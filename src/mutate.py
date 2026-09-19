"""Single-point mutations of a reference solution.

A mutant is the reference solution with exactly one thing changed: a comparison
flipped, an operator swapped, a constant nudged, a condition negated. Each one is a
program that is *provably different* from the one MBPP calls correct.

If the three asserts still pass, the suite cannot tell the difference between the
reference solution and a program that is not it. That is a false accept, and counting
them is the whole point.

One change at a time, on purpose. Multiple simultaneous changes are more likely to break
the program loudly, which would flatter the test suite by making mutants easier to catch.

Not every surviving mutant is a real bug - some mutations are genuinely equivalent, like
`a < b` to `b > a`. Equivalent mutants are the known hard problem in mutation testing and
cannot be detected in general, so `run_mutation.py` reports the survival rate as an upper
bound on weakness and samples survivors by hand rather than claiming every one is a hole.
"""

from __future__ import annotations

import ast
import copy
from dataclasses import dataclass

# Flip a comparison to its neighbour rather than its opposite where possible: `<` to
# `<=` is the off-by-one a person actually writes, and it is the case a three-assert
# suite is least likely to cover.
CMP_SWAP = {
    ast.Lt: ast.LtE, ast.LtE: ast.Lt,
    ast.Gt: ast.GtE, ast.GtE: ast.Gt,
    ast.Eq: ast.NotEq, ast.NotEq: ast.Eq,
    ast.Is: ast.IsNot, ast.IsNot: ast.Is,
    ast.In: ast.NotIn, ast.NotIn: ast.In,
}

BIN_SWAP = {
    ast.Add: ast.Sub, ast.Sub: ast.Add,
    ast.Mult: ast.FloorDiv, ast.FloorDiv: ast.Mult,
    ast.Div: ast.Mult,
    ast.Mod: ast.FloorDiv,
    ast.Pow: ast.Mult,
    ast.BitAnd: ast.BitOr, ast.BitOr: ast.BitAnd,
}

BOOL_SWAP = {ast.And: ast.Or, ast.Or: ast.And}


@dataclass(frozen=True)
class Mutant:
    code: str
    kind: str
    where: str


class _Counter(ast.NodeVisitor):
    """Count mutable sites so each can be addressed by index."""

    def __init__(self):
        self.sites: list[tuple[str, int]] = []
        self._i = 0

    def visit(self, node):
        if isinstance(node, ast.Compare) and node.ops and type(node.ops[0]) in CMP_SWAP:
            self.sites.append(("compare", self._i))
        elif isinstance(node, ast.BinOp) and type(node.op) in BIN_SWAP:
            self.sites.append(("binop", self._i))
        elif isinstance(node, ast.BoolOp) and type(node.op) in BOOL_SWAP:
            self.sites.append(("boolop", self._i))
        elif (
            isinstance(node, ast.Constant)
            and isinstance(node.value, int)
            and not isinstance(node.value, bool)
        ):
            self.sites.append(("const", self._i))
        elif isinstance(node, ast.If):
            self.sites.append(("negate_if", self._i))
        self._i += 1
        self.generic_visit(node)


class _Applier(ast.NodeTransformer):
    """Apply the mutation at one specific site index."""

    def __init__(self, target: int, kind: str):
        self.target, self.kind = target, kind
        self._i = 0
        self.applied = False

    def visit(self, node):
        i = self._i
        self._i += 1
        node = self.generic_visit(node)
        if i != self.target or self.applied:
            return node

        if self.kind == "compare" and isinstance(node, ast.Compare):
            op = type(node.ops[0])
            if op in CMP_SWAP:
                node.ops[0] = CMP_SWAP[op]()
                self.applied = True
        elif self.kind == "binop" and isinstance(node, ast.BinOp):
            op = type(node.op)
            if op in BIN_SWAP:
                node.op = BIN_SWAP[op]()
                self.applied = True
        elif self.kind == "boolop" and isinstance(node, ast.BoolOp):
            op = type(node.op)
            if op in BOOL_SWAP:
                node.op = BOOL_SWAP[op]()
                self.applied = True
        elif self.kind == "const" and isinstance(node, ast.Constant):
            if isinstance(node.value, int) and not isinstance(node.value, bool):
                node.value = node.value + 1
                self.applied = True
        elif self.kind == "negate_if" and isinstance(node, ast.If):
            node.test = ast.UnaryOp(op=ast.Not(), operand=node.test)
            self.applied = True
        return node


def mutants(code: str, limit: int | None = None) -> list[Mutant]:
    """Every single-point mutant of `code`, capped at `limit`."""
    try:
        tree = ast.parse(code)
    except SyntaxError:
        return []

    counter = _Counter()
    counter.visit(tree)

    out: list[Mutant] = []
    seen: set[str] = {_normalise(code)}
    for kind, idx in counter.sites:
        applier = _Applier(idx, kind)
        mutated = applier.visit(copy.deepcopy(tree))
        if not applier.applied:
            continue
        try:
            ast.fix_missing_locations(mutated)
            src = ast.unparse(mutated)
        except (ValueError, AttributeError, RecursionError):
            continue
        norm = _normalise(src)
        # A mutation that unparses to the original changed nothing observable; counting
        # it as a survivor would inflate the false-accept rate with no-ops.
        if norm in seen:
            continue
        seen.add(norm)
        out.append(Mutant(code=src, kind=kind, where=f"{kind}@{idx}"))
        if limit and len(out) >= limit:
            break
    return out


def _normalise(code: str) -> str:
    try:
        return ast.unparse(ast.parse(code))
    except SyntaxError:
        return code


if __name__ == "__main__":
    import sys
    from collections import Counter as C
    from pathlib import Path

    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from data import load

    probs = load(limit=100)
    per = [len(mutants(p.code)) for p in probs]
    kinds = C(m.kind for p in probs for m in mutants(p.code))
    print(f"problems            : {len(probs)}")
    print(f"mutants per problem : min {min(per)}, max {max(per)}, mean {sum(per) / len(per):.1f}")
    print(f"problems with none  : {sum(1 for x in per if x == 0)}")
    print("\nby kind:")
    for k, v in kinds.most_common():
        print(f"  {k:12} {v}")
    p = probs[2]
    print(f"\nexample - task {p.task_id}:\n{p.code}")
    for m in mutants(p.code)[:3]:
        print(f"\n  [{m.where}]\n{m.code}")
