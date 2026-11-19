using System.Text.Json.Nodes;
using Autodesk.AutoCAD.ApplicationServices;
using Autodesk.AutoCAD.DatabaseServices;
using Autodesk.AutoCAD.Geometry;
using Autodesk.AutoCAD.Colors;
using AcApp = Autodesk.AutoCAD.ApplicationServices.Core.Application;

namespace AutoCADBridge;

public sealed class CadFailure(string code, string message, string outcome, string? failedId = null) : Exception(message)
{
    public string Code { get; } = code;
    public string Outcome { get; } = outcome;
    public string? FailedOperationId { get; } = failedId;
}

public sealed class DocumentSession : IDisposable
{
    public string Id { get; } = Guid.NewGuid().ToString("N");
    public Document Document { get; }
    public bool Managed { get; }
    public long Revision;
    private long nextAlias;
    private readonly Dictionary<ObjectId, long> aliases = new();
    private readonly Dictionary<long, ObjectId> ids = new();
    public DocumentSession(Document document, bool managed) {
        Document = document; Managed = managed;
        document.Database.ObjectAppended += Changed;
        document.Database.ObjectModified += Changed;
        document.Database.ObjectErased += Erased;
    }
    private void Changed(object sender, ObjectEventArgs e) => Interlocked.Increment(ref Revision);
    private void Erased(object sender, ObjectErasedEventArgs e) => Interlocked.Increment(ref Revision);
    public long Alias(ObjectId id) {
        if (!aliases.TryGetValue(id, out var alias)) { alias = ++nextAlias; aliases[id] = alias; ids[alias] = id; }
        return alias;
    }
    public ObjectId Find(long alias) => ids.TryGetValue(alias, out var id) && !id.IsErased ? id : throw new BridgeException("ENTITY_NOT_FOUND", "Entity alias does not belong to this document session");
    public void Dispose() {
        try {
            Document.Database.ObjectAppended -= Changed;
            Document.Database.ObjectModified -= Changed;
            Document.Database.ObjectErased -= Erased;
        } catch (Exception) { }
    }
}

