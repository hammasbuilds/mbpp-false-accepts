# Method

[<- back to README](../README.md)

MBPP gives each of its 974 problems a description, one reference solution, and exactly
three `assert` statements. Three asserts is a thin specification. This measures how thin.

## The question

A benchmark's pass rate is only meaningful if passing implies correct. So: **how much
wrong code do three asserts accept?**

Two arms answer it from different directions.

## Arm 1 - mutation

Take the reference solution MBPP calls correct, change exactly one thing, and run the
same three asserts:

| Mutation | Example |
|---|---|
| `compare` | `a < b` becomes `a <= b` |
| `binop` | `a + b` becomes `a - b` |
| `const` | `range(2, n)` becomes `range(3, n)` |
| `negate_if` | `if cond:` becomes `if not cond:` |
| `boolop` | `and` becomes `or` |

One change at a time, deliberately. Several simultaneous changes are likelier to break
the program loudly, which would flatter the suite by making mutants easier to catch.
Comparisons are flipped to their *neighbour* (`<` to `<=`) rather than their opposite,
because the off-by-one is the error people actually write and the case three asserts are
least likely to cover.

A mutant that still passes is a program MBPP cannot distinguish from the right answer.

## Arm 2 - generation

The mutation arm asks whether the asserts *can* be fooled. This asks what happens with the
kind of solution a model actually writes: generate one with a local coder model, keep only
those that pass all three asserts, and then look for an input where the accepted solution
and the reference disagree.

**A disagreement here is not proof the generation is wrong**, and that distinction does not
arise in the mutation arm. A mutant is derived from the reference, so a difference means
the mutant deviates. A generation is written independently, so a difference can equally
mean the *reference* is wrong.

It sometimes does. MBPP's `is_not_prime` returns `False` for 1, which is incorrect - 1 is
not prime. A model that returns `True` disagrees with the reference and is right.

So arm 2 measures something more careful than "the model was wrong": **three asserts do not
pin the behaviour down.** Two programs both pass, they do different things outside the
tested values, and the benchmark has no opinion about which is correct.

## Separating inputs, not just survival

Mutation survival alone **overstates** a suite's weakness. Some mutations are equivalent
to the original - `a < b` and `b > a` compute the same thing - and no test could ever
catch them. Equivalent-mutant detection is undecidable in general, and the usual response
is to note the problem and move on.

Instead, every survivor is checked for a **witness**: an input on which the reference and
the survivor return different values. A survivor with a witness is a *provably* wrong
program that MBPP marked correct. A survivor without one is reported as unproven rather
than counted either way.

Candidate inputs are built from the asserts themselves. MBPP's asserts contain literal
arguments, and perturbing those literals - a number off by one, an emptied list, a
flipped sign, a doubled string - stays inside the type the function expects. That matters:
a function that raises `TypeError` on both sides has not been separated by anything.

Two different exception types do count as a separation. Two identical ones do not.

## Execution

Every candidate runs in its own process with an 8-second timeout.

The timeout is not a formality. Mutated code hangs often - changing `i + 1` to `i - 1`
inside a `while` is an ordinary mutation and a reliable infinite loop - and without a
timeout a hang is indistinguishable from slowness.

Outcomes are kept apart rather than collapsed into pass/fail:

- `pass` - every assert held
- `fail` - an assert raised `AssertionError`, the honest way to be wrong
- `error` - any other exception: `NameError`, `TypeError`, `ZeroDivisionError`
- `timeout` - did not finish in time

`fail` and `error` both mean the suite rejected the code, but only `fail` means the suite
did its job *as written*. Collapsing them hides how often a mutant is caught by crashing
rather than by being tested, which is a different and weaker property.

## Two bugs that produced false findings

Both were caught by checking a surprising number rather than reporting it.

**Newline translation.** `Path.write_text` on Windows rewrites LF as CRLF. MBPP source
already containing CRLF became CR CR LF, which turns a backslash line-continuation into
a `SyntaxError`. Valid reference solutions looked broken, and an entire mutation run had
to be discarded because mutants were being scored as killed when they had never run.

**Setup order.** The runner executed `test_setup_code` before the solution. Several
problems define a class in the solution (`class Node`) that the setup then instantiates
to build a fixture, so setup-first raised `NameError`.

Together these made five reference solutions look broken. Only one - task 180, which
asserts float equality on a haversine distance - actually is.

## Reproducing

```bash
python run_mutation.py              # arm 1, no model needed
python run_mutation.py --limit 50   # quick
python run_model.py                 # arm 2, needs Ollama
```

Both write JSONL to `results/`. Arm 2 caches generations and resumes, because generation
is the expensive half.

## What this does not measure

- **Whether MBPP's reference solutions are right.** They are the oracle here. Where a
  reference is wrong, a "wrong" mutant may be right; the reference is taken as the
  definition of intended behaviour, not as ground truth about the task description.
- **Other benchmarks.** HumanEval's suites are larger; whether this holds there is
  untested.
- **The sanitized split.** MBPP ships a hand-verified subset, `sanitized-mbpp.json`,
  which is the fairer target for a "how good is MBPP" claim and is not used here.
- **Anything about a model's ability.** Arm 2 measures the benchmark, not the model.
