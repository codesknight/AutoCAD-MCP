using System.IO;
using System.Security.Cryptography;

namespace AutoCADBridge;

// File publication is deliberately separate from database transactions. No overwrite,
// arbitrary input-file opening, or path supplied by a later save/reopen request.
public static class ArtifactFiles
{
    public static string DirectoryPath(string value) {
        if (!Path.IsPathFullyQualified(value) || value.StartsWith(@"\\") || value.StartsWith("//"))
            throw new BridgeException("INVALID_ARGUMENT", "Output directory must be an absolute local path");
        var path = Path.TrimEndingDirectorySeparator(Path.GetFullPath(value));
        if (!Directory.Exists(path)) throw new BridgeException("INVALID_ARGUMENT", "Output directory must exist");
        for (var part = new DirectoryInfo(path); part is not null; part = part.Parent)
            if ((part.Attributes & FileAttributes.ReparsePoint) != 0)
                throw new BridgeException("FORBIDDEN", "Output directory cannot traverse a reparse point");
        return path;
    }
    public static string Destination(string directory, string name) {
        directory = DirectoryPath(directory); // Recheck at use, not just at session creation.
        if (string.IsNullOrWhiteSpace(name) || name.Length > 200 || name.IndexOfAny(Path.GetInvalidFileNameChars()) >= 0 ||
            name.Contains('/') || name.Contains('\\') || name.Contains(':') || name.EndsWith(' ') || name.EndsWith('.') ||
            !string.Equals(Path.GetExtension(name), ".dwg", StringComparison.OrdinalIgnoreCase))
            throw new BridgeException("INVALID_ARGUMENT", "Use a plain .dwg filename within the bound output directory");
        var stem = name.Split('.')[0].ToUpperInvariant();
        if (new[] { "CON", "PRN", "AUX", "NUL", "COM1", "COM2", "COM3", "COM4", "COM5", "COM6", "COM7", "COM8", "COM9", "LPT1", "LPT2", "LPT3", "LPT4", "LPT5", "LPT6", "LPT7", "LPT8", "LPT9" }.Contains(stem))
            throw new BridgeException("INVALID_ARGUMENT", "Reserved output filename");
        var path = Path.Combine(directory, name);
        if (File.Exists(path) || Directory.Exists(path)) throw new BridgeException("FILE_EXISTS", "Output already exists; overwriting is not supported");
        return path;
    }
    public static (string Hash, long Bytes) Fingerprint(string path) {
        using var input = new FileStream(path, FileMode.Open, FileAccess.Read, FileShare.Read);
        return (Convert.ToHexString(SHA256.HashData(input)).ToLowerInvariant(), input.Length);
    }
}