public sealed class CadOperations : IDisposable
{
    private readonly QueryCursor cursors = new();
    private readonly Dictionary<string, DocumentSession> sessions = new();
    private static readonly string[] Writes = ["draw_line", "draw_circle", "create_layer", "_batch"];
    private DocumentSession Session(Document document, bool managed = false) {
        var old = sessions.Values.FirstOrDefault(s => ReferenceEquals(s.Document, document));
        if (old is not null) return old;
        var state = new DocumentSession(document, managed); sessions[state.Id] = state; return state;
    }
    private DocumentSession Target(string? id) {
        if (id is null || !sessions.TryGetValue(id, out var state) || !AcApp.DocumentManager.Cast<Document>().Any(d => ReferenceEquals(d, state.Document)))
            throw new BridgeException("DOCUMENT_NOT_FOUND", "Document session is missing or closed");
        return state;
    }
    public (JsonNode? Result, string? DocumentId, long? Revision) Execute(Request request) {
        if (request.Operation == "_status") {
            var active = AcApp.DocumentManager.MdiActiveDocument;
            var documents = new JsonArray();
            foreach (Document document in AcApp.DocumentManager) {
                var state = Session(document);
                documents.Add(new JsonObject { ["document_id"] = state.Id, ["name"] = document.Name,
                    ["managed"] = state.Managed, ["revision"] = state.Revision,
                    ["active"] = ReferenceEquals(active, document) });
            }
            return (new JsonObject { ["documents"] = documents, ["active_document_id"] = active is null ? null : Session(active).Id,
                ["cad_version"] = Convert.ToString(AcApp.GetSystemVariable("ACADVER")), ["revision_mode"] = "observed_database_events" }, null, null);
        }
        if (request.Operation == "new_document") {
            var document = AcApp.DocumentManager.Add("acadiso.dwt");
            var state = Session(document, true);
            return (JsonValue.Create(document.Name), state.Id, state.Revision);
        }
        var target = Target(request.DocumentId);
        if (Writes.Contains(request.Operation) && !target.Managed) throw new BridgeException("FORBIDDEN", "Writes require a Bridge-created document");
        if (request.ExpectedRevision is { } revision && revision != target.Revision) throw new BridgeException("REVISION_CONFLICT", "Read the document revision again before applying changes");
        using var documentLock = target.Document.LockDocument();
        using var transaction = target.Document.Database.TransactionManager.StartTransaction();
        string? failedId = null;
        try {
            JsonNode? result;
            if (request.Operation == "_batch") {
                if (request.Args["atomic"]?.GetValue<bool>() != true) throw new BridgeException("INVALID_ARGUMENT", "Only atomic:true is supported");
                var operations = request.Args["operations"]?.AsArray() ?? throw new BridgeException("INVALID_ARGUMENT", "operations must be an array");
                if (operations.Count is < 1 or > 200) throw new BridgeException("INVALID_ARGUMENT", "Batch must contain 1 to 200 operations");
                var results = new JsonArray(); var operationIds = new HashSet<string>(StringComparer.Ordinal);
                foreach (var item in operations) {
                    var op = item?.AsObject() ?? throw new BridgeException("INVALID_ARGUMENT", "Invalid batch operation");
                    failedId = op["id"]?.GetValue<string>() ?? throw new BridgeException("INVALID_ARGUMENT", "Each batch operation needs an id");
                    if (failedId.Length is < 1 or > 128 || !operationIds.Add(failedId)) throw new BridgeException("INVALID_ARGUMENT", "Batch operation IDs must be nonempty and unique");
                    var name = op["operation"]?.GetValue<string>() ?? "";
                    if (name is not ("draw_line" or "draw_circle" or "create_layer")) throw new BridgeException("UNSUPPORTED_OPERATION", "Operation is not transactional batch-safe");
                    var value = Run(target, transaction, name, op["args"]?.AsObject() ?? new JsonObject());
                    results.Add(new JsonObject { ["id"] = failedId, ["result"] = value });
                }
                result = results;
            } else if (request.Operation == "query_entities_page") result = Page(target,transaction,request.Args);
            else result = Run(target, transaction, request.Operation, request.Args);
            transaction.Commit();
            return (result, target.Id, target.Revision);
        } catch (BridgeException ex) {
            transaction.Abort();
            throw new CadFailure(ex.Code, ex.Message, "rolled_back", failedId);
        } catch (Exception) {
            transaction.Abort();
            throw new CadFailure("TRANSACTION_FAILED", "CAD transaction failed and was rolled back", "rolled_back", failedId);
        }
    }

