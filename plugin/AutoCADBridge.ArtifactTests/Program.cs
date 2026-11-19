using AutoCADBridge;

var directory = Path.Combine(Path.GetTempPath(), "mcp-artifact-tests-" + Guid.NewGuid().ToString("N"));
Directory.CreateDirectory(directory);
var assertions = 0;
void Reject(Action action, string code) {
    try { action(); throw new Exception("Expected " + code); }
    catch (BridgeException ex) when (ex.Code == code) { assertions++; }
}
try {
    var path = ArtifactFiles.Destination(directory, "drawing.dwg");
    if (Path.GetDirectoryName(path) != directory || File.Exists(path)) throw new Exception("Unexpected publication");
    assertions++;
    foreach (var name in new[] { "../x.dwg", @"..\x.dwg", "x:stream.dwg", "x.txt", "NUL.dwg", "COM1.dwg", "x.dwg ", "x.dwg.", "" })
        Reject(() => ArtifactFiles.Destination(directory, name), "INVALID_ARGUMENT");
    Reject(() => ArtifactFiles.DirectoryPath("relative"), "INVALID_ARGUMENT");
    Reject(() => ArtifactFiles.DirectoryPath(@"\\server\share"), "INVALID_ARGUMENT");
    Reject(() => ArtifactFiles.DirectoryPath(Path.Combine(directory, "missing")), "INVALID_ARGUMENT");
    File.WriteAllText(path, "original");
    Reject(() => ArtifactFiles.Destination(directory, "drawing.dwg"), "FILE_EXISTS");
    var before = ArtifactFiles.Fingerprint(path);
    var temporary = Path.Combine(directory, "temporary.dwg"); File.WriteAllText(temporary, "replacement");
    try { File.Move(temporary, path, false); throw new Exception("Overwrite unexpectedly succeeded"); }
    catch (IOException) { assertions++; }
    if (ArtifactFiles.Fingerprint(path) != before || File.ReadAllText(path) != "original") throw new Exception("Original changed");
    assertions++;
    File.AppendAllText(path, "-tampered");
    if (ArtifactFiles.Fingerprint(path) == before) throw new Exception("Fingerprint missed modification");
    assertions++;
    Console.WriteLine($"{assertions} artifact path/publication assertions passed");
} finally {
    // Only files this fixture created, no recursive cleanup of computed paths.
    foreach (var name in new[] { "drawing.dwg", "temporary.dwg" }) File.Delete(Path.Combine(directory, name));
    Directory.Delete(directory);
}
