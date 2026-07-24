from __future__ import annotations

import json
import tempfile
from pathlib import Path

from codex_istm.model_workflow import (
    _structured_sweep_plan,
    _validate_structured_context_response,
)
from memory_forest import (
    apply_daily,
    apply_structured_sweep,
    index_forest,
    initialize_forest,
    load_forest_identity,
    structured_context_index,
)
from memory_forest.errors import MemoryForestError


def main() -> int:
    real_temporary_root = Path(tempfile.gettempdir()).resolve()
    with tempfile.TemporaryDirectory(dir=real_temporary_root) as raw:
        root = Path(raw) / "forest"
        initialize_forest(root, example=True)
        index_forest(root)
        forest_id = load_forest_identity(root)
        query = "instrument calibration"
        context_response = structured_context_index(root, query, limit=3)
        documents, forest_snapshot_sha256 = (
            _validate_structured_context_response(
                context_response,
                query=query,
                forest_id=forest_id,
            )
        )
        if not documents:
            raise RuntimeError("The interop fixture returned no Structured documents")

        daily_result_sha256 = "c" * 64
        apply_daily(
            root,
            {
                "schema_version": "memory-forest-daily-plan-v1",
                "forest_id": forest_id,
                "transaction_id": "a" * 64,
                "date": "2042-04-13",
                "entries": [
                    {
                        "entry_id": "entry-1",
                        "source_record_ids": ["record-1"],
                        "summary": "A wholly fictional source summary.",
                    }
                ],
                "provenance": {
                    "packet_sha256": "b" * 64,
                    "result_sha256": daily_result_sha256,
                    "batch_id": "a" * 64,
                },
            },
        )
        packet = {
            "date": "2042-04-13",
            "packet_sha256": "d" * 64,
            "items": [
                {
                    "daily_entry_id": "entry-1",
                    "daily_result_sha256": daily_result_sha256,
                }
            ],
            "forest_context": {
                "forest_snapshot_sha256": forest_snapshot_sha256,
            },
        }
        result = {
            "changes": [],
            "dispositions": [
                {
                    "daily_entry_id": "entry-1",
                    "status": "source_only",
                    "targets": [],
                    "reason": "The synthetic source remains source evidence only.",
                }
            ],
        }
        plan = _structured_sweep_plan(
            packet,
            result,
            "e" * 64,
            forest_id,
        )
        if (
            plan["provenance"]["forest_snapshot_sha256"]
            != forest_snapshot_sha256
        ):
            raise RuntimeError("The companion changed the whole-Forest snapshot binding")
        first = apply_structured_sweep(root, plan)
        second = apply_structured_sweep(root, plan)
        if first["already_applied"] or not second["already_applied"]:
            raise RuntimeError("Structured receipt idempotency failed")

        xltm = root / "01 xltm" / "XLTM.md"
        xltm.write_text(
            xltm.read_text(encoding="utf-8") + "\nSynthetic later change.\n",
            encoding="utf-8",
        )
        stale_plan = _structured_sweep_plan(
            packet,
            result,
            "f" * 64,
            forest_id,
        )
        try:
            apply_structured_sweep(root, stale_plan)
        except MemoryForestError as error:
            if error.code != "structured_snapshot_mismatch":
                raise
        else:
            raise RuntimeError("A stale whole-Forest snapshot was accepted")

    print(
        json.dumps(
            {
                "documents": len(documents),
                "ok": True,
                "operation": "memory-forest-interop-smoke",
            },
            separators=(",", ":"),
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
