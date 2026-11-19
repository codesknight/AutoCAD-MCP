using System.Text.Json.Nodes;
using Autodesk.AutoCAD.DatabaseServices;

namespace AutoCADBridge;

public sealed partial class CadOperations
{
    public static readonly string[] VerificationFields = ["linetype", "linetype_scale", "lineweight", "color_index", "layer_properties",
        "normal", "start_angle", "end_angle", "arc_length", "elevation", "bulges", "text_override", "geometry_complete"];
    private static bool GeometrySupported(Entity entity) => entity is Line or Circle or Arc or DBText or MText or AlignedDimension ||
        entity is Polyline2d { PolyType: Poly2dType.SimplePoly };
    private static void AddVerificationFields(JsonObject result, Entity entity, Transaction tr, Func<string, bool> want) {
        JsonArray Vector(Autodesk.AutoCAD.Geometry.Vector3d v) => new(v.X, v.Y, v.Z);
        if (want("geometry_complete")) result["geometry_complete"] = GeometrySupported(entity);
        if (want("linetype")) result["linetype"] = entity.Linetype;
        if (want("linetype_scale")) result["linetype_scale"] = entity.LinetypeScale;
        if (want("lineweight")) result["lineweight"] = (int)entity.LineWeight;
        if (want("color_index")) result["color_index"] = entity.ColorIndex;
        if (want("layer_properties")) {
            var layer = (LayerTableRecord)tr.GetObject(entity.LayerId, OpenMode.ForRead);
            result["layer_properties"] = new JsonObject { ["name"] = layer.Name, ["color_index"] = layer.Color.ColorIndex,
                ["linetype"] = ((LinetypeTableRecord)tr.GetObject(layer.LinetypeObjectId, OpenMode.ForRead)).Name,
                ["lineweight"] = (int)layer.LineWeight, ["is_off"] = layer.IsOff, ["is_frozen"] = layer.IsFrozen, ["is_locked"] = layer.IsLocked };
        }
        if (entity is Arc arc) {
            if (want("center")) result["center"] = XYZ(arc.Center);
            if (want("radius")) result["radius"] = arc.Radius;
            if (want("normal")) result["normal"] = Vector(arc.Normal);
            if (want("start_point")) result["start_point"] = XYZ(arc.StartPoint);
            if (want("end_point")) result["end_point"] = XYZ(arc.EndPoint);
            if (want("start_angle")) result["start_angle"] = arc.StartAngle * 180 / Math.PI;
            if (want("end_angle")) result["end_angle"] = arc.EndAngle * 180 / Math.PI;
            if (want("arc_length")) result["arc_length"] = arc.Length;
        }
        if (entity is Circle circle && want("normal")) result["normal"] = Vector(circle.Normal);
        if (entity is DBText text && want("normal")) result["normal"] = Vector(text.Normal);
        if (entity is MText mtext && want("normal")) result["normal"] = Vector(mtext.Normal);
        if (entity is Polyline2d poly) {
            if (want("normal")) result["normal"] = Vector(poly.Normal);
            if (want("elevation")) result["elevation"] = poly.Elevation;
            if (want("bulges")) {
                var bulges = new JsonArray();
                foreach (Autodesk.AutoCAD.DatabaseServices.ObjectId id in poly) bulges.Add(((Vertex2d)tr.GetObject(id, OpenMode.ForRead)).Bulge);
                result["bulges"] = bulges;
            }
        }
        if (entity is AlignedDimension dim) {
            if (want("normal")) result["normal"] = Vector(dim.Normal);
            if (want("text_override")) result["text_override"] = dim.DimensionText;
        }
    }
}
