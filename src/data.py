"""Load MBPP from the local Hugging Face cache.

MBPP gives each problem a natural-language description, one reference solution, and
exactly three `assert` statements. Three asserts is a thin specification, and whether
they are thin enough to pass wrong code is the question this repository answers.

No network: the dataset is 809 KB and already cached. A benchmark study that cannot run
offline is a benchmark study that silently depends on someone else's uptime.
"""

from __future__ import annotations

import ast
import gzip
import json
import os
import re
from dataclasses import dataclass
from pathlib import Path

CACHE_DIR_NAME = "datasets--Muennighoff--mbpp"

# The name being tested, taken from the first assert: `assert foo(1) == 2` -> `foo`.
_CALLED = re.compile(r"assert\s+(?:not\s+)?([A-Za-z_]\w*)\s*\(")

# EvalPlus stores its cases as `inputs = [...]` immediately above `results = [...]`.
_PLUS_INPUTS = re.compile(r"inputs\s*=\s*(\[.*?\])\s*\n\s*results", re.S)


@dataclass(frozen=True)
class Problem:
    task_id: int
    text: str
    code: str
    test_list: tuple[str, ...]
    test_setup_code: str
    challenge_test_list: tuple[str, ...]
    source: str = "mbpp"
    # HumanEval's asserts call the function through a parameter named `candidate`, so
    # reading the name out of the assert returns "candidate" - a name that exists in no
    # solution. `differential.py` uses this name to call both programs and look for an
    # input that separates them; given the wrong one it finds nothing and reports every
    # survivor as unproven, which reads as "probably equivalent mutants" rather than as
    # "the harness was calling something that does not exist". A silent wrong answer, so
    # the name is carried explicitly where the dataset supplies one.
    named_entry_point: str | None = None

    @property
    def entry_point(self) -> str | None:
        """The function the asserts call, or None if they call nothing recognisable."""
        if self.named_entry_point:
            return self.named_entry_point
        for t in self.test_list:
            m = _CALLED.search(t)
            if m:
                return m.group(1)
        return None

    @property
    def asserts(self) -> tuple[str, ...]:
        """The individual assert statements, however the dataset happens to store them.

        MBPP stores three separate strings. HumanEval stores one `def check(candidate)`
        blob, and every assert inside it calls the function through the parameter name
        `candidate`, so each line is rewritten to name the function it actually tests.

        Multi-line asserts and asserts built inside a loop are skipped rather than
        guessed at, so this is a lower bound on HumanEval's suite, not a full parse.
        """
        if self.source == "humanevalplus":
            return self._plus_cases()
        if self.source != "humaneval":
            return self.test_list
        out = []
        name = self.entry_point or "candidate"
        for line in self.test_list[0].splitlines():
            stripped = line.strip()
            if stripped.startswith("assert ") and "candidate" in stripped:
                out.append(stripped.replace("candidate", name))
        return tuple(out)

    def _plus_cases(self, cap: int = 40) -> tuple[str, ...]:
        """EvalPlus's `inputs` list, rewritten as calls the witness search can mine.

        EvalPlus writes no asserts. Its `check` holds `inputs = [[...], [...]]` beside a
        matching `results`, and loops. So the HumanEval adapter - which reads lines starting
        with `assert` - finds nothing here, `asserts` falls through to the raw 77 KB blob,
        and `call_args` returns the first `Call` it meets in that text: `isinstance(x, float)`
        from a float-comparison helper. The separating-input search is then seeded with two
        junk arguments and proves nothing, which reads as "every survivor is an equivalent
        mutant" - a statement about this benchmark that was a statement about this parser.

        Capped at 40 because the point is to seed a search, not to re-run the suite, and
        some problems ship 1100 cases whose literals are long.
        """
        name = self.entry_point or "candidate"
        m = _PLUS_INPUTS.search(self.test_list[0])
        if not m:
            return ()
        try:
            cases = ast.literal_eval(m.group(1))
        except (ValueError, SyntaxError, MemoryError, RecursionError):
            return ()
        out = []
        for inp in cases[:cap]:
            args = inp if isinstance(inp, list) else [inp]
            try:
                out.append(f"assert {name}({', '.join(repr(a) for a in args)})")
            except (ValueError, RecursionError):
                continue
        return tuple(out)

    @property
    def prompt_test(self) -> str:
        """One example assert, to show the model what the function should do.

        MBPP's `test_list[0]` is one of three asserts, so the model sees a third of the
        specification. HumanEval's whole suite is a single blob, and passing that as the
        example would hand the model every assert it is about to be graded on. The two
        arms would then not be measuring the same thing, and HumanEval would score higher
        for a reason that has nothing to do with HumanEval. One assert each, in both.
        """
        picked = self.asserts
        return picked[0] if picked else f"{self.entry_point}(...)"

    @property
    def witness_tests(self) -> tuple[str, ...]:
        """The asserts the separating-input search mines for candidate arguments.

        It must be the individual asserts, not `test_list`. `differential.call_args`
        takes the first call out of each string it is given, so handing it HumanEval's
        single blob yields one seed input where MBPP gets three - and a search given
        fewer seeds finds fewer witnesses and reports more survivors as "equivalent".
        HumanEval would then look like it had more untestable mutants when the only
        real difference was how its asserts are packaged.
        """
        return self.asserts or self.test_list


def _cache_roots() -> list[Path]:
    roots = []
    if env := os.environ.get("HF_HUB_CACHE"):
        roots.append(Path(env))
    if env := os.environ.get("HF_HOME"):
        roots.append(Path(env) / "hub")
    roots.append(Path.home() / ".cache" / "huggingface" / "hub")
    return roots