    private static Point3d Point(JsonObject args, string name) {
        var value = args[name]?.AsArray();
        if (value is null || value.Count != 3) throw new BridgeException("INVALID_ARGUMENT", name + " must contain three WCS coordinates");
        var point = value.Select(v => v?.GetValue<double>() ?? double.NaN).ToArray();
        if (point.Any(v => !double.IsFinite(v))) throw new BridgeException("INVALID_ARGUMENT", "Coordinates must be finite");
        return new Point3d(point[0], point[1], point[2]);
    }
    private static JsonArray XYZ(Point3d p) => new(p.X, p.Y, p.Z);
    private static JsonNode? Run(DocumentSession state, Transaction tr, string operation, JsonObject args) {
        var db = state.Document.Database;
        var layers = (LayerTable)tr.GetObject(db.LayerTableId, OpenMode.ForRead);
        if (operation == "list_layers") return new JsonArray(layers.Cast<ObjectId>().Select(id => (JsonNode?)JsonValue.Create(((LayerTableRecord)tr.GetObject(id, OpenMode.ForRead)).Name)).ToArray());
        if (operation == "create_layer") {
            var name = args["name"]?.GetValue<string>();
            if (string.IsNullOrWhiteSpace(name)) throw new BridgeException("INVALID_ARGUMENT", "Layer name is required");
            SymbolUtilityServices.ValidateSymbolName(name, false);
            LayerTableRecord layer;
            if (layers.Has(name)) layer = (LayerTableRecord)tr.GetObject(layers[name], OpenMode.ForWrite);
            else {
                layers.UpgradeOpen(); layer = new LayerTableRecord { Name = name };
                layers.Add(layer); tr.AddNewlyCreatedDBObject(layer, true);
            }
            if (args["color"] is { } color) {
                var aci = color.GetValue<int>();
                if (aci is < 1 or > 255) throw new BridgeException("INVALID_ARGUMENT", "Layer color must be an ACI from 1 to 255");
                layer.Color = Autodesk.AutoCAD.Colors.Color.FromColorIndex(ColorMethod.ByAci, (short)aci);
            }
            return null;
        }
        if (operation == "get_entity") {
            var alias = args["object_id"]?.GetValue<long>() ?? throw new BridgeException("INVALID_ARGUMENT", "object_id is required");
            return Summary(state, (Entity)tr.GetObject(state.Find(alias), OpenMode.ForRead));
        }
        var blocks = (BlockTable)tr.GetObject(db.BlockTableId, OpenMode.ForRead);
        var model = (BlockTableRecord)tr.GetObject(blocks[BlockTableRecord.ModelSpace], operation.StartsWith("draw_", StringComparison.Ordinal) ? OpenMode.ForWrite : OpenMode.ForRead);
        if (operation == "query_entities") {
            var type = args["entity_type"]?.GetValue<string>(); var result = new JsonArray();
            foreach (ObjectId id in model) {
                var entity = (Entity)tr.GetObject(id, OpenMode.ForRead);
                if (!string.IsNullOrEmpty(type) && entity.GetRXClass().Name != type) continue;
                if (result.Count == 1000) throw new BridgeException("RESULT_TOO_LARGE", "Legacy query exceeds 1000 entities; use query_entities_page");
                result.Add(Summary(state, entity));
            }
            return result;
        }
        Entity created;
        if (operation == "draw_line") {
            var start = Point(args, "start"); var end = Point(args, "end");
            if (start.IsEqualTo(end)) throw new BridgeException("INVALID_ARGUMENT", "Line must have nonzero length");
            created = new Line(start, end);
        } else if (operation == "draw_circle") {
            var radius = args["radius"]?.GetValue<double>() ?? double.NaN;
            if (!double.IsFinite(radius) || radius <= 0) throw new BridgeException("INVALID_ARGUMENT", "Radius must be finite and positive");
            created = new Circle(Point(args, "center"), Vector3d.ZAxis, radius);
        } else throw new BridgeException("UNSUPPORTED_OPERATION", "Operation is not supported by this Bridge");
        using (created) {
            var layerName = args["layer"]?.GetValue<string>() ?? "0";
            if (!layers.Has(layerName)) throw new BridgeException("INVALID_ARGUMENT", "Layer does not exist");
            created.SetDatabaseDefaults(db); created.Layer = layerName;
            var id = model.AppendEntity(created); tr.AddNewlyCreatedDBObject(created, true);
            return JsonValue.Create(state.Alias(id));
        }
    }

