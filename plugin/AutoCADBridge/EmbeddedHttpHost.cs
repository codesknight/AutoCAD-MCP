using System.IO;
using System.Net;
using Microsoft.AspNetCore.Builder;
using Microsoft.AspNetCore.Hosting;
using Microsoft.AspNetCore.Http;
using Microsoft.AspNetCore.Hosting.Server;
using Microsoft.AspNetCore.Hosting.Server.Features;
using Microsoft.Extensions.DependencyInjection;
using Microsoft.Extensions.Hosting;
using Microsoft.Extensions.Logging;

namespace AutoCADBridge;

/// <summary>A network host whose async lifecycle never captures the CAD UI context.</summary>
public sealed class EmbeddedHttpHost
{
    private readonly WebApplication application;
    private readonly object gate = new();
    private Task? shutdown;
    public string Address { get; private set; } = "";

    public EmbeddedHttpHost(int port, RequestDelegate handler)
    {
        var builder = WebApplication.CreateSlimBuilder(new WebApplicationOptions {
            ApplicationName = typeof(EmbeddedHttpHost).Assembly.FullName,
            ContentRootPath = Path.GetDirectoryName(typeof(EmbeddedHttpHost).Assembly.Location)!
        });
        builder.Logging.ClearProviders();
        builder.Services.AddSingleton<IHostLifetime, EmbeddedLifetime>();
        builder.Services.Configure<HostOptions>(options => options.ShutdownTimeout = TimeSpan.FromSeconds(3));
        builder.WebHost.ConfigureKestrel(options => {
            options.Listen(IPAddress.Loopback, port);
            options.Limits.MaxRequestBodySize = 1024 * 1024;
        });
        application = builder.Build();
        application.Run(handler);
    }

    public void Start()
    {
        Task.Run(() => application.StartAsync()).GetAwaiter().GetResult();
        Address = application.Services.GetRequiredService<IServer>()
            .Features.Get<IServerAddressesFeature>()!.Addresses.Single();
    }

    public Task StopAsync()
    {
        lock (gate) return shutdown ??= Task.Run(async () => {
            try {
                using var timeout = new CancellationTokenSource(TimeSpan.FromSeconds(3));
                await application.StopAsync(timeout.Token).ConfigureAwait(false);
            } catch (Exception exception) {
                Diagnostics.Record("http-stop", exception);
            } finally {
                try {
                    await application.DisposeAsync().AsTask()
                        .WaitAsync(TimeSpan.FromSeconds(5)).ConfigureAwait(false);
                } catch (Exception exception) {
                    Diagnostics.Record("http-dispose", exception);
                }
            }
        });
    }

    private sealed class EmbeddedLifetime : IHostLifetime
    {
        public Task WaitForStartAsync(CancellationToken cancellationToken) => Task.CompletedTask;
        public Task StopAsync(CancellationToken cancellationToken) => Task.CompletedTask;
    }
}