SPLITS = {"full": "mbpp.jsonl", "sanitized": "sanitized-mbpp.json"}

# Not an MBPP split. HumanEval is here as a second benchmark with a thicker suite -
# ~7.7 asserts per problem against MBPP's exactly 3 - because "three asserts is too
# thin" and "assert-based acceptance is thin" are different claims and MBPP alone
# cannot separate them. Committed to `data/` by `scripts/convert_humaneval.py`.
HUMANEVAL_FILE = Path(__file__).resolve().parent.parent / "data" / "humaneval.jsonl"

# The third point on the suite-size curve, and by far the widest. EvalPlus keeps HumanEval's
# problems and replaces its handful of asserts with a generated input list - a mean of 775
# cases per problem, median 983. Gzipped because the same content is 11.3 MB as plain JSONL
# and 1.3 MB compressed, and `gzip` is in the standard library, so the repo keeps its
# property of running from a bare checkout.
#
# One caveat that is real: 163 of the 164 EvalPlus suites `import numpy`, so *this split
# alone* needs it. MBPP and HumanEval still need nothing.
HUMANEVALPLUS_FILE = Path(__file__).resolve().parent.parent / "data" / "humanevalplus.jsonl.gz"


def find_file(split: str = "full") -> Path | None:
    if split == "humaneval":
        return HUMANEVAL_FILE if HUMANEVAL_FILE.exists() else None
    if split == "humanevalplus":
        return HUMANEVALPLUS_FILE if HUMANEVALPLUS_FILE.exists() else None
    name = SPLITS[split]
    for root in _cache_roots():
        hits = sorted((root / CACHE_DIR_NAME).glob(f"snapshots/*/data/{name}"))
        if hits:
            return hits[0]
    return None


def _load_humaneval(limit: int | None) -> list[Problem]:
    """HumanEval as `Problem`s. Four fields do not line up with MBPP's and each is a trap.

    `canonical_solution` is only the function *body* - the signature and docstring live
    in `prompt`, so the solution has to be reassembled or it is a syntax error. `task_id`
    is the string "HumanEval/0". The suite is one `def check(candidate)` blob that has to
    be followed by a call to actually run. And the name under test is given explicitly
    rather than being readable from the asserts.
    """
    out: list[Problem] = []
    for line in HUMANEVAL_FILE.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        r = json.loads(line)
        if "_provenance" in r:  # header record written by the converter
            continue
        entry = r["entry_point"]
        out.append(
            Problem(
                task_id=int(str(r["task_id"]).rsplit("/", 1)[-1]),
                text=r["prompt"],
                code=r["prompt"] + r["canonical_solution"],
                # The blob defines `check`; nothing calls it. Without the second element
                # every candidate "passes" by running no assertions at all - a 0% false
                # accept rate that means the tests never executed.
                test_list=(r["test"], f"check({entry})"),
                test_setup_code="",
                challenge_test_list=(),
                source="humaneval",
                named_entry_point=entry,
            )
        )
        if limit and len(out) >= limit:
            break
    return out


# Kept for the original call sites; `find_file` is the general form.
def find_jsonl() -> Path | None:
    return find_file("full")


def _load_humanevalplus(limit: int | None) -> list[Problem]:
    """EvalPlus as `Problem`s. Same shape as HumanEval; only the suite is different.

    Its `check(candidate)` holds an `inputs` list and a matching `results` list and loops
    over them, so counting `assert` statements the way the HumanEval adapter does reports
    2 per problem for a 77 KB suite. The quantity that varies across these three splits is
    the number of *test cases*, and `case_count` is what reports it.
    """
    out: list[Problem] = []
    with gzip.open(HUMANEVALPLUS_FILE, "rt", encoding="utf-8") as fh:
        for line in fh:
            if not line.strip():
                continue
            r = json.loads(line)
            if "_provenance" in r:
                continue
            entry = r["entry_point"]
            out.append(
                Problem(
                    task_id=int(str(r["task_id"]).rsplit("/", 1)[-1]),
                    text=r["prompt"],
                    code=r["prompt"] + r["canonical_solution"],
                    test_list=(r["test"], f"check({entry})"),
                    test_setup_code="",
                    challenge_test_list=(),
                    source="humanevalplus",
                    named_entry_point=entry,
                )
            )
            if limit and len(out) >= limit:
                break
    return out


def load(limit: int | None = None, split: str = "full") -> list[Problem]:
    """Problems from one MBPP split.

    `full` is all 974 as released. `sanitized` is the 427 the authors hand-verified,
    and it is the fairer target for any claim about MBPP's quality: its asserts are
    revised, not merely re-copied. Comparing the two is the point - if the verified
    subset accepts wrong code at the same rate, hand-verification did not fix what
    three asserts cannot express.
    """
    if split == "humanevalplus":
        if not HUMANEVALPLUS_FILE.exists():
            raise FileNotFoundError(
                f"{HUMANEVALPLUS_FILE} is missing.\n"
                "Rebuild it:  python scripts/convert_humanevalplus.py  (needs pyarrow)"
            )
        return _load_humanevalplus(limit)

    if split == "humaneval":
        if not HUMANEVAL_FILE.exists():
            raise FileNotFoundError(
                f"{HUMANEVAL_FILE} is missing.\n"
                "Rebuild it:  python scripts/convert_humaneval.py  (needs pyarrow)"
            )
        return _load_humaneval(limit)

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
