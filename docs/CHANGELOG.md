# Changelog

## 2026-09-19: A-5 suppression-helper reduction — second batch

- Removed `_go_median_guarded_indices` and `_go_sort_search_guarded_indices`: the median idiom `mid := len(arr)/2` after an empty-return guard is already covered by `_LEN_DIV` + `min_len`, and `sort.Search` result indices are covered by the ordinary `i < len(files)` condition guard (closure bodies stay out of dataflow scope).
- Two generic fact fixes in `agent/dataflow_facts.py` make `:=` symmetric with `=`: `x := len(c)`/`len(c)±k` now seeds `len_values` (previously only `_assign` recorded it), and a midpoint rule bounds `(a+b)>>k`/`(a+b)/k` when both terms are non-negative `lt_len`/`len_values` of the same container with at least one strict side — covers binary-search midpoints whose bounds don't need the loop-invariant helper.
- Kept (verified not generically replaceable): `_go_binary_search_guarded_indices` (loop-invariant `hi = m` narrowing kills `len_values` before the condition applies), `_go_enum_string_guarded_indices` / `_go_enum_string_array_guarded_indices` (`iota` enum constants are unresolved, so range-guard upper bounds can't be proved), `_go_bits_uint8_lookup_guarded_indices` (lookup tables are undeclared in the analysed source and `uint8 < 256` type upper bounds aren't modelled).
- Regression gate: `tests/test_dataflow_facts.py` (+3 pinned cases); full suite green.

## 2026-09-19: A-6 final kind — contract-derived postcondition reaching-defs

- New category `contract_output_unassigned`: identifiers referenced by a function's doc-comment `ensures:` / `@ensures` / `postcondition:` contract that are named results (`func f() (r int, err error)`) or `*T` output params are checked against a new `_Env.defined` *must-assign* fact (intersected at merges). A `return` (or named-result fall-off-end) on a path that never `=`-assigned the name reports the unestablished postcondition.
- `return <exprs>` satisfies named results positionally (Go requires full coverage), so only `*T` params are checked there; `r := …` shadows and does not establish; `*out = …` / `(*out).f = …` / `out.f = …` writes and bare `f(out)` call args (including `defer` calls and `switch`/`select` case-clause args) establish output params — `out = &x` reassignment, `f(&out)` (a `**T` write), and `go fill(out)` (no happens-before) do not.
- Regression gate: `tests/test_dataflow_facts.py` (+22 cases); full suite green. This completes the A-6 extension set (uninitialised use, guard-state call ordering, contract-derived postconditions).

## 2026-09-19: A-6 follow-up — guard-state call-ordering categories

- `agent/dataflow_facts.py` now tracks four more terminal-transition states in `_Env.held` and reports guaranteed-failure call orderings: `send_on_closed_channel` (`ch <- v` or re-`close` after `close(ch)`, including `select` send clauses and deferred `close`), `close_nil_channel` (`close` on a `var ch chan T` still nil), `use_after_close` (error-returning method calls like `Read`/`Write`/`Stat` after `x.Close()`, double `Close` included), and `unlock_of_unlocked` (`Unlock`/`RUnlock` on a mutex provably unlocked — `var mu sync.Mutex`, `sync.Mutex{}`, `new(sync.Mutex)`, or a completed `Unlock`; a successful `Unlock` always transitions to unlocked so a second call panics).
- Nil-channel sends / receives / `range` are never reported (they block rather than panic — the `select`-disable idiom); `defer close(ch)` does not mark the channel closed (only its guaranteed panic at return is flagged). `nil`-able held entries survive `x.Close()`/`x.Unlock()` so a still-nil `var f *os.File` keeps flagging later dereferences.
- Terminal-state markers propagate through `x2 := x` aliases and `x.Close()` / `close(x)` mark the whole alias cluster; `make(chan|map|slice)` / `&x` / `new(T)` / ident-alias `:=` definitions seed `nilable` type facts so a later `x = nil` re-marks even non-`var` locals.
- `defer mu.Unlock()` / `defer func(){ mu.Unlock() }()` / `go close(ch)` / `go func(){ ch <- v }()` forms are checked at registration: a deferred/goroutine `Unlock` on an unlocked mutex or `close`/send on a nil/closed channel still panics when the deferred call or goroutine runs. `*sync.Mutex` / `*sync.RWMutex` nil values use the dedicated `uninit_mutex` kind — every mutex method dereferences its receiver so nil-receiver `mu.Unlock()` panics (and a nil mutex is never recorded as locked).
- Regression gate: `tests/test_dataflow_facts.py` (+42 cases), `tests/test_foreign_code.py` / `tests/test_cross_validation.py` unchanged pass; full suite green.

## 2026-09-18: A-6 follow-up — `uninitialized_use` dataflow category

- `agent/dataflow_facts.py` now reports uses of `var`-declared nil-able values that are still uninitialised on the path: nil-pointer dereference / field / index (`*p`, `p.x`, `p[i]`), nil-slice indexing (`s[i]`; reslices `s[a:b]` excluded since `s[:0]` is legal), nil `func` calls, and nil-interface method calls / type assertions (`error`, `any`, `interface{…}`).
- Nil-able type facts live in a new `_Env.nilable` map so `p = &x` clears the marker but `p = nil`, `T(nil)` casts, and `x := p` aliases re-mark / propagate it. `p != nil` guards, nil-receiver-tolerant method calls `p.m(...)`, `len(s)` / `range s` / `append`, nil map reads, and nil channels (the `select`-disable idiom) are not reported.
- Reported via `_dataflow_safety_issues` as category `uninitialized_use`, appended after the existing bounds → nil → division → overflow ordering. Regression gate: `tests/test_dataflow_facts.py` (+17 cases), `tests/test_foreign_code.py` / `tests/test_cross_validation.py` unchanged pass.

## 2026-07-26: P16-C benchmark feedback into the vStd forge / proliferate loop

- Added `agent/benchmark_feedback.py`, which loads the mumei `mumei.benchmark_forge_feedback/v1` document emitted by `benchmarks/run_benchmarks.py --forge-feedback` and maps each benchmark category's weakness score to a negative `priority_delta` over its stdlib domains.
- Wired `--benchmark-feedback` into `forge` (bias applied before the `--max-tasks` cut, so a weak domain can win a limited budget) and `proliferate` (gap proposals ranked, spec priorities biased, provenance recorded under `benchmark_feedback` in the `--output-json` summary).
- Feedback only reorders work that gap analysis already produced; missing or malformed documents are logged and ignored. Regression gate: `uv run pytest tests/test_benchmark_feedback.py tests/test_forge.py tests/test_proliferate.py -q`.

## 2026-06-28: Multi-language audit and Forge regression hardening

- Added deterministic no-`.mm` audit regressions for Rust `a + b` overflow and `values[idx]` bounds, TypeScript `name!.length` null/undefined, and Go `values[idx]` bounds; all normalize Z3 counterexamples into `verification_violations` with the fixed seven-key audit schema and no aliases.
- Extended MCP `scan_and_fix` regressions so the audit -> migrate-suggest -> heal key order is stable across Python, Rust, TypeScript, and Go, with `next_steps` as the only human-review entrypoint.
- Continued P9 Forge with `forge_tasks/vstd_crypto_primitives.json`, generated and verified `std/crypto/primitives.mm`, and recorded the Z3-decidable proof-certificate result in `forge_log.json` without Lean escalation.
