using System.Text.Json.Nodes;
using Autodesk.AutoCAD.DatabaseServices;
using Autodesk.AutoCAD.Geometry;
using Autodesk.AutoCAD.GraphicsInterface;

namespace AutoCADBridge;

public static class DrawingOperations
{
    public sealed record Created(Entity Entity,Point3d[]? Vertices=null,bool Closed=false);
    public static readonly string[] Names=["draw_rectangle","draw_polyline","draw_text","draw_mtext","add_dimension"];
    private static Point3d Point(JsonNode? value) {
        var a=value?.AsArray();
        if(a is null || a.Count!=3) throw new BridgeException("INVALID_ARGUMENT","Expected a three-coordinate point");
        var v=a.Select(x=>x?.GetValue<double>() ?? double.NaN).ToArray();
        if(v.Any(x=>!double.IsFinite(x))) throw new BridgeException("INVALID_ARGUMENT","Coordinates must be finite");
        return new(v[0],v[1],v[2]);
    }
    private static double Number(JsonObject args,string name,double fallback=double.NaN,bool positive=false) {
        var value=args[name]?.GetValue<double>() ?? fallback;
        if(!double.IsFinite(value)||(positive&&value<=0)) throw new BridgeException("INVALID_ARGUMENT",name+" must be finite"+(positive?" and positive":""));
        return value;
    }
    private static string Text(JsonObject args) {
        var value=args["text"]?.GetValue<string>() ?? "";
        if(value.Length is <1 or >16384 || value.Contains('\0')) throw new BridgeException("INVALID_ARGUMENT","Text must contain 1–16384 characters without NUL");
        return value;
    }
    private static ObjectId CjkStyle(Database db,Transaction tr) {
        var table=(TextStyleTable)tr.GetObject(db.TextStyleTableId,OpenMode.ForRead);
        if(table.Has("MCP_CJK")) return table["MCP_CJK"];
        table.UpgradeOpen();
        using var style=new TextStyleTableRecord { Name="MCP_CJK",Font=new FontDescriptor("SimSun",false,false,134,0) };
        var id=table.Add(style);tr.AddNewlyCreatedDBObject(style,true);return id;
    }
    public static Created Create(string operation,JsonObject args,Database db,Transaction tr) {
        try {
            if(operation is "draw_rectangle" or "draw_polyline") {
                Point3d[] points;
                bool closed;
                if(operation=="draw_rectangle") {
                    var a=Point(args["corner1"]);var b=Point(args["corner2"]);
                    if(a.X==b.X||a.Y==b.Y) throw new BridgeException("INVALID_ARGUMENT","Rectangle must have nonzero width and height");
                    points=[new(a.X,a.Y,0),new(b.X,a.Y,0),new(b.X,b.Y,0),new(a.X,b.Y,0)];closed=true;
                } else {
                    var values=args["points"]?.AsArray();
                    if(values is null || values.Count is <2 or >10000) throw new BridgeException("INVALID_ARGUMENT","Polyline requires 2–10000 points");
                    points=values.Select(Point).Select(p=>new Point3d(p.X,p.Y,0)).ToArray();
                    closed=args["closed"]?.GetValue<bool>() ?? false;
                }
                // Match legacy ActiveX AddPolyline: OCS XY vertices, input Z ignored,
                // heavyweight AcDb2dPolyline at the target model-space elevation.
                // Add the parent to the database before AppendVertex. The bulk
                // construction path failed with a native db2dpoly.cpp
                // eInvalidInput in real AutoCAD 2026; do not use that path.
                var poly=new Polyline2d();poly.SetDatabaseDefaults(db);poly.Elevation=db.Elevation;
                return new(poly,points,closed);
            }
            if(operation=="draw_text") {
                var p=Point(args["position"]);var text=Text(args);
                var height=Number(args,"height",positive:true);
                var rotation=Number(args,"rotation",0)*Math.PI/180;
                var style=CjkStyle(db,tr);
                var entity=new DBText();entity.SetDatabaseDefaults(db);
                entity.Position=p;entity.TextString=text;entity.Height=height;entity.Rotation=rotation;entity.TextStyleId=style;
                return new(entity);
            }
            if(operation=="draw_mtext") {
                var p=Point(args["position"]);var text=Text(args);
                var width=Number(args,"width",100,positive:true);var height=Number(args,"height",2.5,positive:true);
                var style=CjkStyle(db,tr);
                var entity=new MText();entity.SetDatabaseDefaults(db);
                entity.Attachment=AttachmentPoint.TopLeft;entity.Location=p;entity.Width=width;
                entity.TextHeight=height;entity.TextStyleId=style;entity.Contents=text;
                return new(entity);
            }
            if(operation=="add_dimension") {
                var a=Point(args["start"]);var b=Point(args["end"]);var p=Point(args["text_position"]);
                if(a.IsEqualTo(b)) throw new BridgeException("INVALID_ARGUMENT","Dimension endpoints must differ");
                if(a.Z!=b.Z||a.Z!=p.Z) throw new BridgeException("INVALID_ARGUMENT","HTTP aligned dimensions currently require a common WCS Z plane");
                var entity=new AlignedDimension(a,b,p,"",db.Dimstyle);entity.SetDatabaseDefaults(db);return new(entity);
            }
            throw new BridgeException("UNSUPPORTED_OPERATION","Drawing operation is unsupported");
        } catch(Exception ex) when(ex is InvalidOperationException or FormatException or OverflowException) {
            throw new BridgeException("INVALID_ARGUMENT","Invalid drawing argument types");
        }
    }
}
