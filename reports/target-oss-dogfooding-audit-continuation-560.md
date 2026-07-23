# Target OSS no-LLM dogfooding audit — continuation 560 (batch 561)

Run: 2026-07-23T12:11:51.819439+00:00

## Summary

- Files audited: 50
- Verified: 50
- Refuted: 0
- Unverifiable: 0

All sampled files passed no-LLM verification; no new tool-side fixes were required.

## Sample details

| repo | file | status | notes |
|------|------|--------|-------|
| go | `src/cmd/cgo/internal/test/issue52611b/a.go` | verified |  |
| go | `src/cmd/compile/internal/base/bootstrap_false.go` | verified |  |
| go | `src/cmd/compile/internal/ssa/id.go` | verified |  |
| go | `src/cmd/compile/internal/types2/lookup.go` | verified |  |
| go | `src/cmd/internal/src/pos.go` | verified |  |
| go | `src/cmd/link/internal/x86/l.go` | verified |  |
| go | `src/crypto/internal/fips140/mldsa/semiexpanded.go` | verified |  |
| go | `src/crypto/md5/gen.go` | verified | No Mumei atoms were generated from the extracted forge task spec. |
| go | `src/crypto/rsa/example_test.go` | verified |  |
| go | `src/internal/abi/escape.go` | verified |  |
| go | `src/internal/goexperiment/exp_runtimesecret_off.go` | verified |  |
| go | `src/internal/poll/error_linux_test.go` | verified | No Mumei atoms were generated from the extracted forge task spec. |
| go | `src/internal/runtime/gc/scan/scan_test.go` | verified | No Mumei atoms were generated from the extracted forge task spec. |
| go | `src/internal/syscall/unix/faccessat_bsd.go` | verified |  |
| go | `src/internal/syscall/unix/kernel_version_ge_test.go` | verified |  |
| go | `src/internal/syscall/unix/siginfo_linux_test.go` | verified |  |
| go | `src/internal/testenv/exec.go` | verified | No Mumei atoms were generated from the extracted forge task spec. |
| go | `src/internal/trace/order_test.go` | verified |  |
| go | `src/internal/trace/reader.go` | verified |  |
| go | `src/internal/xcoff/file_test.go` | verified |  |
| go | `src/math/log10.go` | verified |  |
| go | `src/net/http/transport_dial_test.go` | verified | No Mumei atoms were generated from the extracted forge task spec. |
| go | `src/os/user/lookup.go` | verified |  |
| go | `src/reflect/type.go` | verified |  |
| go | `src/runtime/defs_aix.go` | verified |  |
| go | `src/runtime/msize.go` | verified |  |
| go | `src/syscall/syscall_freebsd_riscv64.go` | verified |  |
| go | `test/abi/fuzz_trailing_zero_field.go` | verified |  |
| go | `test/codegen/issue60673.go` | verified |  |
| go | `test/fixedbugs/bug190.go` | verified |  |
| go | `test/fixedbugs/bug298.go` | verified |  |
| go | `test/fixedbugs/bug459.go` | verified |  |
| go | `test/fixedbugs/issue11326b.go` | verified |  |
| go | `test/fixedbugs/issue26105.go` | verified |  |
| go | `test/fixedbugs/issue29735.go` | verified |  |
| go | `test/fixedbugs/issue4396b.go` | verified |  |
| go | `test/fixedbugs/issue46903.go` | verified |  |
| go | `test/fixedbugs/issue48898.go` | verified |  |
| go | `test/fixedbugs/issue49378.go` | verified |  |
| go | `test/fixedbugs/issue7547.go` | verified |  |
| go | `test/fixedbugs/notinheap3.go` | verified |  |
| go | `test/inline_callers.go` | verified |  |
| go | `test/interface/bigdata.go` | verified |  |
| go | `test/ken/rob2.go` | verified |  |
| go | `test/literal.go` | verified |  |
| go | `test/recover5.go` | verified |  |
| go | `test/simd_inline.go` | verified |  |
| go | `test/typeparam/issue48047.go` | verified |  |
| go | `test/typeparam/issue50841.dir/a.go` | verified | No Mumei atoms were generated from the extracted forge task spec. |
| go | `test/typeparam/issue54535.go` | verified |  |
