# CAD-09 native qualification

This is an opt-in, local Windows harness. It never changes the default COM backend and never launches AutoCAD through COM Dispatch. Ordinary CI only tests the data validator/reporting code.

## Before running

1. Install the project in the development environment: `python -m pip install -e ".[dev]"`.
2. Build/install the Bridge using [the Bridge guide](../docs/design/http-bridge.md).
   For native fault injection, also build the independent fixture:

   ~~~powershell
   dotnet build plugin/AutoCADBridge.NativeTests -c Release -p:AutoCADDir="<installed-AutoCAD-directory>"
   ~~~

   It is explicitly NETLOADed for fault tests only; handle its unsigned DLL confirmation manually.
3. Normally launch one dedicated AutoCAD instance. Keep it idle and stop other MCP writers during qualification.
4. Run from the repository root. Any unsigned DLL confirmation must be handled manually in AutoCAD.

By default the harness requires an instance with no drawings. `--preserve-existing` permits existing drawings: it creates scratch drawings, retains originals and restores the original active drawing. It does not save or close original drawings. `--owned-pid PID` permits quitting only that exact, explicitly owned process, and only when there were no original drawings.

~~~powershell
python -m benchmarks.run --mode all --preserve-existing --output benchmarks/results/<new-run>
~~~

Separate phases, with distinct output directories:

~~~powershell
python -m benchmarks.run --mode faults --preserve-existing --output benchmarks/results/<fault-run>
python -m benchmarks.run --mode benchmark --preserve-existing --output benchmarks/results/<benchmark-run> --sizes 100 500 1000 --warmups 3 --samples 20 --heavy-samples 5 --heavy-threshold 5 --seed 190019
python -m benchmarks.run --mode soak --preserve-existing --output benchmarks/results/<soak-run> --soak-seconds 1800 --interval 1
~~~

Use a new directory each time. Raw `cases.jsonl` records are append-only; failed attempts are retained. The workload checks `STOP` in its output directory to request a graceful stop between operations:

~~~powershell
New-Item -ItemType File benchmarks/results/<run>/STOP
~~~

## Scope and predeclared method

- **Native faults:** authentication/Origin/Host, invalid geometry, rollback at first/middle/last step, deduplication/conflicting IDs, switching/closing documents, stale aliases, external COM revision changes, response loss, polling disconnect, wait-budget expiry, queue saturation/draining, pending-write shutdown, journal capacity, plugin restart and port conflict.

Busy injection uses AutoCADBridge.NativeTests, an explicitly loaded local fixture which holds the CAD main thread for a fixed five seconds and signals entry through a named kernel event. It automatically returns to Idle; a separate variant stops Bridge before returning. This avoids both synchronous interactive-command blocking and COM calls rejected while LINE waits for user input. The fixture exposes no HTTP endpoint and has no startup hook. Stop detection uses the OS TCP listener table; a short loopback connection timeout alone does not prove that a listener is still running on Windows.

The discarded interactive approach is documented by Autodesk's [PostCommand](https://help.autodesk.com/cloudhelp/2026/ENU/AutoCAD-ActiveX-Reference/files/GUID-9D3B8666-1B40-47C0-911B-859E3C38FB1A.htm) and [GetAcadState](https://help.autodesk.com/cloudhelp/2026/ENU/AutoCAD-ActiveX-Reference/files/GUID-820F93B4-7B83-4708-8E21-0D43D7D1C828.htm) references; its failed attempts remain in the raw evidence.

