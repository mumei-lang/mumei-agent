# Target OSS no-LLM dogfooding audit — continuation 561 (batch 562)

Run: 2026-07-23T12:12:58.395358+00:00

## Summary

- Files audited: 28
- Verified: 28
- Refuted: 0
- Unverifiable: 0

All sampled files passed no-LLM verification; no new tool-side fixes were required.

## Sample details

| repo | file | status | notes |
|------|------|--------|-------|
| go | `src/cmd/compile/internal/ir/reassign_consistency_check.go` | verified |  |
| go | `src/cmd/compile/internal/test/issue53888_test.go` | verified |  |
| go | `src/internal/fuzz/queue.go` | verified |  |
| go | `src/internal/poll/fd_io_plan9.go` | verified |  |
| go | `src/internal/runtime/exithook/hooks.go` | verified |  |
| go | `src/math/rand/v2/exp.go` | verified |  |
| go | `src/net/netgo_off.go` | verified |  |
| go | `src/os/error_plan9.go` | verified |  |
| go | `src/os/signal/signal_plan9.go` | verified |  |
| go | `src/os/stat_linux.go` | verified |  |
| go | `src/runtime/defs_openbsd_riscv64.go` | verified |  |
| go | `src/runtime/fipsbypass.go` | verified |  |
| go | `src/sync/runtime_sema_test.go` | verified | No Mumei atoms were generated from the extracted forge task spec. |
| go | `src/syscall/zerrors_netbsd_amd64.go` | verified |  |
| go | `test/codegen/constants.go` | verified |  |
| go | `test/convinline.go` | verified |  |
| go | `test/fixedbugs/bug046.go` | verified |  |
| go | `test/fixedbugs/bug292.go` | verified |  |
| go | `test/fixedbugs/bug338.go` | verified |  |
| go | `test/fixedbugs/issue31959.dir/main.go` | verified |  |
| go | `test/fixedbugs/issue7944.go` | verified |  |
| go | `test/fixedbugs/issue9634.go` | verified |  |
| go | `test/func6.go` | verified |  |
| go | `test/rune.go` | verified |  |
| go | `test/typeparam/issue47924.go` | verified |  |
| go | `test/typeparam/issue50833.go` | verified |  |
| go | `test/typeparam/issue51925.go` | verified |  |
| go | `test/typeparam/mutualimp.dir/a.go` | verified | No Mumei atoms were generated from the extracted forge task spec. |
