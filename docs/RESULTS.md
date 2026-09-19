# Results

[<- back to README](../README.md) &middot; [Method](METHOD.md)

All numbers from `results/full_split.log` and `results/sanitized_split.log`, reproducible
with `python run_mutation.py [--split sanitized]`. No model needed for this arm.

## Arm 1 - mutation

### Full split (974 problems)

```
reference solutions passing their own tests: 973/974
mutants run       : 5116
SURVIVED (passed) :  898  (17.6%)
killed            : 4218  (82.4%)
```

Survivors checked for a separating input:

```
survivors checked : 897
PROVEN WRONG      : 442  (49.3% of survivors)
unproven          : 455

=> 8.6% of all mutants are provably wrong programs that MBPP accepts
```

Per problem: **227 of the 782 problems with mutable code (29.0%)** have a suite that
accepts at least one provably wrong program. Seven suites killed nothing at all: tasks
133, 184, 326, 658, 695, 809, 870.

Median per-problem survival is 0% and the mean is 13%. The weakness is concentrated, not
spread evenly - most suites are adequate and a minority are very weak.

### Sanitized split (427 hand-verified problems)

```
reference solutions passing their own tests: 427/427
mutants run       : 1979
SURVIVED (passed) :  316  (16.0%)
PROVEN WRONG      :  145  (46.8% of survivors) = 7.3% of all mutants
```

### The comparison

| | full | sanitized |
|---|---:|---:|
| references passing own tests | 973/974 | 427/427 |
| survival | 17.6% | 16.0% |
| provably wrong, of all mutants | 8.6% | 7.3% |
| problems with ≥1 proven-wrong survivor | 29.0% | 22.9% |
| `compare` survival | 25.9% | 25.8% |
| `const` survival | 25.3% | 22.8% |
| suites killing nothing | 0.9% | 0.9% |
| suites killing everything | 56.6% | 63.7% |

Hand-verification fixed the reference solutions and left the false-accept rate roughly
where it was. The `compare` survival rate is identical to within a tenth of a point.

Reviewing an assert can catch an assert that is *wrong*. It cannot add the fourth assert
that would pin down the boundary, and that is what is missing.

## By mutation kind

Full split:

| Kind | Run | Survived | What it is |
|---|---:|---:|---|
| `compare` | 788 | **25.9%** | `<` becomes `<=` |
| `const` | 2177 | **25.3%** | `2` becomes `3` |
| `boolop` | 115 | 10.4% | `and` becomes `or` |
| `binop` | 1442 | 7.5% | `+` becomes `-` |
| `negate_if` | 594 | 3.9% | `if c` becomes `if not c` |

The ordering is the useful part. Swapping an arithmetic operator or negating a condition
changes the answer loudly, and three examples usually notice. Shifting a boundary by one
changes the answer only at the boundary - and the boundary is exactly what three
hand-picked examples tend not to contain.

## How the caught mutants were caught

| Outcome | Full | Sanitized |
|---|---:|---:|
| `fail` - an assert failed | 69.9% | 72.2% |
| `error` - crashed | 10.8% | 10.7% |
| `timeout` - hung | 1.8% | 1.2% |

Of the mutants that were caught, **15.3%** (full) were caught by crashing or hanging
rather than by failing a test. That still produces a red result, but it is not the suite
testing behaviour: the same mutation behind a guard clause would have survived.

## Worked examples

### Task 3 - `is_not_prime`

```python
def is_not_prime(n):
    result = False
    for i in range(2, int(math.sqrt(n)) + 1):
        if n % i == 0:
            result = True
    return result
```

Asserts: `is_not_prime(2) == False`, `is_not_prime(10) == True`, `is_not_prime(35) == True`.

Three separate mutations survive all three: `n % i != 0`, `not n % i == 0`, and
`n % i == 1`. Each inverts the divisibility test. The test values are either composite
with a small divisor (10, 35) or too small to enter the loop (2), so the inverted
condition arrives at the same answer by the opposite route.

`is_not_prime(11)` returns `False` for the reference and `True` for the mutant. The
mutant calls every prime above 3 composite: 5, 7, 11, 13, 17, 19, 23, 29.

### Task 184 - `greater_specificnum`

```python
def greater_specificnum(list, num):
    return all(x >= num for x in list)
```

```python
assert greater_specificnum([220, 330, 500], 200) == True
assert greater_specificnum([12, 17, 21],    20)  == False
assert greater_specificnum([1, 2, 3, 4],    10)  == False
```

Change `>=` to `>` and all three still pass, because no element in any of the three
equals `num`. The single input that separates `>=` from `>` never appears.

`greater_specificnum([1, 2, 3, 4], 1)` is `True` for the reference and `False` for the
mutant.

## Two harness bugs that produced false findings

Both were caught by checking a surprising number instead of reporting it.

**Newline translation.** `Path.write_text` on Windows rewrites LF as CRLF, and MBPP source
already containing CRLF became CR CR LF - which turns a backslash line-continuation into a
`SyntaxError`. Valid reference solutions looked broken and an entire mutation run had to be
discarded, because mutants were being scored as killed when they had never run.

**Setup order.** The runner executed `test_setup_code` before the solution, but several
problems define a class in the solution (`class Node`) that setup then instantiates.

Together these made five reference solutions look broken. Exactly one is: **task 180**,
which asserts float equality on a haversine distance.

## Is the witness search strong enough?

442 of 897 survivors were proven wrong. The obvious objection is that the other 455 are
separable too and the search is simply too weak - which would mean the headline understates
the problem rather than overstating it.

Tested rather than assumed. Twenty-five unproven survivors were sampled and attacked with a
brute-force search far wider than the real one: every combination of up to three arguments
drawn from a pool of ints, negatives, empty and non-empty lists, tuples and strings, up to
3,000 combinations per mutant.

**It separated 3 of 25.**

So the unproven bucket is mostly genuine equivalent mutants, not search failure. Scaling that
rate over all 455 would move the headline from 8.6% to roughly 9.7% - the right order, and
the reported number stays a lower bound.

The 455 break down as 425 where no separating input was found and 30 where the probe itself
timed out, the latter being mutants that hang on some input.

## What this does not establish

- MBPP's reference solutions are the oracle here, not ground truth about the task
  descriptions. Where a reference is wrong, a "wrong" mutant may be right.
- 455 survivors (full) had no separating input found. Some are genuinely equivalent
  mutants; others were simply not separated by the inputs tried. They are reported as
  unproven and excluded from the headline.
- 192 of 974 problems contain no mutable AST site and produce no mutants.
- Nothing here transfers to HumanEval, whose suites are larger.
