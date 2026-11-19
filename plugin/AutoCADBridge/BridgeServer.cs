using System.Collections.Concurrent;
using System.Net;
using System.IO;
using System.Runtime.InteropServices;
using System.Security.Cryptography;
using System.Text;
using System.Text.Json.Nodes;
using System.Text.RegularExpressions;
using Microsoft.AspNetCore.Builder;
using Microsoft.AspNetCore.Hosting;
using Microsoft.AspNetCore.Http;
using Microsoft.Extensions.Logging;
using AcApp = Autodesk.AutoCAD.ApplicationServices.Core.Application;

namespace AutoCADBridge;

public sealed class BridgeServer : IDisposable
{
    public string InstanceId { get; } = Guid.NewGuid().ToString("N");
    private readonly string token;
    private readonly int port;
    private readonly Journal journal = new();
    private readonly ConcurrentQueue<Job> queue = new();
    private readonly object admission = new();
    private readonly CadOperations cad = new();
    private EmbeddedHttpHost? host;
    private volatile bool stopped;
    private nint window;
    [DllImport("user32.dll")]
    private static extern bool PostMessage(nint hwnd, uint message, nint wparam, nint lparam);
    public static readonly string[] Operations = ["new_document", "draw_line", "draw_circle", "create_layer", "list_layers", "query_entities", "get_entity", "query_entities_page"];

    public BridgeServer(string token, int port) { this.token = token; this.port = port; }
    public void Start()
    {
        window = System.Diagnostics.Process.GetCurrentProcess().MainWindowHandle;
        host = new EmbeddedHttpHost(port, Handle);
        host.Start();
        AcApp.Idle += OnIdle;
    }

    private async Task Handle(HttpContext context)
    {
        try {
            if (context.Connection.RemoteIpAddress is not { } remote || !IPAddress.IsLoopback(remote) ||
                context.Request.Host.Host != "127.0.0.1" || context.Request.Host.Port != port ||
                context.Request.Headers.ContainsKey("Origin"))
                throw new BridgeException("FORBIDDEN", "Only local non-browser requests to the configured Host are accepted");
            var supplied = Encoding.UTF8.GetBytes(context.Request.Headers.Authorization.ToString());
            var wanted = Encoding.UTF8.GetBytes("Bearer " + token);
            if (!CryptographicOperations.FixedTimeEquals(supplied, wanted))
                throw new BridgeException("UNAUTHORIZED", "A valid Bridge bearer token is required");
            var path = context.Request.Path.Value ?? "";
            var method = context.Request.Method;
            if (method == "GET" && path == "/v1/health") {
                await Write(context, new JsonObject { ["protocol_version"] = "1", ["status"] = stopped ? "stopping" : "ready",
                    ["process_id"] = Environment.ProcessId }); return;
            }
            if (method == "GET" && path == "/v1/capabilities") {
                await Write(context, new JsonObject { ["protocol_version"] = "1", ["operations"] = new JsonArray(Operations.Select(x => (JsonNode?)JsonValue.Create(x)).ToArray()),
                    ["atomic_batch"] = true, ["max_batch_operations"] = 200, ["max_query_entities"] = 1000,
                    ["query_pagination"] = true,["max_query_page_entities"] = 1000,["cursor_ttl_seconds"] = 600,
                    ["legacy_object_ids"] = "document_session_aliases", ["job_ttl_seconds"] = 600 }); return;
            }
            if (method == "GET" && path == "/v1/status") {
                var job = Accept(new Request(Guid.NewGuid().ToString("N"), null, null, "_status", new JsonObject()));
                try { await Write(context, await job.Completion.Task.WaitAsync(TimeSpan.FromSeconds(3), context.RequestAborted)); }
                catch (TimeoutException) { throw new BridgeException("CAD_BUSY", "CAD did not reach a safe execution context within three seconds"); }
                return;
            }
            if (method == "GET" && path.StartsWith("/v1/jobs/", StringComparison.Ordinal)) {
                await Write(context, journal.Get(path[9..]).Snapshot()); return;
            }
            if (method == "POST" && path is "/v1/execute" or "/v1/batch") {
                if (context.Request.ContentType?.Split(';')[0] != "application/json") throw new BridgeException("INVALID_ARGUMENT", "application/json is required");
                JsonObject data;
                try { data = (await JsonNode.ParseAsync(context.Request.Body, cancellationToken: context.RequestAborted))?.AsObject() ?? throw new Exception(); }
                catch (Exception) { throw new BridgeException("INVALID_ARGUMENT", "Invalid or oversized JSON object"); }
                var id = data["request_id"]?.GetValue<string>() ?? "";
                if (!Regex.IsMatch(id, "^[A-Za-z0-9._-]{1,128}$")) throw new BridgeException("INVALID_ARGUMENT", "Invalid request_id");
                var operation = path == "/v1/batch" ? "_batch" : data["operation"]?.GetValue<string>() ?? "";
                if (operation != "_batch" && !Operations.Contains(operation)) throw new BridgeException("UNSUPPORTED_OPERATION", "Operation is not supported");
                var args = path == "/v1/batch" ? new JsonObject { ["operations"] = data["operations"]?.DeepClone(), ["atomic"] = data["atomic"]?.DeepClone() } : data["args"]?.AsObject() ?? new JsonObject();
                var request = new Request(id, data["document_id"]?.GetValue<string>(), data["expected_revision"]?.GetValue<long>(), operation, args);
                var job = Accept(request);
                await Write(context, job.Snapshot(), job.Completion.Task.IsCompleted ? 200 : 202); return;
            }
            throw new BridgeException("UNSUPPORTED_OPERATION", "Unknown endpoint or method");
        } catch (BridgeException ex) { await Write(context, Error(ex.Code, ex.Message), StatusCode(ex.Code)); }
        catch (OperationCanceledException) { }
        catch (Exception) { await Write(context, Error("INVALID_ARGUMENT", "Request could not be processed"), 400); }
    }

