"""Arm 2: does MBPP accept wrong code that a real model actually writes?

The mutation arm asks whether the three asserts *can* be fooled. This asks whether they
are fooled in practice, by the kind of wrong answer a model produces on its own.

For each problem: generate a solution with a local coder model, keep only the ones that
pass all three asserts - MBPP calls these correct - and then look for an input on which
the accepted solution and the reference disagree.

**A disagreement is not proof the generation is wrong.** That distinction matters here and
does not arise in the mutation arm. A mutant is derived from the reference, so a difference
means the mutant deviates. A generation is independent, so a difference can equally mean
the *reference* is wrong - and sometimes it does. MBPP's `is_not_prime` returns `False`
for 1, which is incorrect: 1 is not prime. A model that returns `True` disagrees with the
reference and is right.

So what this measures is that **three asserts do not pin the behaviour down**. Two programs
both pass, they do different things outside the tested values, and the benchmark has no
opinion about which is correct. That is the finding, and it is weaker and more honest than
"the model was wrong".

    python run_model.py                    # all 974
    python run_model.py --limit 50         # quick
    python run_model.py --model qwen2.5-coder:3b
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import threading
import time
import urllib.error
import urllib.request
import warnings
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "src"))

warnings.filterwarnings("ignore", category=SyntaxWarning)

from data import load  # noqa: E402
from differential import find_many  # noqa: E402
from sandbox import run_many  # noqa: E402

OLLAMA = "http://localhost:11434"
OUT = Path(__file__).resolve().parent / "results"

PROMPT = """Write a Python function for this task.

Task: {text}

It must satisfy this test:
{test}

Output ONLY the function definition and any imports it needs. No explanation, no tests.
"""


def _generate(text: str, test: str, model: str, timeout: int = 180) -> str | None:
    payload = {
        "model": model,
        "prompt": PROMPT.format(text=text, test=test),
        "stream": False,
        # Deterministic: a benchmark measurement whose value moves with the seed is
        # not reproducible by whoever reads the number.
        "options": {"temperature": 0.0, "num_predict": 512},
    }
    req = urllib.request.Request(
        f"{OLLAMA}/api/generate",
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as fh:
            return json.loads(fh.read()).get("response", "")
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError):
        return None


_FENCE = re.compile(r"```(?:python)?\s*\n(.*?)```", re.DOTALL)


def extract_code(raw: str) -> str:
    """Pull the code out of a model response.

    How code is extracted is itself a source of benchmark variance - the same
    generations can score anywhere from 0% to 94% depending on the rule - so this is
    deliberately permissive: fenced block if present, otherwise the raw text, which is
    what the model was asked for.
    """
    m = _FENCE.search(raw)
    if m:
        return m.group(1).strip()
    return raw.strip()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int)
    ap.add_argument("--model", default="qwen2.5-coder:14b")
    ap.add_argument("--workers", type=int, default=6)
    ap.add_argument("--gen-workers", type=int, default=8)
    args = ap.parse_args()

    probs = [p for p in load(limit=args.limit) if p.entry_point]
    print(f"problems: {len(probs)}  model: {args.model}")

    OUT.mkdir(parents=True, exist_ok=True)
    gen_path = OUT / f"generations_{args.model.replace(':', '_').replace('/', '_')}.jsonl"

    # Resume: generation is the expensive half and an interrupted run should not
    # repeat it.
    done: dict[int, str] = {}
    if gen_path.exists():
        for line in gen_path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                r = json.loads(line)
                done[r["task_id"]] = r["code"]
    todo = [p for p in probs if p.task_id not in done]
    print(f"generations: {len(done)} cached, {len(todo)} to go")

    # Generate concurrently. One request at a time leaves the GPU near 9% utilised -
    # it spends almost all of its time waiting for the next HTTP round trip instead of
    # decoding. A pool of workers takes it to ~98%.
    t0 = time.time()
    lock = threading.Lock()
    counter = [0]
    with gen_path.open("a", encoding="utf-8") as fh:

        def one(p):
            raw = _generate(p.text, p.test_list[0], args.model)
            code = extract_code(raw) if raw is not None else ""
            with lock:
                done[p.task_id] = code
                fh.write(json.dumps({"task_id": p.task_id, "code": code}) + "\n")
                fh.flush()
                counter[0] += 1
                i = counter[0]
                if i % 25 == 0 or i == len(todo):
                    rate = (time.time() - t0) / i
                    print(
                        f"  {i}/{len(todo)}  {rate:.2f}s each  "
                        f"eta {rate * (len(todo) - i) / 60:.0f} min",
                        flush=True,
                    )

        with ThreadPoolExecutor(max_workers=args.gen_workers) as pool:
            list(pool.map(one, todo))

    # Which generations does MBPP call correct?
    jobs = [(done[p.task_id], list(p.test_list), p.test_setup_code) for p in probs]
    print("\nrunning generations against MBPP's asserts...")
    outcomes = run_many(jobs, args.workers)
    status = Counter(o.status for o in outcomes)
    accepted = [p for p, o in zip(probs, outcomes, strict=True) if o.passed]
    n = len(probs)
    print(f"  accepted by MBPP : {len(accepted)}/{n}  ({len(accepted) / n:.1%})  <- pass@1")
    for k in ("fail", "error", "timeout"):
        if status[k]:
            print(f"  {k:16} : {status[k]}")

    if not accepted:
        print("nothing accepted; stopping")
        return 1

    # Of the accepted ones, how many are not actually the reference behaviour?
    print(f"\nsearching for separating inputs on {len(accepted)} accepted solutions...")
    t = time.time()
    witnesses = find_many(
        [
            (p.code, done[p.task_id], p.entry_point, p.test_list, p.test_setup_code)
            for p in accepted
        ],
        args.workers,
    )
    print(f"  done in {time.time() - t:.0f}s")

    rows = []
    for p, w in zip(accepted, witnesses, strict=True):
        rows.append(
            {
                "task_id": p.task_id,
                "entry_point": p.entry_point,
                "accepted": True,
                "disagrees": w.found,
                "witness": ({"args": w.args, "ref": w.ref, "mut": w.mut} if w.found else None),
                "reason": None if w.found else w.reason,
            }
        )
    (OUT / f"model_{args.model.replace(':', '_')}.jsonl").write_text(
        "".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8"
    )

    differ = [r for r in rows if r["disagrees"]]
    print("\n" + "=" * 70)
    print("UNDERSPECIFIED - accepted solutions that differ from the reference")
    print("=" * 70)
    print(f"  problems attempted    : {n}")
    print(f"  accepted by MBPP      : {len(accepted)}  ({len(accepted) / n:.1%})")
    print(
        f"  of those, DISAGREE    : {len(differ)}  ({len(differ) / len(accepted):.1%} of accepted)"
    )
    print(
        f"\n  => {len(differ) / len(accepted):.1%} of the solutions MBPP accepted behave "
        "differently from the\n     reference on some input. Three asserts did not decide "
        "between them, and\n     which of the two is correct is a question MBPP does not "
        "answer."
    )
    print("\n  witnesses:")
    for r in differ[:8]:
        w = r["witness"]
        print(f"    task {r['task_id']:4} {r['entry_point']:22} f({w['args'][:30]})")
        print(f"          reference {w['ref'][:32]}   generated {w['mut'][:32]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
