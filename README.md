<h1 align="center">mbpp-false-accepts (Python · stdlib ast · mutation testing · differential fuzzing)</h1>
<p align="center"><i>MBPP gives each problem three assert statements. Three asserts accept a lot of wrong code.</i></p>

<p align="center">
  <a href="https://github.com/hammasbuilds/mbpp-false-accepts/actions/workflows/ci.yml"><img src="https://github.com/hammasbuilds/mbpp-false-accepts/actions/workflows/ci.yml/badge.svg" alt="ci"></a>
  <img src="https://img.shields.io/badge/python-3.11%2B-blue" alt="python">
  <img src="https://img.shields.io/badge/runtime%20deps-0-brightgreen" alt="zero dependencies">
  <img src="https://img.shields.io/badge/tests-32-brightgreen" alt="tests">
  <img src="https://img.shields.io/badge/suites%20compared-3%20%C2%B7%207%20%C2%B7%20775-blue" alt="">
</p>

<p align="center">
  <a href="#the-result">The result</a> &middot;
  <a href="#what-that-looks-like">What that looks like</a> &middot;
  <a href="#hand-verification-does-not-fix-it">Hand-verification</a> &middot;
  <a href="#how-much-testing-would-it-take-more-than-anyone-writes">The curve</a> &middot;
  <a href="#run-it">Run it</a> &middot;
  <a href="#input">Input</a> &middot;
  <a href="#output">Output</a> &middot;
  <a href="docs/METHOD.md">Method</a> &middot;
  <a href="docs/RESULTS.md">Results</a>
</p>

---

A benchmark's pass rate only means something if passing implies correct. MBPP specifies
each of its 974 problems with exactly three `assert` statements. This measures how much
wrong code three asserts let through.

## The result

Take each reference solution MBPP calls correct, change exactly one thing - flip a
comparison, swap an operator, nudge a constant - and run the same three asserts.

```
mutants run       : 5116
SURVIVED (passed) : 898  (17.6%)   <- three asserts could not tell these apart
```

Survival alone overstates the problem: some mutations are equivalent to the original and
no test could catch them. So every survivor is checked for a **separating input** - a value
on which the mutant and the reference return different things.

```
survivors checked : 897
PROVEN WRONG      : 442  (49.3% of survivors)

=> 8.6% of all mutants are provably wrong programs that MBPP accepts
```

Put per problem, which is the number that matters:

**227 of the 782 problems with mutable code - 29.0% - have a test suite that accepts at
least one provably wrong program.**

## What that looks like

Task 3, `is_not_prime`, tested on 2, 10 and 35:

```python
def is_not_prime(n):
    result = False
    for i in range(2, int(math.sqrt(n)) + 1):
        if n % i == 0:          # invert this
            result = True
    return result

assert is_not_prime(2)  == False
assert is_not_prime(10) == True
assert is_not_prime(35) == True
```

Invert the condition to `if n % i != 0` and all three still pass. Every test value is
either composite with a small divisor (10, 35) or too small to enter the loop at all (2),
so the inverted condition reaches the same answer by the opposite route.

The mutant claims every prime above 3 is composite. MBPP calls it correct.

```
witness: is_not_prime(11)   reference -> False   mutant -> True
```

Three separate mutations of this function survive: `n % i != 0`, `not n % i == 0`, and
`n % i == 1`.

Task 184, `greater_specificnum`, shows the pattern more sharply. The reference is
`all(x >= num for x in list)`. Change `>=` to `>` and all three asserts still pass:

```python
assert greater_specificnum([220, 330, 500], 200) == True
assert greater_specificnum([12, 17, 21],    20)  == False
assert greater_specificnum([1, 2, 3, 4],    10)  == False
```

Look at what is missing. In none of the three does any element *equal* `num` - so the one
input that distinguishes `>=` from `>` is never tried. Three asserts, and the boundary
the function is about goes untested.

```
witness: greater_specificnum([1, 2, 3, 4], 1)   reference -> True   mutant -> False
```

**Seven problems have suites that killed nothing at all.**

## Hand-verification does not fix it

MBPP ships a **sanitized** split: 427 problems the authors reviewed by hand, with revised
asserts. It is the fairer target for any claim about MBPP's quality, so the same
measurement was run on it.

| | full (974) | sanitized (427) |
|---|---:|---:|
| reference solutions passing their own tests | 973/974 | **427/427** |
| mutants run | 5116 | 1979 |
| survived | 17.6% | **16.0%** |
| provably wrong, of all mutants | 8.6% | **7.3%** |
| problems with ≥1 proven-wrong survivor | 29.0% | **22.9%** |
| `compare` mutations surviving | 25.9% | **25.8%** |
| suites that killed nothing | 7 (0.9%) | 3 (0.9%) |

Verification did what it says on the tin - it fixed the *reference solutions*, taking them
from 973/974 to 427/427 passing. It barely touched the false accepts: 17.6% to 16.0%, and
the `compare` survival rate is the same to within a tenth of a point.

