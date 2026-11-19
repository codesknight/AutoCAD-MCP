using System.Security.Cryptography;
using System.Text;
using System.Text.Json;

namespace AutoCADBridge;

// Per-Bridge-instance signing key: cursors cannot be moved across instances or documents.
public sealed class QueryCursor
{
    private readonly byte[] key;
    private readonly Func<long> now;
    private readonly int ttlSeconds;
    private sealed record Payload(int Version,string DocumentId,long Revision,int Offset,string Fingerprint,long Expires);
    public QueryCursor(int ttlSeconds=600,Func<long>? now=null,byte[]? key=null) {
        if (ttlSeconds<=0) throw new ArgumentOutOfRangeException(nameof(ttlSeconds));
        this.ttlSeconds=ttlSeconds;
        this.now=now ?? (()=>DateTimeOffset.UtcNow.ToUnixTimeSeconds());
        this.key=key?.ToArray() ?? RandomNumberGenerator.GetBytes(32);
        if (this.key.Length<32) throw new ArgumentException("Cursor key is too short");
    }
    private static string Encode(byte[] bytes)=>Convert.ToBase64String(bytes).TrimEnd('=').Replace('+','-').Replace('/','_');
    private static byte[] Decode(string value) {
        if (value.Any(c=>!(char.IsAsciiLetterOrDigit(c)||c=='-'||c=='_'))) throw new FormatException();
        var padded=value.Replace('-','+').Replace('_','/');
        padded+=new string('=',(4-padded.Length%4)%4);
        return Convert.FromBase64String(padded);
    }
    public string Create(string documentId,long revision,int offset,string fingerprint) {
        if (offset<0) throw new ArgumentOutOfRangeException(nameof(offset));
        var data=JsonSerializer.SerializeToUtf8Bytes(new Payload(1,documentId,revision,offset,fingerprint,now()+ttlSeconds));
        return Encode(data)+"."+Encode(HMACSHA256.HashData(key,data));
    }
    public int Read(string token,string documentId,long revision,string fingerprint) {
        Payload payload;
        try {
            if (token.Length>2048) throw new FormatException();
            var parts=token.Split('.');
            if (parts.Length!=2) throw new FormatException();
            var data=Decode(parts[0]);
            var signature=Decode(parts[1]);
            if (data.Length>1024||signature.Length!=32||!CryptographicOperations.FixedTimeEquals(signature,HMACSHA256.HashData(key,data)))
                throw new FormatException();
            payload=JsonSerializer.Deserialize<Payload>(data,new JsonSerializerOptions { MaxDepth=8 }) ?? throw new FormatException();
            if (payload.Version!=1||payload.DocumentId!=documentId||payload.Fingerprint!=fingerprint||payload.Offset<0)
                throw new FormatException();
        } catch (Exception ex) when (ex is FormatException or JsonException or ArgumentException) {
            throw new BridgeException("CURSOR_INVALID","Cursor does not match this instance, document or query");
        }
        if (payload.Expires<=now()) throw new BridgeException("CURSOR_EXPIRED","Cursor expired; restart the query from the first page");
        if (payload.Revision!=revision) throw new BridgeException("CURSOR_STALE","Drawing revision changed; restart the query from the first page");
        return payload.Offset;
    }
}
