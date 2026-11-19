using AutoCADBridge;
using System.Text;
var assertions=0;
void Check(bool valid) { if(!valid)throw new Exception("Cursor assertion failed"); assertions++; }
void Reject(Action run,string code) {
    try {run();throw new Exception("Invalid cursor accepted");}
    catch(BridgeException ex){Check(ex.Code==code);}
}
long clock=100;
var key=Enumerable.Range(0,32).Select(i=>(byte)i).ToArray();
var signer=new QueryCursor(60,()=>clock,key);
var token=signer.Create("doc-a",7,200,"query-a");
Check(signer.Read(token,"doc-a",7,"query-a")==200);
Check(signer.Read(token,"doc-a",7,"query-a")==200); // Replay is read-only and deterministic.
Reject(()=>signer.Read(token,"doc-b",7,"query-a"),"CURSOR_INVALID");
Reject(()=>signer.Read(token,"doc-a",7,"query-b"),"CURSOR_INVALID");
Reject(()=>signer.Read(token,"doc-a",8,"query-a"),"CURSOR_STALE");
Reject(()=>signer.Read(token.Substring(0,5)+"!"+token.Substring(6),"doc-a",7,"query-a"),"CURSOR_INVALID");
Reject(()=>signer.Read(token+"x","doc-a",7,"query-a"),"CURSOR_INVALID");
Reject(()=>signer.Read(new string('a',2049),"doc-a",7,"query-a"),"CURSOR_INVALID");
Reject(()=>new QueryCursor(60,()=>clock,Enumerable.Repeat((byte)9,32).ToArray()).Read(token,"doc-a",7,"query-a"),"CURSOR_INVALID");
clock=159;
Check(signer.Read(token,"doc-a",7,"query-a")==200);
clock=160;
Reject(()=>signer.Read(token,"doc-a",7,"query-a"),"CURSOR_EXPIRED");
Console.WriteLine($"{assertions} cursor integrity, document/query/revision and TTL assertions passed");
