using Autodesk.AutoCAD.Runtime;
using System.IO;
using System.Text.Json.Nodes;
using AcApp = Autodesk.AutoCAD.ApplicationServices.Core.Application;

[assembly: ExtensionApplication(typeof(AutoCADBridge.Plugin))]
[assembly: CommandClass(typeof(AutoCADBridge.Plugin))]
namespace AutoCADBridge;

public sealed class Plugin : IExtensionApplication
{
    private static BridgeServer? server;
    public void Initialize() { } // Explicit command only; NETLOAD never opens a listener.
    public void Terminate() => Stop();

    [CommandMethod("MCPBRIDGE_START", CommandFlags.Session)]
    public static void Start()
    {
        if (server is not null) { Message("Bridge already running"); return; }
        try {
            var token = Environment.GetEnvironmentVariable("AUTOCAD_BRIDGE_TOKEN") ?? "";
            var portText = Environment.GetEnvironmentVariable("AUTOCAD_BRIDGE_PORT") ?? "8765";
            // COM activation does not inherit the calling Python process's environment.
            // A per-user local settings file supports that launch mode as well as GUI starts.
            var settingsPath = Path.Combine(Path.GetDirectoryName(typeof(Plugin).Assembly.Location)!, "bridge-settings.json");
            if (token.Length == 0 && File.Exists(settingsPath)) {
                if (new FileInfo(settingsPath).Length > 8192) throw new InvalidOperationException("Bridge settings file is too large");
                var settings = JsonNode.Parse(File.ReadAllText(settingsPath))!.AsObject();
                token = settings["token"]?.GetValue<string>() ?? "";
                portText = Convert.ToString(settings["port"]?.GetValue<int>() ?? 8765);
            }
            if (token.Length < 32) throw new InvalidOperationException("Set AUTOCAD_BRIDGE_TOKEN to at least 32 random characters before starting AutoCAD");
            var port = int.Parse(portText);
            if (port < 1024 || port > 65535) throw new InvalidOperationException("Bridge port must be between 1024 and 65535");
            var candidate = new BridgeServer(token, port);
            try { candidate.Start(); server = candidate; }
            catch { candidate.Dispose(); throw; }
            Message($"Bridge listening on 127.0.0.1:{port}");
        } catch (System.Exception ex) {
            Diagnostics.Record("start", ex);
            Message("Bridge start failed; inspect the local AutoCAD-MCP bridge.log");
        }
    }

    [CommandMethod("MCPBRIDGE_STOP", CommandFlags.Session)]
    public static void Stop() {
        var current = server;
        server = null;
        try { current?.Dispose(); }
        catch (System.Exception ex) { Diagnostics.Record("stop", ex); }
    }

    [CommandMethod("MCPBRIDGE_STATUS", CommandFlags.Session)]
    public static void Status() => Message(server is null ? "Bridge stopped" : "Bridge running: " + server.InstanceId);
    private static void Message(string value) {
        try { AcApp.DocumentManager.MdiActiveDocument?.Editor.WriteMessage("\n" + value + "\n"); }
        catch (System.Exception ex) { Diagnostics.Record("message", ex); }
    }
}
