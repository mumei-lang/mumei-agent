# External verifier pilot: Z3 CLI

Candidate: Z3 CLI, exercised only as an external process through the C11 verifier-adapter schedule.

Assessment summary:

| criterion | pilot result |
|---|---|
| license | MIT; redistribution/CI use is compatible in principle |
| maintenance | actively maintained upstream; local version must be pinned explicitly |
| CI/toolchain | available as a binary, but not guaranteed on every host; absence must stay fail-closed |
| runtime cost | subprocess startup and solver runtime; bounded by host timeout and memory policy |
| independence | weak for Mumei assurance because Core already uses Z3; useful as an execution-boundary pilot, not as independent semantic evidence |
| verdict trust | stdout markers are adapter self-reports only; they are not Evidence acceptance |

The regression pilot in `tests/test_fixture_adapter_schedule.py` uses the narrow `smtlib2.unsat/v1` profile with `(assert false)` input. It verifies host-controlled argv dispatch, stdin feeding, timeout/memory metadata, exit-code selection and marker normalization. It intentionally does not promote the result to proof, Evidence acceptance or grade.

Adoption recommendation: keep Z3 CLI as a non-promotable pilot only. Do not count it as an independent verifier because it shares the same solver family as Mumei Core. A future candidate with independent semantics or proof certificates should supersede it.
