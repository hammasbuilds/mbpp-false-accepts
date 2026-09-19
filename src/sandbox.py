"""Run a candidate solution against a list of assert statements.

Every execution happens in a separate process with a wall-clock timeout. Two reasons,
and the second is the one that matters: mutated code loops forever surprisingly often -
changing `i + 1` to `i - 1` inside a `while` is a perfectly ordinary mutation and a
perfectly reliable hang - and a run that hangs without a timeout is indistinguishable
from a run that is merely slow.

Outcomes are deliberately distinguished rather than collapsed into pass/fail:

- `pass`    - every assert held
- `fail`    - an assert raised AssertionError, the honest way to be wrong
- `error`   - any other exception: NameError, TypeError, ZeroDivisionError
- `timeout` - did not finish in time

`fail` and `error` are both "the tests caught it", but only `fail` means the test suite
did its job as written. Collapsing them hides how often a mutant is caught by crashing
rather than by being tested.
"""

from __future__ import annotations

import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path

TIMEOUT = 8.0

# Order matters: solution, then setup, then asserts. Several problems define a class
# in the solution (`class Node`) that the setup code then instantiates to build a
# fixture. Running setup first raises NameError and makes a working reference look
# broken - which is what it did here, on tasks 367 and 927.
_RUNNER = """\
import sys
{code}

{setup}

{tests}
print("__MBPP_OK__")
"""


@dataclass(frozen=True)
class Outcome:
    status: str  # pass | fail | error | timeout
    detail: str = ""

    @property
    def passed(self) -> bool:
        return self.status == "pass"

    @property
    def caught(self) -> bool:
        """The suite rejected this code, by any means."""
        return self.status in ("fail", "error", "timeout")


def run(code: str, tests: list[str], setup: str = "", timeout: float = TIMEOUT) -> Outcome:
    src = _RUNNER.format(setup=setup, code=code, tests="\n".join(tests))
    with tempfile.TemporaryDirectory() as tmp:
        f = Path(tmp) / "candidate.py"
        # newline="" disables Windows newline translation. Without it every LF is
        # written as CRLF, and MBPP source that already contains CRLF becomes CR CR LF.
        # That turns a backslash line-continuation into a SyntaxError and makes a
        # valid reference solution look broken - it did, on tasks 113 and 121.
        f.write_text(src, encoding="utf-8", newline="")
        try:
            r = subprocess.run(
                [sys.executable, str(f)],
                capture_output=True, text=True, encoding="utf-8",
                errors="replace", timeout=timeout,
                # Inherit no cwd of ours: a candidate that writes files should not be
                # able to write them next to the source it was generated from.
                cwd=tmp,
            )
        except subprocess.TimeoutExpired:
            return Outcome("timeout")
        except OSError as exc:  # process table exhaustion under heavy parallelism
            return Outcome("error", f"spawn failed: {exc}")

    if "__MBPP_OK__" in (r.stdout or ""):
        return Outcome("pass")
    err = (r.stderr or "").strip()
    last = err.rsplit("\n", 1)[-1] if err else ""
    if "AssertionError" in err:
        return Outcome("fail", last)
    return Outcome("error", last[:200])


def run_many(jobs: list[tuple[str, list[str], str]], workers: int = 8) -> list[Outcome]:
    """Run many candidates concurrently.

    Threads, not processes: each job already spawns its own interpreter, so the work
    happens outside the GIL and a thread pool just keeps several subprocesses in flight.
    """
    from concurrent.futures import ThreadPoolExecutor

    with ThreadPoolExecutor(max_workers=workers) as pool:
        return list(pool.map(lambda j: run(j[0], j[1], j[2]), jobs))


if __name__ == "__main__":
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from data import load

    probs = load(limit=40)
    jobs = [(p.code, list(p.test_list), p.test_setup_code) for p in probs]
    outcomes = run_many(jobs)
    from collections import Counter

    c = Counter(o.status for o in outcomes)
    print(f"reference solutions on their own tests ({len(probs)} problems):")
    for k, v in c.most_common():
        print(f"  {k:8} {v}")
    for p, o in zip(probs, outcomes, strict=True):
        if not o.passed:
            print(f"  task {p.task_id}: {o.status} - {o.detail[:90]}")
