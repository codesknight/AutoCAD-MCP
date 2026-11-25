using Autodesk.AutoCAD.Runtime;
using System.Runtime.InteropServices;
using System.Runtime.InteropServices.ComTypes;

[assembly: CommandClass(typeof(AutoCADBridge.NativeTests.Commands))]
[assembly: ExtensionApplication(typeof(AutoCADBridge.NativeTests.InstanceFixture))]
namespace AutoCADBridge.NativeTests;

// Test-only explicit targeting of a dedicated CAD process. AutoCAD registers
// duplicate application monikers; GetActiveObject may always select the user's
// first process. Never install this helper as an auto-loaded production plugin.
public sealed class InstanceFixture : IExtensionApplication
{
    [DllImport("ole32.dll")] private static extern int GetRunningObjectTable(int reserved, out IRunningObjectTable table);
    [DllImport("ole32.dll", CharSet = CharSet.Unicode)] private static extern int CreateItemMoniker(string delimiter, string item, out IMoniker moniker);
    private IRunningObjectTable? table;
    private int cookie;
    public void Initialize() {
        Marshal.ThrowExceptionForHR(GetRunningObjectTable(0, out var rot));
        Marshal.ThrowExceptionForHR(CreateItemMoniker("!", "AutoCADMCP-NativeTests-" + Environment.ProcessId, out var moniker));
        table = rot;
        cookie = rot.Register(1, Autodesk.AutoCAD.ApplicationServices.Application.AcadApplication, moniker);
    }
    public void Terminate() { if (table is not null) table.Revoke(cookie); }
}

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
