"""Arm 1: how much wrong code does MBPP's three-assert suite accept?

For each problem, take the reference solution MBPP calls correct, change exactly one
thing, and run the same three asserts. A mutant that still passes is a program MBPP
cannot distinguish from the right answer.

The headline is the survival rate. It is an upper bound on the suite's weakness rather
than a count of holes, because some mutations are genuinely equivalent to the original
(`a < b` vs `b > a`) and equivalent-mutant detection is undecidable in general. Survivors
are sampled and printed so the reader can judge the proportion that are real.

    python run_mutation.py              # all 974
    python run_mutation.py --limit 50   # quick
"""

from __future__ import annotations

import argparse
import json
import sys
import time
import warnings
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "src"))

# MBPP solutions contain unescaped regex strings; the warning is about their source,
# not ours, and it fires once per parse of nearly a thousand problems.
warnings.filterwarnings("ignore", category=SyntaxWarning)

from data import load  # noqa: E402
from differential import find_many  # noqa: E402
from mutate import mutants  # noqa: E402
from sandbox import run_many  # noqa: E402

OUT = Path(__file__).resolve().parent / "results"
MUTANTS_PER_PROBLEM = 12


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int)
    ap.add_argument(
        "--split",
        choices=["full", "sanitized", "humaneval"],
        default="full",
        help="sanitized is the 427 the authors hand-verified; "
        "humaneval is a second benchmark with ~7 asserts per problem instead of 3",
    )
    ap.add_argument("--workers", type=int, default=8)
    ap.add_argument("--per-problem", type=int, default=MUTANTS_PER_PROBLEM)
    ap.add_argument(
        "--no-witness",
        action="store_true",
        help="skip the search for separating inputs (faster, weaker claim)",
    )
    args = ap.parse_args()

    probs = load(limit=args.limit, split=args.split)
    print(f"problems: {len(probs)}  split: {args.split}")

    # Validate the reference solutions first. A reference that fails its own asserts
    # would make every mutant of it meaningless, and MBPP is known to contain a few.
    t = time.time()
    ref = run_many([(p.code, list(p.test_list), p.test_setup_code) for p in probs], args.workers)
    broken = [p.task_id for p, o in zip(probs, ref, strict=True) if not o.passed]
    print(
        f"reference solutions passing their own tests: "
        f"{len(probs) - len(broken)}/{len(probs)}  ({time.time() - t:.0f}s)"
    )
    if broken:
        print(
            f"  excluded (reference does not pass): {broken[:12]}"
            f"{' ...' if len(broken) > 12 else ''}"
        )
    usable = [p for p, o in zip(probs, ref, strict=True) if o.passed]

    jobs, meta = [], []
    for p in usable:
        for m in mutants(p.code, limit=args.per_problem):
            jobs.append((m.code, list(p.test_list), p.test_setup_code))
            meta.append((p, m))
    print(f"mutants to run: {len(jobs)}")
    if not jobs:
        print("nothing to run")
        return 1

    t = time.time()
    outcomes = run_many(jobs, args.workers)
    print(f"ran in {time.time() - t:.0f}s")

    rows = []
    for (p, m), o in zip(meta, outcomes, strict=True):
        rows.append(
            {
                "task_id": p.task_id,
                "kind": m.kind,
                "where": m.where,
                "status": o.status,
                "survived": o.passed,
                "code": m.code,
            }
        )

    # Survival alone overstates weakness: some mutants are equivalent to the original
    # and no suite could catch them. Look for an input that separates each survivor
    # from the reference, so the headline counts proven-wrong programs rather than
    # merely-surviving ones.
    if not args.no_witness:
        by_id = {p.task_id: p for p in usable}
        survivors = [r for r in rows if r["survived"]]
        jobs2 = [
            (
                by_id[r["task_id"]].code,
                r["code"],
                by_id[r["task_id"]].entry_point,
                by_id[r["task_id"]].witness_tests,
                by_id[r["task_id"]].test_setup_code,
            )
            for r in survivors
            if by_id[r["task_id"]].entry_point
        ]
        eligible = [r for r in survivors if by_id[r["task_id"]].entry_point]
        print(f"\nsearching for separating inputs on {len(jobs2)} survivors...")
        t = time.time()
        witnesses = find_many(jobs2, args.workers)
        print(f"  done in {time.time() - t:.0f}s")
        for r, w in zip(eligible, witnesses, strict=True):
            r["proven_wrong"] = w.found
            if w.found:
                r["witness"] = {"args": w.args, "ref": w.ref, "mut": w.mut}
            else:
                r["witness_reason"] = w.reason

    OUT.mkdir(parents=True, exist_ok=True)
    with (OUT / f"mutation_{args.split}.jsonl").open("w", encoding="utf-8") as fh:
        for r in rows:
            fh.write(json.dumps(r) + "\n")

    report(rows, usable, args.split)
    return 0


