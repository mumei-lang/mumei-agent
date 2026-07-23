# Target OSS no-LLM dogfooding audit — continuation 556 (batch 557)

Run: 2026-07-23T11:30:26.211545+00:00

## Summary

- Files audited: 50
- Verified: 50
- Refuted: 0
- Unverifiable: 0

All sampled files passed no-LLM verification; no new tool-side fixes were required.

## Sample details

| repo | file | status | notes |
|------|------|--------|-------|
| go | `src/cmd/compile/internal/gc/compile.go` | verified |  |
| go | `src/cmd/compile/internal/ssa/_gen/decOps.go` | verified |  |
| go | `src/cmd/compile/internal/test/inl_test.go` | verified | No Mumei atoms were generated from the extracted forge task spec. |
| go | `src/cmd/compile/internal/types2/typexpr.go` | verified |  |
| go | `src/cmd/go/internal/verylongtest/go_unix_test.go` | verified |  |
| go | `src/cmd/internal/cov/covcmd/cmddefs.go` | verified |  |
| go | `src/cmd/internal/cov/mreader.go` | verified |  |
| go | `src/cmd/internal/obj/arm/obj5.go` | verified |  |
| go | `src/cmd/internal/pgo/pprof.go` | verified |  |
| go | `src/cmd/link/internal/ld/deadcode.go` | verified |  |
| go | `src/cmd/link/internal/ppc64/asm.go` | verified |  |
| go | `src/compress/flate/fuzz_test.go` | verified |  |
| go | `src/crypto/internal/fips140test/cast_test.go` | verified | No Mumei atoms were generated from the extracted forge task spec. |
| go | `src/database/sql/closemu_test.go` | verified |  |
| go | `src/go/types/self_test.go` | verified | No Mumei atoms were generated from the extracted forge task spec. |
| go | `src/image/color/ycbcr.go` | verified |  |
| go | `src/image/gif/writer.go` | verified |  |
| go | `src/internal/cpu/cpu_darwin.go` | verified |  |
| go | `src/internal/runtime/cgroup/cgroup_linux.go` | verified |  |
| go | `src/internal/zstd/fuzz_test.go` | verified |  |
| go | `src/math/big/alias_test.go` | verified | No Mumei atoms were generated from the extracted forge task spec. |
| go | `src/math/rand/v2/chacha8.go` | verified |  |
| go | `src/math/rand/v2/example_test.go` | verified |  |
| go | `src/math/unsafe.go` | verified |  |
| go | `src/os/sys_wasip1.go` | verified |  |
| go | `src/runtime/defs_arm_linux.go` | verified |  |
| go | `src/runtime/sema_test.go` | verified | No Mumei atoms were generated from the extracted forge task spec. |
| go | `src/runtime/tracestack.go` | verified |  |
| go | `src/simd/simd_test.go` | verified |  |
| go | `src/syscall/syscall_darwin.go` | verified |  |
| go | `src/syscall/zsyscall_openbsd_arm64.go` | verified |  |
| go | `src/text/template/example_test.go` | verified |  |
| go | `test/chan/sieve1.go` | verified |  |
| go | `test/directive2.go` | verified |  |
| go | `test/escape_struct_param2.go` | verified |  |
| go | `test/fixedbugs/bug060.go` | verified |  |
| go | `test/fixedbugs/bug200.go` | verified |  |
| go | `test/fixedbugs/bug456.go` | verified |  |
| go | `test/fixedbugs/issue4510.dir/f2.go` | verified | No Mumei atoms were generated from the extracted forge task spec. |
| go | `test/fixedbugs/issue48536.go` | verified |  |
| go | `test/fixedbugs/issue52590.dir/b.go` | verified | No Mumei atoms were generated from the extracted forge task spec. |
| go | `test/fixedbugs/issue52862.dir/b.go` | verified | No Mumei atoms were generated from the extracted forge task spec. |
| go | `test/fixedbugs/issue6513.dir/main.go` | verified | No Mumei atoms were generated from the extracted forge task spec. |
| go | `test/func3.go` | verified |  |
| go | `test/ken/slicearray.go` | verified |  |
| go | `test/recover.go` | verified |  |
| go | `test/syntax/composite.go` | verified |  |
| go | `test/tighten.go` | verified |  |
| go | `test/undef.go` | verified |  |
| go | `test/writebarrier.go` | verified |  |
