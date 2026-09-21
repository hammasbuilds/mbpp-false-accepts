"""Convert the cached HumanEval parquet to JSONL, once, so the repo keeps zero dependencies.

HumanEval ships as a single parquet file, and reading parquet needs pyarrow. Adding a
runtime dependency to read 84 KB would cost this repo the property that it runs in a bare
checkout with nothing installed, which is worth more than avoiding a 220 KB committed file.
So the conversion happens here, once, and `data/humaneval.jsonl` is committed with its
provenance in the first record. HumanEval is MIT licensed.

Run it with any interpreter that has pyarrow; it is not part of the measurement.

    python scripts/convert_humaneval.py
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CACHE_DIR_NAME = "datasets--openai--openai_humaneval"
FIELDS = ("task_id", "prompt", "canonical_solution", "test", "entry_point")


def _cache_roots() -> list[Path]:
    roots = []
    if env := os.environ.get("HF_HUB_CACHE"):
        roots.append(Path(env))
    if env := os.environ.get("HF_HOME"):
        roots.append(Path(env) / "hub")
    roots.append(Path.home() / ".cache" / "huggingface" / "hub")
    return roots


def find_parquet() -> Path | None:
    for root in _cache_roots():
        hits = sorted((root / CACHE_DIR_NAME).glob("snapshots/*/**/*.parquet"))
        if hits:
            return hits[0]
    return None


def main() -> int:
    try:
        import pyarrow.parquet as pq
    except ImportError:
        print("needs pyarrow (this script only; the repo itself has no dependencies)")
        return 2

    src = find_parquet()
    if src is None:
        print(f"HumanEval is not in the cache. Looked in: {_cache_roots()}")
        return 2

    table = pq.read_table(src)
    missing = [f for f in FIELDS if f not in table.column_names]
    if missing:
        print(f"unexpected schema, missing {missing}; got {table.column_names}")
        return 2

    rows = table.select(FIELDS).to_pylist()
    dest = ROOT / "data" / "humaneval.jsonl"
    dest.parent.mkdir(parents=True, exist_ok=True)
    with dest.open("w", encoding="utf-8", newline="\n") as fh:
        fh.write(
            json.dumps(
                {
                    "_provenance": "openai/openai_humaneval, MIT licensed",
                    "_source": str(src.name),
                    "_rows": len(rows),
                }
            )
            + "\n"
        )
        for r in rows:
            fh.write(json.dumps(r) + "\n")

    print(f"wrote {dest} ({dest.stat().st_size:,} bytes, {len(rows)} problems)")
    print(f"  e.g. {rows[0]['task_id']}  entry_point={rows[0]['entry_point']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
