using AutoCADBridge;
using Microsoft.AspNetCore.Http;

var savedContext = SynchronizationContext.Current;
var assertions = 0;
try {
    SynchronizationContext.SetSynchronizationContext(new NonPumpingUiContext());
    for (var index = 0; index < 3; index++) {
        var host = new EmbeddedHttpHost(0, context => context.Response.WriteAsync("ok"));
        host.Start();
        using var client = new HttpClient(new HttpClientHandler { UseProxy = false });
        if (client.GetStringAsync(host.Address).GetAwaiter().GetResult() != "ok")
            throw new Exception("Embedded Kestrel request failed");
        assertions++;
        var shutdown = host.StopAsync();
        if (!ReferenceEquals(shutdown, host.StopAsync()))
            throw new Exception("Shutdown was not idempotent");
        assertions++;
        if (!shutdown.Wait(TimeSpan.FromSeconds(10)))
            throw new Exception("Shutdown captured or blocked the native UI context");
        assertions++;
        try {
            client.GetStringAsync(host.Address).GetAwaiter().GetResult();
            throw new Exception("Listener remained open after shutdown");
        } catch (HttpRequestException) { assertions++; }
    }
} finally {
    SynchronizationContext.SetSynchronizationContext(savedContext);
}
Console.WriteLine($"{assertions} embedded hosting assertions passed without a pumping UI context");

sealed class NonPumpingUiContext : SynchronizationContext
{
    public override void Post(SendOrPostCallback callback, object? state) =>
        throw new Exception("Network lifecycle attempted to use the CAD UI context");
    public override void Send(SendOrPostCallback callback, object? state) =>
        throw new Exception("Network lifecycle attempted to synchronously use the CAD UI context");
}