    private Job Accept(Request request)
    {
        lock (admission) {
            if (stopped) throw new BridgeException("CAD_BUSY", "Bridge is stopping");
            var (job, added) = journal.Accept(request);
            if (added) {
                if (queue.Count >= 64) job.Finish(Failure(job.Request, "QUEUE_FULL", "Execution queue is full", "not_executed"));
                else {
                    queue.Enqueue(job);
                    // Wake the UI message loop without calling any CAD API here.
                    if (window != 0) PostMessage(window, 0, 0, 0);
                }
            }
            return job;
        }
    }

    private void OnIdle(object? sender, EventArgs args)
    {
        if (queue.IsEmpty || stopped) return;
        try { DrainQueue(); }
        catch (Exception ex) {
            // Never propagate a managed event-handler exception into AutoCAD.
            Diagnostics.Record("idle", ex);
            lock (admission) {
                stopped = true;
                while (queue.TryDequeue(out var job))
                    job.Finish(Failure(job.Request, "CAD_BUSY", "CAD dispatcher is unavailable", "not_executed"));
            }
        }
    }

    private void DrainQueue()
    {
        if (!string.IsNullOrEmpty(AcApp.DocumentManager.MdiActiveDocument?.CommandInProgress)) return;
        for (var count = 0; count < 4 && queue.TryDequeue(out var job); count++) {
            job.Running();
            var clock = System.Diagnostics.Stopwatch.StartNew();
            try {
                var (result, documentId, revision) = cad.Execute(job.Request);
                job.Finish(new JsonObject { ["request_id"] = job.Request.RequestId, ["status"] = "succeeded",
                    ["document_id"] = documentId, ["revision"] = revision, ["result"] = result, ["error"] = null,
                    ["metrics"] = new JsonObject { ["execution_ms"] = clock.Elapsed.TotalMilliseconds,
                        ["queue_ms"] = (DateTime.UtcNow - job.Created).TotalMilliseconds - clock.Elapsed.TotalMilliseconds } });
            } catch (CadFailure ex) { job.Finish(Failure(job.Request, ex.Code, ex.Message, ex.Outcome, ex.FailedOperationId)); }
            catch (BridgeException ex) { job.Finish(Failure(job.Request, ex.Code, ex.Message, "not_executed")); }
            catch (Exception) { job.Finish(Failure(job.Request, "TRANSACTION_FAILED", "CAD operation failed", "outcome_unknown")); }
        }
    }

    private static JsonObject Error(string code, string message, string outcome = "not_executed", string? failedId = null) => new() {
        ["error"] = new JsonObject { ["code"] = code, ["message"] = message,
            ["retryable"] = code is "CAD_BUSY" or "QUEUE_FULL", ["outcome"] = outcome, ["failed_operation_id"] = failedId }
    };
    private static JsonObject Failure(Request req, string code, string message, string outcome, string? failedId = null) {
        var result = Error(code, message, outcome, failedId);
        result["request_id"] = req.RequestId; result["document_id"] = req.DocumentId;
        result["status"] = outcome == "rolled_back" ? "rolled_back" : "failed"; return result;
    }
    private async Task Write(HttpContext context, JsonObject value, int status = 200) {
        value["instance_id"] = InstanceId;
        context.Response.StatusCode = status;
        context.Response.ContentType = "application/json";
        await context.Response.WriteAsync(value.ToJsonString(), context.RequestAborted);
    }
    private static int StatusCode(string code) => code switch {
        "UNAUTHORIZED" => 401, "FORBIDDEN" => 403,
        "DOCUMENT_NOT_FOUND" or "ENTITY_NOT_FOUND" or "JOB_NOT_FOUND" => 404,
        "REQUEST_ID_CONFLICT" or "REVISION_CONFLICT" or "DOCUMENT_MISMATCH" or "CURSOR_STALE" => 409,
        "CURSOR_EXPIRED" => 410,
        "UNSUPPORTED_OPERATION" => 422, "QUEUE_FULL" => 429, "CAD_BUSY" => 503, _ => 400
    };
    public void Dispose() {
        lock (admission) {
            stopped = true;
            AcApp.Idle -= OnIdle;
            while (queue.TryDequeue(out var job)) job.Finish(Failure(job.Request, "CAD_BUSY", "Bridge stopped before execution", "not_executed"));
        }
        cad.Dispose();
        // Never wait for a network shutdown on AutoCAD's command/event thread.
        _ = host?.StopAsync();
        host = null;
    }
}
