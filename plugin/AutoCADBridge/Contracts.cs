using System.Security.Cryptography;
using System.Text;
using System.Text.Json;
using System.Text.Json.Nodes;

namespace AutoCADBridge;

public sealed class BridgeException(string code, string message) : Exception(message)
{
    public string Code { get; } = code;
}

public sealed record Request(string RequestId, string? DocumentId, long? ExpectedRevision,
    string Operation, JsonObject Args);

public sealed class Job(Request request, string hash)
{
    public Request Request { get; private set; } = request;
    public string Hash { get; } = hash;
    public DateTime Created { get; } = DateTime.UtcNow;
    private DateTime? completed;
    public TaskCompletionSource<JsonObject> Completion { get; } = new(TaskCreationOptions.RunContinuationsAsynchronously);
    private readonly object gate = new();
    private JsonObject value = new() { ["request_id"] = request.RequestId, ["status"] = "queued" };
    public JsonObject Snapshot() { lock (gate) return (JsonObject)value.DeepClone(); }
    public bool IsExpired(DateTime cutoff) { lock (gate) return completed < cutoff; }
    public void Running() { lock (gate) value["status"] = "running"; }
    public void Finish(JsonObject result)
    {
        lock (gate) {
            value = result;
            completed = DateTime.UtcNow;
            // Retain the hash and outcome, not large completed request bodies.
            Request = Request with { Args = new JsonObject() };
        }
        Completion.TrySetResult(Snapshot());
    }
}

public sealed class Journal(int capacity = 2048)
{
    private readonly object gate = new();
    private readonly Dictionary<string, Job> jobs = new(StringComparer.Ordinal);
    public (Job Job, bool Added) Accept(Request request)
    {
        var hash = Convert.ToHexString(SHA256.HashData(Encoding.UTF8.GetBytes(Canonical(new JsonObject {
            ["document_id"] = request.DocumentId, ["expected_revision"] = request.ExpectedRevision,
            ["operation"] = request.Operation, ["args"] = request.Args.DeepClone()
        }))));
        lock (gate)
        {
            foreach (var key in jobs.Where(p => p.Value.IsExpired(DateTime.UtcNow.AddMinutes(-10))).Select(p => p.Key).ToArray()) jobs.Remove(key);
            if (jobs.TryGetValue(request.RequestId, out var old))
            {
                if (old.Hash != hash) throw new BridgeException("REQUEST_ID_CONFLICT", "Request ID already has different content");
                return (old, false);
            }
            if (jobs.Count >= capacity) throw new BridgeException("QUEUE_FULL", "Request journal is full; terminal records expire after ten minutes");
            var job = new Job(request, hash);
            jobs.Add(request.RequestId, job);
            return (job, true);
        }
    }
    public Job Get(string id) { lock (gate) return jobs.TryGetValue(id, out var job) ? job : throw new BridgeException("JOB_NOT_FOUND", "Request is unknown to this Bridge instance"); }
    public static string Canonical(JsonNode? node) => node switch {
        JsonObject obj => "{" + string.Join(",", obj.OrderBy(p => p.Key, StringComparer.Ordinal).Select(p => JsonSerializer.Serialize(p.Key) + ":" + Canonical(p.Value))) + "}",
        JsonArray arr => "[" + string.Join(",", arr.Select(Canonical)) + "]",
        null => "null", _ => node.ToJsonString()
    };
}
