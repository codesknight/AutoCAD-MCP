using Autodesk.AutoCAD.Runtime;

[assembly: CommandClass(typeof(AutoCADBridge.NativeTests.Commands))]
namespace AutoCADBridge.NativeTests;

// Explicitly NETLOADed opt-in fixture. No listener, network endpoint or startup hook.
public static class Commands
{
    [CommandMethod("CAD09_BUSY5", CommandFlags.Session)]
    public static void Busy() => Hold(false);

    [CommandMethod("CAD09_BUSY5_STOP", CommandFlags.Session)]
    public static void BusyAndStop() => Hold(true);

    private static void Hold(bool stop)
    {
        using var entered = new EventWaitHandle(false, EventResetMode.ManualReset,
            @"Local\AutoCADMCP-CAD09-" + Environment.ProcessId);
        entered.Set();
        try {
            Thread.Sleep(5000);
            if (stop) Plugin.Stop();
        }
        finally { entered.Reset(); }
    }
}
