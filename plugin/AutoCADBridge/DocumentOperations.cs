using System.IO;
using System.Text.Json.Nodes;
using Autodesk.AutoCAD.ApplicationServices;
using Autodesk.AutoCAD.DatabaseServices;
using AcApp = Autodesk.AutoCAD.ApplicationServices.Core.Application;

namespace AutoCADBridge;

public sealed partial class CadOperations
{
    public static readonly string[] DocumentOperations = ["create_working_document", "get_document_info", "save_document", "reopen_artifact"];
    public static readonly string[] BatchOperations = ["create_layer", "draw_line", "draw_circle", .. DrawingOperations.Names];
    private static readonly Dictionary<string, UnitsValue> Units = new(StringComparer.Ordinal) {
        ["unitless"] = UnitsValue.Undefined, ["millimeters"] = UnitsValue.Millimeters,
        ["centimeters"] = UnitsValue.Centimeters, ["meters"] = UnitsValue.Meters,
        ["inches"] = UnitsValue.Inches, ["feet"] = UnitsValue.Feet
    };
    private sealed record SavedArtifact(string Id, string Path, string DocumentId, long Revision,
        string Hash, long Bytes, string SavedAt, int Units);
    private readonly Dictionary<string, SavedArtifact> artifacts = new();
    private static JsonObject UnitInfo(Database db) => new() { ["code"] = (int)db.Insunits, ["name"] = db.Insunits.ToString() };
    private static JsonObject DocumentInfo(DocumentSession state) => new() {
        ["document_id"] = state.Id, ["name"] = state.Document.Name, ["revision"] = state.Revision,
        ["units"] = UnitInfo(state.Document.Database), ["managed"] = state.Managed,
        ["read_only"] = !state.Managed, ["output_directory"] = state.OutputDirectory,
        ["source_artifact_id"] = state.SourceArtifactId
    };
    private static JsonObject ArtifactInfo(SavedArtifact artifact) => new() {
        ["artifact_id"] = artifact.Id, ["file_path"] = artifact.Path,
        ["source_document_id"] = artifact.DocumentId, ["saved_revision"] = artifact.Revision,
        ["sha256"] = artifact.Hash, ["bytes"] = artifact.Bytes, ["saved_at"] = artifact.SavedAt,
        ["units_code"] = artifact.Units, ["state"] = "saved"
    };
    private (JsonNode?, string?, long?) ExecuteDocument(Request request) {
        // These operations must never enter the entity transaction/rollback wrapper.
        if (request.Operation == "create_working_document") {
            var unit = request.Args["units"]?.GetValue<string>() ?? "millimeters";
            if (!Units.TryGetValue(unit, out var units)) throw new BridgeException("INVALID_ARGUMENT", "Unsupported units");
            var directory = request.Args["output_directory"]?.GetValue<string>() ?? "";
            if (directory.Length == 0) {
                directory = Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData), "AutoCAD-MCP", "outputs", Guid.NewGuid().ToString("N"));
                Directory.CreateDirectory(directory);
            }
            directory = ArtifactFiles.DirectoryPath(directory);
            try {
                var document = AcApp.DocumentManager.Add("acadiso.dwt");
                using (document.LockDocument()) document.Database.Insunits = units;
                var state = Session(document, true); state.OutputDirectory = directory;
                return (DocumentInfo(state), state.Id, state.Revision);
            } catch (Exception) { throw new CadFailure("DOCUMENT_CREATE_FAILED", "Working document creation could not be confirmed; inspect status before any further write", "outcome_unknown"); }
        }
        if (request.Operation == "reopen_artifact") return ReopenArtifact(request);
        var target = Target(request.DocumentId);
        using var documentLock = target.Document.LockDocument();
        if (request.Operation == "get_document_info") {
            var info = DocumentInfo(target);
            using var tr = target.Document.Database.TransactionManager.StartTransaction();
            var db = target.Document.Database;
            var blocks = (BlockTable)tr.GetObject(db.BlockTableId, OpenMode.ForRead);
            var model = (BlockTableRecord)tr.GetObject(blocks[BlockTableRecord.ModelSpace], OpenMode.ForRead);
            var layers = ((LayerTable)tr.GetObject(db.LayerTableId, OpenMode.ForRead)).Cast<ObjectId>()
                .Select(id => ((LayerTableRecord)tr.GetObject(id, OpenMode.ForRead)).Name).ToArray();
            var styles = ((TextStyleTable)tr.GetObject(db.TextStyleTableId, OpenMode.ForRead)).Cast<ObjectId>()
                .Select(id => ((TextStyleTableRecord)tr.GetObject(id, OpenMode.ForRead)).Name).ToArray();
            info["model_space_count"] = model.Cast<ObjectId>().Count();
            info["layer_names"] = new JsonArray(layers.Take(1000).Select(x => (JsonNode?)JsonValue.Create(x)).ToArray());
            info["text_style_names"] = new JsonArray(styles.Take(1000).Select(x => (JsonNode?)JsonValue.Create(x)).ToArray());
            info["catalogs_truncated"] = layers.Length > 1000 || styles.Length > 1000;
            return (info, target.Id, target.Revision);
        }
        if (!target.Managed || target.OutputDirectory is null) throw new BridgeException("FORBIDDEN", "Saving requires an explicitly created working document with a bound output directory");
        if (request.ExpectedRevision is null) throw new BridgeException("INVALID_ARGUMENT", "Saving requires expected_revision");
        if (request.ExpectedRevision != target.Revision) throw new BridgeException("REVISION_CONFLICT", "Document changed before save; read its revision again");
        if (artifacts.Count >= 2048) throw new BridgeException("QUEUE_FULL", "Artifact registry is full for this instance");
        var path = ArtifactFiles.Destination(target.OutputDirectory, request.Args["file_name"]?.GetValue<string>() ?? "");
        var temporary = Path.Combine(target.OutputDirectory, ".mcp-" + Guid.NewGuid().ToString("N") + ".dwg");
        var revision = target.Revision;
        try {
            // false means full copy-save without renaming the editor document or
            // generating .bak. Publish with a no-replace move only after SaveAs returns.
            target.Document.Database.SaveAs(temporary, false, DwgVersion.Current, target.Document.Database.SecurityParameters);
            var (hash, bytes) = ArtifactFiles.Fingerprint(temporary);
            ArtifactFiles.DirectoryPath(target.OutputDirectory);
            File.Move(temporary, path, false);
            var artifact = new SavedArtifact(Guid.NewGuid().ToString("N"), path, target.Id, revision,
                hash, bytes, DateTime.UtcNow.ToString("O"), (int)target.Document.Database.Insunits);
            artifacts.Add(artifact.Id, artifact);
            return (ArtifactInfo(artifact), target.Id, target.Revision);
        } catch (Exception) {
            throw new CadFailure("FILE_OPERATION_FAILED", "Save/publication could not be confirmed; inspect the job and output path. No database rollback is claimed", "outcome_unknown");
        } finally {
            try { if (File.Exists(temporary)) File.Delete(temporary); } catch (IOException) { } catch (UnauthorizedAccessException) { }
        }
    }
    private (JsonNode?, string?, long?) ReopenArtifact(Request request) {
        var id = request.Args["artifact_id"]?.GetValue<string>() ?? "";
        if (!artifacts.TryGetValue(id, out var artifact)) throw new BridgeException("ARTIFACT_NOT_FOUND", "Only artifacts saved by this Bridge instance may be reopened");
        ArtifactFiles.DirectoryPath(Path.GetDirectoryName(artifact.Path)!);
        if (!File.Exists(artifact.Path)) throw new BridgeException("ARTIFACT_NOT_FOUND", "Saved artifact is missing");
        if ((File.GetAttributes(artifact.Path) & FileAttributes.ReparsePoint) != 0) throw new BridgeException("FORBIDDEN", "Artifact cannot be a reparse point");
        var before = ArtifactFiles.Fingerprint(artifact.Path);
        if (before.Hash != artifact.Hash || before.Bytes != artifact.Bytes) throw new BridgeException("ARTIFACT_CHANGED", "Saved file differs from the recorded artifact");
        try {
            var document = AcApp.DocumentManager.Open(artifact.Path, true);
            var after = ArtifactFiles.Fingerprint(artifact.Path);
            if (after != before) throw new IOException("Artifact changed while opening");
            var state = Session(document); state.SourceArtifactId = artifact.Id;
            var result = DocumentInfo(state); result["artifact"] = ArtifactInfo(artifact);
            return (result, state.Id, state.Revision);
        } catch (Exception) { throw new CadFailure("REOPEN_FAILED", "Artifact reopen could not be confirmed; inspect status. No rollback or write permission is implied", "outcome_unknown"); }
    }
}
