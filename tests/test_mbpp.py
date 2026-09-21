"""Tests that never need the dataset.

Every case is hand-written code, so a red suite means the mutation or scoring logic is
wrong rather than that a Hugging Face cache was missing.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from data import Problem  # noqa: E402
from differential import call_args, candidate_calls, find_witness  # noqa: E402
from mutate import mutants  # noqa: E402
from sandbox import run  # noqa: E402

GOOD = "def add(a, b):\n    return a + b\n"
TESTS = ["assert add(1, 2) == 3", "assert add(0, 0) == 0"]


# --- sandbox -------------------------------------------------------------------------


def test_correct_code_passes():
    assert run(GOOD, TESTS).status == "pass"


def test_wrong_code_fails_an_assert():
    o = run("def add(a, b):\n    return a - b\n", TESTS)
    assert o.status == "fail"
    assert o.caught and not o.passed


def test_missing_function_is_an_error_not_a_failure():
    # NameError is the suite catching a crash, not testing behaviour. The distinction
    # is the point of separating `error` from `fail`.
    assert run("x = 1\n", TESTS).status == "error"


def test_infinite_loop_times_out():
    code = "def add(a, b):\n    while True:\n        pass\n"
    assert run(code, TESTS, timeout=3).status == "timeout"


def test_syntax_error_is_an_error():
    assert run("def add(a, b)\n    return a\n", TESTS).status == "error"


# --- mutation ------------------------------------------------------------------------


def test_produces_mutants_for_an_operator():
    ms = mutants(GOOD)
    assert any("a - b" in m.code for m in ms)


def test_comparison_is_mutated_to_its_neighbour():
    ms = mutants("def f(a, b):\n    return a < b\n")
    assert any("a <= b" in m.code for m in ms)


def test_integer_constant_is_nudged():
    ms = mutants("def f():\n    return 41\n")
    assert any("42" in m.code for m in ms)


def test_if_condition_can_be_negated():
    ms = mutants("def f(x):\n    if x:\n        return 1\n    return 0\n")
    assert any("not x" in m.code for m in ms)


def test_no_mutant_equals_the_original():
    src = "def f(a, b):\n    return a + b\n"
    for m in mutants(src):
        assert m.code.strip() != src.strip()


def test_mutants_are_syntactically_valid():
    import ast

    src = (
        "def f(xs):\n"
        "    t = 0\n"
        "    for i in range(len(xs)):\n"
        "        if xs[i] > 0:\n"
        "            t += xs[i] * 2\n"
        "    return t\n"
    )
    for m in mutants(src):
        ast.parse(m.code)  # raises if the mutation produced broken source


def test_code_with_no_mutable_sites_yields_nothing():
    assert mutants("def f(s):\n    return s\n") == []


def test_syntax_error_yields_no_mutants():
    assert mutants("def f(:\n") == []


def test_limit_is_respected():
    src = "def f(a):\n    return a + 1 + 2 + 3 + 4 + 5 + 6\n"
    assert len(mutants(src, limit=2)) <= 2


# --- differential --------------------------------------------------------------------


def test_extracts_call_arguments():
    args = call_args("assert add(1, 2) == 3")
    assert args is not None and len(args) == 2


def test_no_call_returns_none():
    assert call_args("assert True") is None


def test_candidates_include_the_original_call():
    cands = candidate_calls(("assert add(1, 2) == 3",))
    assert "1, 2" in cands


def test_candidates_perturb_each_argument():
    cands = candidate_calls(("assert add(1, 2) == 3",))
    assert len(cands) > 1
    assert any(c != "1, 2" for c in cands)


def test_witness_found_for_a_genuinely_different_program():
    w = find_witness(GOOD, "def add(a, b):\n    return a * b\n", "add", ("assert add(1, 2) == 3",))
    assert w.found
    assert w.ref != w.mut


def test_no_witness_for_an_equivalent_program():
    # Same function, spelled differently: nothing can separate these.
    same = "def add(a, b):\n    return b + a\n"
    assert not find_witness(GOOD, same, "add", ("assert add(1, 2) == 3",)).found


def test_witness_separates_exception_from_value():
    crasher = "def add(a, b):\n    return a / 0\n"
    w = find_witness(GOOD, crasher, "add", ("assert add(1, 2) == 3",))
    assert w.found and "ZeroDivisionError" in w.mut


# --- problem model -------------------------------------------------------------------


def test_entry_point_is_read_from_the_asserts():
    p = Problem(1, "t", GOOD, tuple(TESTS), "", ())
    assert p.entry_point == "add"


def test_entry_point_is_none_when_no_call_is_present():
    p = Problem(1, "t", GOOD, ("assert True",), "", ())
    assert p.entry_point is None


def test_entry_point_handles_negated_assert():
    p = Problem(1, "t", GOOD, ("assert not is_empty([1])",), "", ())
    assert p.entry_point == "is_empty"


# --- splits --------------------------------------------------------------------------


def test_unknown_split_is_rejected():
    import pytest

    from data import load

    with pytest.raises(ValueError, match="unknown split"):
        load(split="nonexistent")


def test_both_splits_are_known():
    from data import SPLITS

    assert set(SPLITS) == {"full", "sanitized"}


# --- humaneval -----------------------------------------------------------------------
#
# Hand-written in HumanEval's shape, so these fail when the adapter is wrong rather than
# when `data/humaneval.jsonl` is absent.

HE_CHECK = (
    "def check(candidate):\n"
    "    assert candidate(1, 2) == 3\n"
    "    assert candidate(0, 0) == 0\n"
    "    assert candidate(-1, 1) == 0\n"
)
HE = Problem(
    task_id=0,
    text="def add(a, b):\n    '''Add.'''\n",
    code=GOOD,
    test_list=(HE_CHECK, "check(add)"),
    test_setup_code="",
    challenge_test_list=(),
    source="humaneval",
    named_entry_point="add",
)


def test_humaneval_entry_point_is_the_function_not_the_parameter():
    # Read from the asserts it would be "candidate", which exists in no solution, and
    # the witness search would then silently separate nothing.
    assert HE.entry_point == "add"


def test_humaneval_suite_actually_runs():
    # `check` is only defined by the blob. Without the trailing call the candidate
    # passes by asserting nothing, which is a 0% false-accept rate that means nothing ran.
    assert run(HE.code, list(HE.test_list)).status == "pass"
    assert run(HE.code, [HE_CHECK]).status == "pass"  # defines check, never calls it
    assert run("def add(a, b):\n    return a - b\n", list(HE.test_list)).status == "fail"


def test_humaneval_asserts_are_unpacked_and_renamed():
    assert HE.asserts == (
        "assert add(1, 2) == 3",
        "assert add(0, 0) == 0",
        "assert add(-1, 1) == 0",
    )


def test_witness_tests_give_the_search_every_assert():
    # The whole point: `test_list` would hand the search one blob and yield one seed,
    # making HumanEval's survivors look equivalent when the search was just starved.
    assert len(candidate_calls(HE.witness_tests)) > len(candidate_calls(HE.test_list))


def test_prompt_test_is_one_assert_not_the_whole_suite():
    # Passing the blob would show the model every assert it is about to be graded on.
    assert HE.prompt_test == "assert add(1, 2) == 3"
    assert "check" not in HE.prompt_test


def test_mbpp_problems_are_unaffected():
    p = Problem(1, "t", GOOD, tuple(TESTS), "", ())
    assert p.source == "mbpp"
    assert p.asserts == tuple(TESTS)
    assert p.witness_tests == tuple(TESTS)
    assert p.prompt_test == TESTS[0]