That is the finding. The weakness is not careless asserts that review can catch. **Three
examples cannot pin down a boundary**, however carefully the three are chosen, and
reviewing them one at a time does not change how many there are.

## How much testing would it take? More than anyone writes.

"Three asserts is too thin" and "deciding correctness by running examples is too thin" are
different claims, and MBPP alone cannot separate them - every problem in it has exactly
three. So the same measurement runs on two more suites over the same kind of problems:

- **HumanEval** - hand-written, a mean of **7.2 asserts** per problem
- **EvalPlus** - HumanEval's problems with generated inputs instead, a mean of
  **775 test cases** per problem (median 983, max 1100)

That is a ~250x range in how hard the suite tries.

```
suite        cases/problem   mutants survive   PROVABLY WRONG and accepted
MBPP           3 asserts          17.6%                 8.6%
HumanEval    7.2 asserts          11.4%                 3.3%
EvalPlus     775 cases             8.1%                 1.2%
```

**Testing harder works, and it works with sharply diminishing returns.** The first jump -
3 asserts to 7 - removes most of what is removable. Going from 7 asserts to 775 generated
cases, a 100x increase in effort, buys another 2.1 points.

**And it never closes.** At 775 cases per problem, **13 mutants still pass with a
separating input attached** - programs that return a different answer from the reference on
a value anyone can print, which EvalPlus calls correct. You cannot test your way out of
this by adding cases.

### The same curve, measured a completely different way

The numbers above come from *synthetic* mutants. The model arm asks the same question with
real generated solutions: keep the ones each suite accepts, then look for an input where
the accepted solution and the reference disagree.

```
suite        accepted (pass@1)   of those, DISAGREE with the reference
MBPP           777/972  79.9%              195   25.1%
HumanEval      147/164  89.6%               29   19.7%
EvalPlus       134/164  81.7%               20   14.9%
```

Same direction, same shape, from a method that shares nothing with mutation testing except
the benchmark. **A quarter of what MBPP accepts is underspecified; at 775 test cases it is
still one in seven.**

The disagreements at the EvalPlus end are the interesting ones, because they are what
survives 775 cases:

```
largest_divisor(0)      reference 1        generated None
find_closest_elements([])  reference None  generated (0.0, 0.0)
fib4(-5)                reference 0        generated IndexError
string_xor('1110001', '101010')  reference IndexError   generated '010010'
```

These are not the model being wrong. They are inputs the problem statement never mentions,
where the reference has a behaviour nobody chose and the suite never checks. Which is the
point: **a suite can only pin down behaviour its author thought to describe**, and no amount
of generated cases over the same input distribution finds the edge the author did not
consider.

## The same thing, with solutions a model actually wrote

Mutants are programs nobody wrote. So: generate a solution for all 972 problems with
`qwen2.5-coder:14b`, keep the ones MBPP accepts, and check whether they match the
reference.

```
accepted by MBPP  : 777/972  (79.9%)   <- this is the pass@1 anyone would report
of those, DISAGREE: 195      (25.1% of accepted)
```

**A quarter of the solutions MBPP accepted behave differently from the reference on some
input.** Three asserts did not decide between them.

Note carefully what that is *not*. A disagreement here is not proof the model was wrong -
unlike a mutant, a generated solution is written independently, so the reference can be the
one at fault. It sometimes is:

```
is_not_prime(1)   reference -> False   generated -> True
```

1 is not prime, so the generated answer is right and MBPP's reference is wrong.

The other witnesses are mostly untested edges, where the benchmark simply has no opinion:

```
maximum_Sum([])           reference -> -100000      generated -> ValueError
binomial_Coeff(-5, 2)     reference -> 0            generated -> IndexError
remove_Occ('hello','ll')  reference -> 'hello'      generated -> 'heo'
```

That is the honest version of the finding: **three asserts do not pin the behaviour down**.
Two programs both pass, they differ outside the tested values, and which one is correct is
a question the benchmark does not answer.

## Which mutations slip through

| Mutation | Run | Survived |
|---|---:|---:|
| `compare` - `<` becomes `<=` | 788 | **25.9%** |
| `const` - `2` becomes `3` | 2177 | **25.3%** |
| `boolop` - `and` becomes `or` | 115 | 10.4% |
| `binop` - `+` becomes `-` | 1442 | 7.5% |
| `negate_if` - `if c` becomes `if not c` | 594 | 3.9% |

Off-by-one errors are the ones that get through. A swapped arithmetic operator usually
breaks the answer loudly enough for three examples to notice; a boundary shifted by one
does not.

## How the caught ones were caught

```
fail    3574  (69.9%)   an assert failed - the suite working as written
error    554  (10.8%)   crashed: NameError, IndexError, ZeroDivisionError
timeout   90  ( 1.8%)   hung
```

Of the mutants that were caught, **15.3% were caught by crashing or hanging rather than by
failing a test**. That counts as a pass/fail signal but it is not the suite testing
behaviour - the same mutant with a guard clause would have survived.

## Limits

- **The reference solution is the oracle.** Where a reference is itself wrong, a "wrong"
  mutant may be right. This measures the suite against the reference, not against the task
  description.
