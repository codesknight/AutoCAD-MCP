# Controlled working drawings and saved artifacts

These additive HTTP-only tools preserve the original 36 tool schemas and leave
COM as the default. The MCP server now registers 44 tools. Selecting HTTP is an
explicit MCP-server configuration choice; no Cader code or configuration changes
are needed in this repository. Cader still needs its own controlled-write client.

## Tools and identities

| MCP tool | Required identity | Successful result |
| --- | --- | --- |
| `create_working_drawing` | `instance_id`, preallocated `request_id` | Job envelope plus document ID, revision, units, Bridge permissions and bound output directory |
| `get_working_drawing` | `instance_id`, `document_id` | Current document identity/revision/units, model-space count and bounded layer/style names |
| `save_working_drawing` | `instance_id`, `document_id`, `expected_revision`, `request_id` | Recorded artifact ID, path, SHA-256, bytes, save time and source revision |
| `reopen_saved_drawing` | `instance_id`, `artifact_id`, `request_id` | A read-only document with its own identity and a reference to the recorded artifact |

All results are structured. The envelope owns `instance_id`, `request_id`,
`document_id`, `revision`, `status` and errors; `result` contains the typed document
or artifact metadata. Document metadata repeats document identity/revision and is
validated against the envelope. A reopened document has `managed=false` and
`read_only=true`. Here `read_only` describes Bridge access; it is not a claim about
the editor's permissions on an arbitrary preexisting user drawing.

`get_working_drawing` includes `model_space_count`, `layer_names`,
`text_style_names` and `catalogs_truncated`. Each name catalog is capped at 1,000;
it is not a complete catalog when that flag is true. Normal backend status remains
lightweight and does not enumerate entity geometry.

## Workflow

1. Select the HTTP backend explicitly and read `get_backend_status`. Verify
   `controlled_documents`, operation support, instance and revision semantics.
2. Allocate and persist a request ID before calling `create_working_drawing`.
   Choose `unitless`, `millimeters`, `centimeters`, `meters`, `inches` or `feet`.
   These set INSUNITS; they do not infer a reference image's physical scale or
   rescale existing geometry. The default is millimeters.
3. Retain the returned document identity. The operation does **not** change the
   legacy tools' shared bound document. Inspect it with `get_working_drawing`.
4. Submit `execute_atomic_batch` with `instance_id`, `document_id`, a preallocated
   nonempty `request_id` and the observed `expected_revision`. In this controlled
   mode all three guards are required. Omitting `instance_id` preserves the earlier
   batch call signature, but new clients should always use controlled mode.
5. Read every `query_entities_page` page against that explicit document. Check
   geometry, text and layer properties independently of the command response.
6. Read the current revision and save a new filename with `save_working_drawing`.
   Saving is a full DWG copy-save: the editor document keeps its existing name.
7. Reopen the returned artifact ID and query **the new read-only document ID**.
   Compare normalized geometry/text/properties. Aliases cannot identify entities
   across documents; a successful reopen alone is not content acceptance.

Example creation (IDs and directory are illustrative):

```json
{
  "instance_id": "<from get_backend_status>",
  "request_id": "work-001",
  "units": "millimeters",
  "output_directory": "D:/cad-test-output"
}
```

The directory must already exist, be an absolute local path and not traverse a
reparse point. An empty directory argument creates an isolated directory below
the current user's LocalAppData/AutoCAD-MCP/outputs. Later save calls accept only a
plain `.dwg` filename. No overwrite option is provided: existing files/directories,
path traversal, alternate streams, UNC/device paths and reparse directories are
rejected. This is an application-level output boundary, not an OS security sandbox
against other processes running as the same user.

## Entity transactions and files are separate

`batch_operations` advertises nine operations: `create_layer`, `draw_line`,
`draw_circle`, `draw_arc`, `draw_rectangle`, `draw_polyline`, `draw_text`,
`draw_mtext`, `add_dimension`. A batch has 1–200 unique step IDs. It uses one
database transaction, including layer/style creation. File operations never enter
that transaction. The capabilities distinguish `operations`, `batch_operations`,
`file_operations`, `file_overwrite=false` and
`file_operations_atomic_with_entities=false`.

Circle/arc radii are positive; arc/text angles are degrees. Arc angles run CCW
from WCS +X in the XY plane. Coincident arc endpoints/full-circle sweeps are
rejected; use a circle. Rectangle/polyline preserve the legacy OCS XY behavior:
input Z is ignored and database elevation is used. This is advertised as
`polyline_coordinates=legacy_ocs_xy_input_z_ignored`; it is not arbitrary 3D polyline
support. Aligned dimensions currently require a common WCS Z plane.

Save writes a unique temporary DWG in the bound directory with AutoCAD SaveAs
using `bBakAndRename=false`, computes its hash, then publishes with a no-replace
move. No `.bak` or editor rename is requested. Failures after file I/O begins are
reported as `outcome_unknown`, never as a database rollback. Temporary-file cleanup
is best effort; a crash can leave a temporary file or a published file without a
registered artifact. Do not infer success from file existence or rerun an unknown
save to resolve it. See Autodesk's [SaveAs contract](https://help.autodesk.com/cloudhelp/2026/ENU/OARX-ManagedRefGuide/files/OARX-ManagedRefGuide-Autodesk_AutoCAD_DatabaseServices_Database_SaveAs_string__MarshalAsUnmanagedType_U1__bool_DwgVersion_Autodesk_AutoCAD_DatabaseServices_SecurityParameters.html).

Reopen accepts only an artifact saved by this instance, checks hash/size and opens
it with AutoCAD's [read-only document API](https://help.autodesk.com/cloudhelp/2024/ENU/OARX-ManagedRefGuide/files/OARX-ManagedRefGuide-Autodesk_AutoCAD_ApplicationServices_DocumentCollectionExtension_Open_this_DocumentCollection_string__MarshalAsUnmanagedType_U1__bool.html).
It keeps the source work document open. A later source edit does not become an edit
of the saved artifact. A changed/missing file is rejected. Artifact records are
in-memory, limited to 2,048 per instance and not recoverable after restart. Saved
files remain on disk; reopening arbitrary existing files is deliberately outside
this interface.

## Reconciliation and verification fields

The HTTP adapter sends its pinned instance on every POST. The server checks it
before admission; new lifecycle operations require it. Old-instance writes do not
reach the CAD dispatcher. `get_job_status` remains the reconciliation interface:
unknown result, lost response or timeout never triggers automatic POST replay.
The request journal retains at most 2,048 entries for ten minutes after completion;
`JOB_NOT_FOUND` and instance changes cannot prove absence of a side effect. Clients
must stop dependent writes until the outcome is resolved.

Pagination adds arc center/radius/angles/endpoints/length/normal, polyline
normal/elevation/bulges, text/dimension normals and dimension text overrides.
Entity properties include linetype, scale, lineweight, ACI color and layer properties
(including the referenced layer's linetype/color/weight and visibility/lock flags).
Angles are degrees; lineweight values use AutoCAD's numeric enum, including ByLayer
and ByBlock sentinels. Existing geometry/text fields remain available.

`geometry_complete` means the entity is one of the supported summary types, not
that every CAD appearance/style/proxy/block property has been reproduced. Unsupported
types and fitted heavy polylines are flagged, and page-level
`unsupported_geometry_types` remains explicit. Block topology, raster comparison,
appearance equivalence and general DWG validation are not claimed.

Real qualification and reproduction instructions: [validation report](../validation/2026-11-19-controlled-documents.md).