def report(rows: list[dict], usable, split: str = "full") -> None:
    n = len(rows)
    survived = [r for r in rows if r["survived"]]
    status = Counter(r["status"] for r in rows)

    # The headline names the suite being measured. Leaving "MBPP's 3 asserts" hardcoded
    # would print it over HumanEval's numbers too, and a reader has no way to tell.
    suite = "HumanEval's ~7 asserts" if split == "humaneval" else "MBPP's 3 asserts"
    print("\n" + "=" * 70)
    print(f"MUTATION SURVIVAL - wrong code that {suite} accept")
    print("=" * 70)
    print(f"  mutants run       : {n}")
    print(f"  SURVIVED (passed) : {len(survived)}  ({len(survived) / n:.1%})  <- false accepts")
    print(f"  killed            : {n - len(survived)}  ({1 - len(survived) / n:.1%})")
    print("\n  how the killed ones died:")
    for k in ("fail", "error", "timeout"):
        if status[k]:
            print(f"    {k:8} {status[k]:5}  ({status[k] / n:5.1%})")
    caught_by_assert = status["fail"] / (n - len(survived)) if n - len(survived) else 0
    print(
        f"\n  of those killed, {caught_by_assert:.1%} failed an assert; the rest "
        "crashed or hung,\n  which the suite catches without actually testing for it."
    )

    print("\n  survival by mutation kind:")
    by_kind: dict[str, list[dict]] = defaultdict(list)
    for r in rows:
        by_kind[r["kind"]].append(r)
    for kind, rs in sorted(by_kind.items(), key=lambda kv: -len(kv[1])):
        s = sum(1 for r in rs if r["survived"])
        bar = "#" * round(28 * s / len(rs))
        print(f"    {kind:12} {len(rs):5}  survived {s / len(rs):6.1%}  {bar}")

    # Per problem: a suite that kills nothing is the strongest statement available.
    per: dict[int, list[dict]] = defaultdict(list)
    for r in rows:
        per[r["task_id"]].append(r)
    none_killed = [t for t, rs in per.items() if all(r["survived"] for r in rs)]
    all_killed = [t for t, rs in per.items() if not any(r["survived"] for r in rs)]
    print(f"\n  problems with mutants          : {len(per)}")
    print(
        f"  suites that killed NOTHING     : {len(none_killed)}  "
        f"({len(none_killed) / len(per):.1%})"
    )
    print(
        f"  suites that killed EVERYTHING  : {len(all_killed)}  ({len(all_killed) / len(per):.1%})"
    )

    checked = [r for r in survived if "proven_wrong" in r]
    if checked:
        proven = [r for r in checked if r["proven_wrong"]]
        print("\n  " + "-" * 66)
        print("  SEPARATING INPUTS - survivors proven to be different programs")
        print("  " + "-" * 66)
        print(f"    survivors checked : {len(checked)}")
        print(
            f"    PROVEN WRONG      : {len(proven)}  "
            f"({len(proven) / len(checked):.1%} of survivors)"
        )
        print(
            f"    unproven          : {len(checked) - len(proven)}  "
            "(equivalent, or not separated by the inputs tried)"
        )
        print(
            f"\n    => {len(proven) / n:.1%} of all mutants are provably wrong programs "
            f"that {'HumanEval' if split == 'humaneval' else 'MBPP'} accepts"
        )
        print("\n    witnesses:")
        for r in proven[:6]:
            w = r["witness"]
            print(f"      task {r['task_id']:4}  f({w['args'][:36]})")
            print(f"              reference {w['ref'][:34]}   mutant {w['mut'][:34]}")
    else:
        print("\n  sample survivors:")
        for r in survived[:5]:
            first = next((ln for ln in r["code"].splitlines() if ln.strip().startswith("def ")), "")
            print(f"    task {r['task_id']:4} [{r['where']:14}] {first.strip()[:56]}")
    print(f"\nwrote {OUT / f'mutation_{split}.jsonl'}")


if __name__ == "__main__":
    raise SystemExit(main())