- **Unproven survivors are not counted as wrong.** 455 survivors had no separating input
  found. Some are genuinely equivalent; others are simply not separated by the inputs
  tried. They are reported, not claimed.
- **Only one benchmark.** HumanEval's suites are larger and this says nothing about them.
- 192 of 974 problems have no mutable AST site and produce no mutants at all.

Exactly one reference solution fails its own tests: task 180 asserts float equality on a
haversine distance.

## Run it

```bash
python run_mutation.py                        # all 974, no model needed
python run_mutation.py --split sanitized      # the 427 hand-verified problems
python run_mutation.py --split humaneval      # 164 problems, ~7 asserts each
python run_mutation.py --split humanevalplus  # the same 164, ~775 cases each
python run_model.py                           # generated solutions, needs Ollama
python run_model.py --split humanevalplus     # the same, on EvalPlus
pytest -q                                     # 32 tests, no network, no dataset needed
```

The `humanevalplus` split is the one exception to zero dependencies: 163 of its 164 suites
`import numpy`, so that split alone needs it. MBPP and HumanEval still need nothing. Its
data is committed gzipped - 11.3 MB as JSONL, 1.3 MB compressed, and `gzip` is stdlib - so
the repo still runs from a bare checkout.

Zero runtime dependencies. The dataset is a local JSONL, mutation is stdlib `ast`, and
execution is stdlib `subprocess`. Every figure in this README is recomputed by those two
scripts from `results/*.jsonl`; nothing is typed by hand.

HumanEval ships as parquet, which would need pyarrow to read. Rather than take a runtime
dependency to read 84 KB, `scripts/convert_humaneval.py` converts it once and
`data/humaneval.jsonl` is committed with its provenance; the repo still runs in a bare
checkout with nothing installed.

---

## Input

![input](docs/images/input.png)

## Output

![output](docs/images/output.png)

*Three asserts are the entire specification, and three separate one-line mutations of this
function pass all of them. Every test value is either composite with a small divisor or too
small to enter the loop, so the inverted condition reaches the same answer by the opposite
route — and the surviving mutant calls every prime above 3 composite.*

---

## Also worth reading

| | |
|---|---|
| &#128202; **[Results](docs/RESULTS.md)** | Full tables, both splits, per-kind survival, the model arm |
| &#128269; **[Method](docs/METHOD.md)** | Mutation operators, the sandbox, how a separating input is found |
| &#128190; **[Raw output](results/)** | Every mutant and its verdict, as JSONL |

Related, and reaching the same conclusion from other directions:

| | |
|---|---|
| **[code-llm-lab](https://github.com/hammasbuilds/code-llm-lab)** | Model-written test suites kill **93.4%** of these mutants against MBPP's own 85.0% |
| **[code-eval-harness](https://github.com/hammasbuilds/code-eval-harness)** | The same generations score 0% or 94% depending only on how code is extracted |
| **[swebench-localization](https://github.com/hammasbuilds/swebench-localization)** | Half of SWE-bench is a retrieval problem wearing a reasoning problem's clothes |

---

## Layout

```
src/data.py           load MBPP's two splits from the HF cache, and HumanEval from data/
src/mutate.py         single-point AST mutation: compare, binop, const, negate_if, boolop
src/sandbox.py        subprocess execution with a timeout; pass / fail / error / timeout
src/differential.py   searches for a separating input between reference and mutant
run_mutation.py       the mutation arm - no model needed
run_model.py          the generated-solutions arm - needs Ollama
tests/                32 tests, no network, no dataset, no model
results/              every mutant and verdict as JSONL, plus run logs
scripts/              one-off conversion of the HumanEval parquet to JSONL
docs/                 method and full results
```

## Stack

`Python 3.11+` &middot; `ast` (stdlib) &middot; `subprocess` (stdlib) &middot;
`urllib` (stdlib) &middot; `qwen2.5-coder:14b` via `Ollama` &middot; `pytest` &middot;
`ruff` &middot; `GitHub Actions` &middot; dataset via `Hugging Face Hub`

**Zero runtime dependencies** is a deliberate property, not an accident: a claim about a
benchmark's weakness should not itself depend on a stack of libraries a reader has to trust.

## Keywords

MBPP &middot; mutation testing &middot; differential testing &middot; test adequacy
&middot; false accepts &middot; equivalent mutants &middot; code generation benchmark
&middot; benchmark evaluation &middot; LLM evaluation &middot; pass@k &middot; test suite
quality &middot; kill rate &middot; separating input &middot; program equivalence
&middot; reproducible benchmarks &middot; qwen2.5-coder

## References

Austin, J., Odena, A., Nye, M., Bosma, M., Michalewski, H., Dohan, D., Jiang, E., Cai, C.,
Terry, M., Le, Q., & Sutton, C. **Program Synthesis with Large Language Models.** *2021.*

&#9888; Citation written from the standard reference - confirm against the paper before
relying on it.

## Licence

MIT - see [LICENSE](LICENSE).
