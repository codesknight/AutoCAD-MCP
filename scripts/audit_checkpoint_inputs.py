"""Read-only checkpoint preflight; never connects to CAD or grants write authority."""

import argparse
import hashlib
import json
from collections import Counter
from pathlib import Path

from autocad_mcp.cad.checkpoint import validate_snapshot
from autocad_mcp.cad.com_artifacts import fingerprint


def file_hash(path):
    result = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1048576), b""):
            result.update(block)
    return result.hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dwg", type=Path, required=True)
    parser.add_argument("--snapshot", type=Path, required=True)
    parser.add_argument("--ledger", type=Path, required=True)
    args = parser.parse_args()
    frozen = json.loads(args.snapshot.read_text(encoding="utf-8-sig"))
    rows = frozen.get("entities", [])
    result = dict(
        scope="input_audit_only",
        source=fingerprint(args.dwg),
        frozen_file_sha256=file_hash(args.snapshot),
        ledger_sha256=file_hash(args.ledger),
        entity_count=len(rows),
        types=dict(Counter(row.get("type") for row in rows)),
        missing_handles=sum("handle" not in row for row in rows),
        original_ledger_reconciled=False,
        recovery_authorized=False,
    )
    try:
        validate_snapshot(frozen)
        result["snapshot_contract_valid"] = True
    except (ValueError, KeyError, TypeError) as error:
        result.update(snapshot_contract_valid=False, rejection=str(error))
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
