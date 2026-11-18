using System.Text.Json.Nodes;
using AutoCADBridge;

var assertions = 0;
void Check(bool condition) {
    if (!condition) throw new Exception("Contract assertion failed");
    assertions++;
}
var journal = new Journal(2);
var request = new Request("first", "doc", 1, "draw_line",
    JsonNode.Parse("""{"end":[1,0,0],"start":[0,0,0]}""")!.AsObject());
var (first, added) = journal.Accept(request);
Check(added);
Check(first.Snapshot()["status"]!.GetValue<string>() == "queued");
var reordered = request with { Args = JsonNode.Parse("""{"start":[0,0,0],"end":[1,0,0]}""")!.AsObject() };
var (duplicate, duplicateAdded) = journal.Accept(reordered);
Check(!duplicateAdded && ReferenceEquals(first, duplicate));
try {
    journal.Accept(request with { DocumentId = "another-document" });
    throw new Exception("Conflicting request was accepted");
} catch (BridgeException ex) { Check(ex.Code == "REQUEST_ID_CONFLICT"); }
first.Running();
Check(first.Snapshot()["status"]!.GetValue<string>() == "running");
var snapshot = first.Snapshot();
snapshot["status"] = "tampered";
Check(first.Snapshot()["status"]!.GetValue<string>() == "running");
first.Finish(new JsonObject { ["request_id"]="first", ["status"]="succeeded", ["result"]=42 });
Check(first.Completion.Task.IsCompletedSuccessfully);
Check(journal.Get("first").Snapshot()["result"]!.GetValue<int>() == 42);
journal.Accept(request with { RequestId = "second" });
try {
    journal.Accept(request with { RequestId = "third" });
    throw new Exception("Journal exceeded its bound");
} catch (BridgeException ex) { Check(ex.Code == "QUEUE_FULL"); }
Check(journal.Get("second").Snapshot()["status"]!.GetValue<string>() == "queued");
try {
    journal.Get("missing");
    throw new Exception("Unknown job was found");
} catch (BridgeException ex) { Check(ex.Code == "JOB_NOT_FOUND"); }
Console.WriteLine($"{assertions} Bridge contract assertions passed");
