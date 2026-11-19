# MCP runtime tools and paginated queries

The four additions preserve the original 36 MCP schemas. COM remains the default.
All four return structured results. An unsupported backend reports an error and
never switches backends.

| Tool | COM | Experimental HTTP |
| --- | --- | --- |
| `get_backend_status` | Worker lifecycle/queue metadata; does not start or probe CAD | Instance, capabilities, active/bound document IDs and observed revisions |
| `get_job_status` | Unsupported | Read an existing request journal entry without resubmitting it |
| `execute_atomic_batch` | Unsupported | 1–200 layer/line/circle steps in one transaction |
| `query_entities_page` | Unsupported | Model-space queries with type/layer filters and field projection |

## Explicit document identity

Call `new_drawing`, then `get_backend_status` and choose the corresponding managed
document's `document_id`. The new batch and page tools require this ID on every
call. They do not change the shared legacy tools' bound document. The HTTP Bridge
allows writes only to Bridge-created documents, and validates document/revision
again on its CAD main thread. Old tools retain their existing signatures.

Example batch arguments:

```json
{
  "document_id": "<managed document ID from status>",
  "request_id": "fixture-001",
  "expected_revision": 0,
  "operations": [
    {"id":"layer","operation":"create_layer","args":{"name":"Fixture","color":3}},
    {"id":"line","operation":"draw_line","args":{"start":[0,0,0],"end":[10,5,0],"layer":"Fixture"}}
  ]
}
```

Use the revision actually returned by status; `0` above is illustrative. Step IDs
must be unique. Coordinates are finite three-element WCS arrays. A batch failure
rolls back its transaction, including a layer created earlier in that batch.
There are no dynamic references between steps or filesystem operations.

An uncertain write reports its request ID. Query that ID with `get_job_status`;
do not automatically repeat the write. The journal is bounded and expires after
600 seconds. A missing job does not prove that the write never happened. Neither
the journal nor document IDs survive Bridge/process restart.

## Read all query pages

```json
{
  "document_id": "<document ID>",
  "entity_type": "AcDbLine",
  "layer": "Fixture",
  "fields": ["start_point","end_point"],
  "limit": 200,
  "cursor": ""
}
```

Append `items`, then pass `next_cursor` with the same document, filters, fields
and limit while `has_more` is true. Each page contains at most 1,000 items.
`object_id`, `type` and `layer` are always included. Omitted/empty fields select
the supported default fields; unsupported geometry is explicitly listed in
`unsupported_geometry_types` rather than fabricated. The legacy `query_entities`
still reports `RESULT_TOO_LARGE` beyond 1,000 items.

Cursors are HMAC signed with a random per-instance key. They bind the document,
observed revision and canonical query, and expire in 600 seconds. A modified
query/instance/document yields `CURSOR_INVALID`; revision changes yield
`CURSOR_STALE`; expired cursors yield `CURSOR_EXPIRED`. Start from the first page
after any of these errors. Database-event revision is conservative, including
rollback events; it is not a persistent snapshot or proof that every special
object edit is observable.

The current implementation rescans model space to skip preceding matches on
each page. It removes the total-result cap, but is not an indexed query engine or
a demonstrated 50K-entity performance improvement. Layout and region queries are
outside this interface.

## Verification

Run `python -m pytest -q` and
`dotnet run --project plugin/AutoCADBridge.CursorTests -c Release`. Offline tests
exercise actual MCP argument validation/structured results, legacy schema
preservation, HTTP no-replay/document binding and cursor tampering, cross-document,
cross-instance, query, revision and TTL rejection. These checks alone do not
establish native geometry correctness; native evidence must identify its DLL hash.
