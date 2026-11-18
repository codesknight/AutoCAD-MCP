using System.IO;

namespace AutoCADBridge;

internal static class Diagnostics
{
    private static readonly object gate = new();
    public static void Record(string stage, Exception exception)
    {
        // Local diagnostics only. This must never throw into the native host.
        try {
            lock (gate) {
                var directory = Path.Combine(Environment.GetFolderPath(
                    Environment.SpecialFolder.LocalApplicationData), "AutoCAD-MCP", "Logs");
                Directory.CreateDirectory(directory);
                var path = Path.Combine(directory, "bridge.log");
                if (File.Exists(path) && new FileInfo(path).Length > 1024 * 1024)
                    File.Move(path, Path.Combine(directory, "bridge.previous.log"), true);
                File.AppendAllText(path, $"{DateTime.UtcNow:O} [{stage}] {exception}\n");
            }
        } catch { }
    }
}