    private JsonObject Page(DocumentSession state,Transaction tr,JsonObject args) {
        var allowed=new HashSet<string>(["entity_type","layer","fields","limit","cursor"],StringComparer.Ordinal);
        var all=new HashSet<string>(["object_id","type","layer","handle","start_point","end_point","center","radius","bounding_box"],StringComparer.Ordinal);
        int limit;
        string type,layer,token;
        HashSet<string> wanted;
        try {
            if (args.Any(p=>!allowed.Contains(p.Key))) throw new BridgeException("INVALID_ARGUMENT","Unknown page argument");
            limit=args["limit"]?.GetValue<int>() ?? 200;
            type=args["entity_type"]?.GetValue<string>() ?? "";
            layer=args["layer"]?.GetValue<string>() ?? "";
            token=args["cursor"]?.GetValue<string>() ?? "";
            if (limit is <1 or >1000 || type.Length>128 || layer.Length>255 || token.Length>2048)
                throw new BridgeException("INVALID_ARGUMENT","Invalid page limit or filter length");
            var values=args["fields"]?.AsArray();
            wanted=values is null || values.Count==0 ? new HashSet<string>(all,StringComparer.Ordinal) : new(StringComparer.Ordinal);
            if (values is not null && values.Count>0) {
                if (values.Count>all.Count) throw new BridgeException("INVALID_ARGUMENT","Too many fields");
                foreach(var field in values) {
                    var name=field?.GetValue<string>() ?? "";
                    if (!all.Contains(name) || !wanted.Add(name))
                        throw new BridgeException("INVALID_ARGUMENT","Fields must be supported and unique");
                }
            }
        } catch (Exception ex) when (ex is InvalidOperationException or FormatException or OverflowException) {
            throw new BridgeException("INVALID_ARGUMENT","Invalid page argument types");
        }
        wanted.UnionWith(["object_id","type","layer"]);
        var fieldArray=new JsonArray(wanted.OrderBy(x=>x,StringComparer.Ordinal).Select(x=>(JsonNode?)JsonValue.Create(x)).ToArray());
        var query=new JsonObject { ["entity_type"]=type,["layer"]=layer,["fields"]=fieldArray,["limit"]=limit };
        var fingerprint=Convert.ToHexString(System.Security.Cryptography.SHA256.HashData(System.Text.Encoding.UTF8.GetBytes(Journal.Canonical(query))));
        var offset=string.IsNullOrEmpty(token) ? 0 : cursors.Read(token,state.Id,state.Revision,fingerprint);
        var blocks=(BlockTable)tr.GetObject(state.Document.Database.BlockTableId,OpenMode.ForRead);
        var model=(BlockTableRecord)tr.GetObject(blocks[BlockTableRecord.ModelSpace],OpenMode.ForRead);
        var items=new JsonArray();
        var unsupported=new HashSet<string>(StringComparer.Ordinal);
        var matched=0;
        var more=false;
        foreach(ObjectId id in model) {
            var entity=(Entity)tr.GetObject(id,OpenMode.ForRead);
            var name=entity.GetRXClass().Name;
            if (type.Length>0 && name!=type) continue;
            if (layer.Length>0 && !string.Equals(entity.Layer,layer,StringComparison.OrdinalIgnoreCase)) continue;
            if (matched++<offset) continue;
            if (items.Count==limit) { more=true;break; }
            items.Add(Summary(state,entity,wanted));
            if (entity is not (Line or Circle)) unsupported.Add(name);
        }
        return new JsonObject { ["document_id"]=state.Id,["revision"]=state.Revision,
            ["items"]=items,["count"]=items.Count,["has_more"]=more,
            ["next_cursor"]=more ? cursors.Create(state.Id,state.Revision,offset+items.Count,fingerprint) : null,
            ["unsupported_geometry_types"]=new JsonArray(unsupported.OrderBy(x=>x,StringComparer.Ordinal).Select(x=>(JsonNode?)JsonValue.Create(x)).ToArray()) };
    }
    private static JsonObject Summary(DocumentSession state, Entity entity, HashSet<string>? fields=null) {
        bool Want(string name)=>fields is null || fields.Contains(name);
        var result = new JsonObject { ["object_id"] = state.Alias(entity.ObjectId), ["type"] = entity.GetRXClass().Name,
            ["layer"] = entity.Layer };
        if (Want("handle")) result["handle"]=entity.Handle.ToString();
        if (entity is Line line) { if(Want("start_point"))result["start_point"] = XYZ(line.StartPoint); if(Want("end_point"))result["end_point"] = XYZ(line.EndPoint); }
        if (entity is Circle circle) { if(Want("center"))result["center"] = XYZ(circle.Center); if(Want("radius"))result["radius"] = circle.Radius; }
        if (Want("bounding_box")) try { var bounds = entity.GeometricExtents; result["bounding_box"] = new JsonObject { ["min"] = XYZ(bounds.MinPoint), ["max"] = XYZ(bounds.MaxPoint) }; } catch (Exception) { }
        return result;
    }
    public void Dispose() { foreach (var session in sessions.Values) session.Dispose(); sessions.Clear(); }
}