- **Soak:** at least 30 minutes and 1,000 successful mixed calls. One call per second, cycling line creation, layer listing, geometry query, entity lookup and circle creation. A fresh scratch drawing every 500 calls bounds model size. CAD private memory is sampled every minute; a 512 MiB increase from the initial baseline stops the run for investigation. This is a stop budget, not a proof of leak freedom.
- **Creation:** 100 / 500 / 1,000 deterministic lines; compare COM sequential, HTTP sequential and HTTP batches of at most 200 operations.
- **Query:** the same fixture and common geometry fields at each supported size. Identity-dependent ObjectID/Handle values are excluded from comparison; count, coordinates, layer and bounds must match at absolute tolerance `1e-8`.
- **Cold attachment:** first adapter call with CAD already running. This is distinct from CAD process startup.
- **Samples:** three warmups, then twenty measurements. If the maximum paired warmup exceeds five seconds, all modes in that group use five measured repeats. The reason and warmups are retained. P95 is reported only with at least twenty successful measured samples; smaller groups expose median/max and sample count.
- **Order:** deterministic random mode order, seed 190019. Both backends use fresh Bridge-created `acadiso.dwt` drawings, `INSUNITS=4`, and an identical fixture layer. No saves or explicit viewport regeneration inside the timed section.
- **Isolation:** a fresh Bridge instance per benchmark sample, outside timing, avoids the 2,048-record / 600-second journal capacity confound. Sustained journal pressure is tested separately.
- **Boundary:** elapsed time surrounds Python `execute` / `execute_batch` calls. It includes STA/HTTP dispatch, serialization, Bridge execution and the existing 50 ms polling interval. Fixture provisioning, connection priming for hot samples, validation and cleanup are outside timing. HTTP request counts/response bytes and job queue/execution metrics are recorded separately. COM IPC byte counts are unavailable; common normalized JSON sizes are not presented as COM wire sizes.
- **Atomicity:** batch and sequential creation compare successful geometry only. COM sequential writes have no equivalent atomic rollback guarantee.
- **Resource context:** working set and private bytes refer to the whole AutoCAD process, including its caches and other in-process components.

The original running CAD process is preserved unless explicitly identified as owned. CAD process restart is recorded as not run when doing so would close a user-owned instance. Long-lived/persistent crash recovery is not implemented.

An additional process-restart check can preserve the original instance by using two NEW, dedicated instances and only HTTP (avoiding ambiguous COM attachment when multiple CAD processes exist):

~~~powershell
python -m benchmarks.restart --output benchmarks/results/<restart-run>
~~~

Follow its prompts: normally launch a new instance, NETLOAD the installed DLL and run MCPBRIDGE_START, enter its PID, start LINE in its scratch drawing, and leave it awaiting a point. After the driver verifies a queued write, terminate only that owned PID. Normally launch the replacement, load/start Bridge, and enter the new PID. The driver checks the unknown outcome, no replay, old-client rejection and explicit recovery. Finally close only the replacement test process as prompted. No original PID may be terminated. The temporary Bridge settings are restored; do not run this phase concurrently with another harness phase.

This iteration does not benchmark unavailable HTTP block/edit tools, 10K/50K legacy queries (current limit: 1,000), LLM latency, or change the default backend.

## Evidence

Each run stores `plan.json`, `environment.json`, `cases.jsonl`, `cleanup.json` and `qualification.json`. Phase-specific summaries are `faults.json`, `soak.json`, `benchmark.json` and `summary.csv`. Missing, failed and not-run cases must stay visible.

No private DWG is needed or uploaded. Scratch geometry is generated locally, never saved, and re-read for verification. Tokens stay in the process environment and the temporary per-user Bridge settings file, which is restored during cleanup.

The result field `completed` means the phase and cleanup finished; inspect `passed` and individual failures/not-run entries before drawing an acceptance conclusion.

Render the audit report from all recorded attempts:

~~~powershell
python -m benchmarks.report --root benchmarks/results/<date> --output docs/validation/<date>-cad09.md
~~~

Optional chart authoring requires matplotlib (not a runtime dependency):

~~~powershell
python -m benchmarks.plot --summary benchmarks/results/<date>/<benchmark-run>/summary.csv --output docs/validation/<date>-cad09-performance.svg
~~~

Recorded report: [2026-11-19 qualification and performance](../docs/validation/2026-11-19-cad09.md).
It includes failed COM samples and earlier harness attempts; completion must not
be confused with all acceptance criteria passing.
