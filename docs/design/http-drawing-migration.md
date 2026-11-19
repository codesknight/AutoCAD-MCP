# HTTP drawing migration: first group

The next five legacy MCP tools use native .NET geometry when HTTP is selected:
`draw_rectangle`, `draw_polyline`, `draw_text`, `draw_mtext`, and `add_dimension`.
Their original MCP schemas and string results remain unchanged. COM stays the
default, and the atomic batch allowlist stays limited to layer/line/circle.

Every write still requires a Bridge-created document and runs under its document
lock and transaction. Errors and unknown outcomes never trigger COM fallback or
automatic write replay. Editing, blocks/attributes and filesystem tools remain
separate migration work.

## Geometry and text compatibility

- Rectangle/polyline use heavyweight `AcDb2dPolyline`, matching legacy COM
  `AddPolyline`. Input points contain three numbers, but only OCS XY is used;
  the target database's model-space elevation supplies Z. Rectangle uses four
  ordered corner vertices and closes the polyline. This intentionally preserves
  the existing COM behavior, including its ignored input Z, rather than silently
  changing entity type or promising arbitrary 3D polylines.
- Single-line text uses DBText, degree-to-radian rotation and the existing
  `MCP_CJK` SimSun style convention. MText uses top-left attachment, width and
  text height. Reuse an existing style without modifying other users of it.
- Aligned dimensions use the target database's current dimension style. This
  initial HTTP implementation requires the three definition points to share a
  WCS Z plane and rejects identical endpoints. It does not claim full 3D parity.
- Native query summaries expose polyline points/closed state, text insertion,
  content/style/height/rotation, MText width, and dimension definition points and
  measurement. The page tool supports projecting these additional fields.

The compatibility decisions follow Autodesk's [AddPolyline](https://help.autodesk.com/cloudhelp/2026/ENU/AutoCAD-ActiveX-Reference/files/GUID-ED02917C-D1D6-46B8-95C6-736163C31362.htm),
[Polyline2d constructor](https://help.autodesk.com/cloudhelp/2026/ENU/OARX-ManagedRefGuide/files/OARX-ManagedRefGuide-Autodesk_AutoCAD_DatabaseServices_Polyline2d_Polyline2d.html),
and [AlignedDimension constructor](https://help.autodesk.com/cloudhelp/2026/ENU/OARX-ManagedRefGuide/files/OARX-ManagedRefGuide-Autodesk_AutoCAD_DatabaseServices_AlignedDimension_AlignedDimension.html) references.

## Native failure and correction

The first real test successfully read 1,205 lines in pages of 400/400/400/5,
then failed during rectangle creation. AutoCAD displayed
`db2dpoly.cpp@352: eInvalidInput` and exited; the client reported
`OUTCOME_UNKNOWN` without replaying. The failed DLL hash and partial evidence are
retained under `docs/validation/runtime-2026-11-19-01`. Only the dedicated scratch
instance exited; the pre-existing CAD instance remained.

The previous bulk Polyline2d construction path was removed. Creation now uses a
default parent, adds it to the database, appends each Vertex2d, registers each
vertex with the same transaction and closes wrappers explicitly, then sets the
closed flag. This follows the documented [database-resident AppendVertex
requirement](https://help.autodesk.com/cloudhelp/2026/ENU/OARX-ManagedRefGuide/files/OARX-ManagedRefGuide-Autodesk_AutoCAD_DatabaseServices_Polyline2d_AppendVertex_Vertex2d.html).
The exact internal native cause has not been proven from a dump. The corrected
DLL subsequently passed all five native creation/re-read checks, including
polyline vertices/closed state and CJK text/style/rotation. The second run exposed
an overly strict test expectation for the dimension definition point; AutoCAD
returned a different point on the same expected dimension line. The final run
uses measurement, endpoints and line placement checks. See the [complete evidence
report](../validation/2026-11-19-mcp-runtime.md), including the separate cleanup
verification and unchanged failure flags.

## Reproduce

Use a dedicated normally launched instance and an isolated Bridge build/settings
directory. Load the DLL manually, start `MCPBRIDGE_START`, then run:

```powershell
python -m scripts.verify_runtime_tools --bridge-dir <isolated-directory> --owned-pid <test-pid> --output docs/validation/<new-run> --control-dir <private-new-control-dir>
```

The script checks actual stdio MCP calls, explicit document identity, atomic
rollback/deduplication, pagination/projection/filtering/cursor rejection and all
five drawing results by re-reading geometry. It never starts CAD or saves a DWG.
At its final checkpoint, close only that dedicated scratch process and create
`cleanup.json` containing `{}` in the private control directory. A passed result
requires both functional checks and process cleanup, with original processes
preserved. Keep failed runs and their original qualification flags.
