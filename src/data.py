"""Load MBPP from the local Hugging Face cache.

MBPP gives each problem a natural-language description, one reference solution, and
exactly three `assert` statements. Three asserts is a thin specification, and whether
they are thin enough to pass wrong code is the question this repository answers.

No network: the dataset is 809 KB and already cached. A benchmark study that cannot run
offline is a benchmark study that silently depends on someone else's uptime.
"""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from pathlib import Path

CACHE_DIR_NAME = "datasets--Muennighoff--mbpp"

# The name being tested, taken from the first assert: `assert foo(1) == 2` -> `foo`.
_CALLED = re.compile(r"assert\s+(?:not\s+)?([A-Za-z_]\w*)\s*\(")


@dataclass(frozen=True)
class Problem:
    task_id: int
    text: str
    code: str
    test_list: tuple[str, ...]
    test_setup_code: str
    challenge_test_list: tuple[str, ...]

    @property
    def entry_point(self) -> str | None:
        """The function the asserts call, or None if they call nothing recognisable."""
        for t in self.test_list:
            m = _CALLED.search(t)
            if m:
                return m.group(1)
        return None


def _cache_roots() -> list[Path]:
    roots = []
    if env := os.environ.get("HF_HUB_CACHE"):
        roots.append(Path(env))
    if env := os.environ.get("HF_HOME"):
        roots.append(Path(env) / "hub")
    roots.append(Path.home() / ".cache" / "huggingface" / "hub")
    return roots


SPLITS = {"full": "mbpp.jsonl", "sanitized": "sanitized-mbpp.json"}


def find_file(split: str = "full") -> Path | None:
    name = SPLITS[split]
    for root in _cache_roots():
        hits = sorted((root / CACHE_DIR_NAME).glob(f"snapshots/*/data/{name}"))
        if hits:
            return hits[0]
    return None


# Kept for the original call sites; `find_file` is the general form.
def find_jsonl() -> Path | None:
    return find_file("full")


def load(limit: int | None = None, split: str = "full") -> list[Problem]:
    """Problems from one MBPP split.

    `full` is all 974 as released. `sanitized` is the 427 the authors hand-verified,
    and it is the fairer target for any claim about MBPP's quality: its asserts are
    revised, not merely re-copied. Comparing the two is the point - if the verified
    subset accepts wrong code at the same rate, hand-verification did not fix what
    three asserts cannot express.
    """
    if split not in SPLITS:
        raise ValueError(f"unknown split {split!r}; expected one of {sorted(SPLITS)}")
    path = find_file(split)
    if path is None:
        raise FileNotFoundError(
            f"MBPP ({split}) is not in the local Hugging Face cache.\n"
            "Fix either one:\n"
            "  pip install datasets   # then: load_dataset('Muennighoff/mbpp')\n"
            "  or set HF_HOME / HF_HUB_CACHE to the cache that already holds it.\n"
            f"Looked in: {', '.join(str(r) for r in _cache_roots())}"
        )

    raw = path.read_text(encoding="utf-8")
    if split == "sanitized":
        records = json.loads(raw)
    else:
        records = [json.loads(ln) for ln in raw.splitlines() if ln.strip()]

    out = []
    for r in records:
        out.append(
            Problem(
                task_id=int(r["task_id"]),
                # The sanitized split renamed `text` to `prompt`, and carries its setup
                # as a list of import lines under `test_imports` rather than a string.
                text=r.get("text") or r.get("prompt") or "",
                code=r["code"],
                test_list=tuple(r["test_list"]),
                test_setup_code=(
                    r.get("test_setup_code") or "\n".join(r.get("test_imports") or ())
                ),
                challenge_test_list=tuple(r.get("challenge_test_list") or ()),
            )
        )
        if limit and len(out) >= limit:
            break
    return out


if __name__ == "__main__":
    probs = load()
    print(f"problems            : {len(probs)}")
    counts = [len(p.test_list) for p in probs]
    print(f"asserts per problem : min {min(counts)}, max {max(counts)}")
    print(f"with setup code     : {sum(1 for p in probs if p.test_setup_code)}")
    print(f"with challenge tests: {sum(1 for p in probs if p.challenge_test_list)}")
    print(f"entry point found   : {sum(1 for p in probs if p.entry_point)}/{len(probs)}")
    print("\nsample:")
    for p in probs[:3]:
        print(f"  {p.task_id:4}  {p.entry_point:24}  {p.text[:58]}")
