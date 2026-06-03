# vStd Phase 4 validation checkpoint

Validated on 2026-06-03 against `mumei-lang/mumei@develop` (`d1adfe1`) and this repository's `forge_log.json`.

## Forge log coverage

All Phase 4 checkpoint tasks are present in `forge_log.json`, have `status: "success"`, have `error: null`, and target the expected stdlib module.

| Task | Target | Atoms recorded | Result |
|------|--------|---------------:|--------|
| `vstd-aviation-control` | `std/concurrency/aviation.mm` | 1 | pass |
| `vstd-container-sorted-map` | `std/container/sorted_map.mm` | 3 | pass |
| `vstd-math-factorial` | `std/math/factorial.mm` | 2 | pass |
| `vstd-math-fibonacci` | `std/math/fibonacci.mm` | 2 | pass |
| `vstd-string-validator` | `std/string/validator.mm` | 2 | pass |

`vstd-math-fibonacci` retains the existing target module after the generation-health gate, matching the note in `forge_log.json`.

## Proof-certificate evidence

Proof certificates were generated outside the repository under `/home/ubuntu/mumei-forge-stdlib-evidence` with:

```bash
MUMEI_STD_PATH=/home/ubuntu/repos/mumei/std \
LLVM_SYS_170_PREFIX=/usr/lib/llvm-17 \
LIBCLANG_PATH=/usr/lib/x86_64-linux-gnu \
  /home/ubuntu/repos/mumei/target/debug/mumei verify --proof-cert \
  --output /home/ubuntu/mumei-forge-stdlib-evidence/<module>.proof.json \
  /home/ubuntu/repos/mumei/std/<module>.mm
```

| Module | Certificate hash | `all_verified` |
|--------|------------------|----------------|
| `std/concurrency/aviation.mm` | `25e5ec165248c5e68fc3275544ef3fed69e06c9f1b80fb48005bc7c7a30ca9e7` | true |
| `std/container/sorted_map.mm` | `6dd293dd5a8f3e9ffba0ea31f07450605f2f991c8febdb72270844114ef97284` | true |
| `std/math/factorial.mm` | `9466f6950076bd231b1fb0a47caa182e568444eef1814ca2da35ea7fcd60d14e` | true |
| `std/math/fibonacci.mm` | `d027d4d473eb4538947d1c9419fb021aeeac3ba3f4531f7faec43717396f8ed4` | true |
| `std/string/validator.mm` | `e6da836c73c3c473527f330c52b41f343c70bf9a5aec69446778690bb28708af` | true |

The full stdlib regression also passed:

```text
STD_VERIFY_FAILURES=0
```

## Roadmap gap conversion

`python -m agent analyze-std-gaps --std-dir ../mumei/std --forge-tasks-dir forge_tasks` reports:

| Metric | Value |
|--------|------:|
| Roadmap items | 16 |
| Forge task specs | 16 |
| Forge task conversion rate | 1.000 |
| Existing std modules | 14 |
| Verification target rate | 0.875 |
| Missing forge tasks | 0 |

No remaining roadmap gaps require a new `forge_tasks/vstd_*.json` file at this checkpoint.

## Benchmark recommendation

The benchmark history currently records `qwen3.5:4b` as the best local model (`0.857` latest generation success rate). The proliferate workflow still supports explicit `llm_model` overrides; for unattended local runs, `scripts/select_benchmark_model.py --profile ollama-local` should prefer the highest success rate in `docs/BENCHMARK_HISTORY.md`, then lower runtime, then shorter generated code.
