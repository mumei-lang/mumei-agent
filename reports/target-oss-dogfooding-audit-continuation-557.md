# Target OSS no-LLM dogfooding audit — continuation 557 (batch 558)

Run: 2026-07-23T11:32:36.720041+00:00

## Summary

- Files audited: 50
- Verified: 50
- Refuted: 0
- Unverifiable: 0

All sampled files passed no-LLM verification; no new tool-side fixes were required.

## Sample details

| repo | file | status | notes |
|------|------|--------|-------|
| go | `src/cmd/asm/internal/arch/ppc64.go` | verified |  |
| go | `src/cmd/cgo/internal/test/issue24161res/restype.go` | verified |  |
| go | `src/cmd/compile/internal/test/memoverlap_test.go` | verified | No Mumei atoms were generated from the extracted forge task spec. |
| go | `src/cmd/go/internal/doc/dirs.go` | verified |  |
| go | `src/cmd/go/internal/generate/generate_test.go` | verified |  |
| go | `src/cmd/go/internal/modget/query.go` | verified |  |
| go | `src/crypto/cipher/gcm_wycheproof_test.go` | verified |  |
| go | `src/crypto/internal/cryptotest/fips140.go` | verified | No Mumei atoms were generated from the extracted forge task spec. |
| go | `src/crypto/internal/fips140/sha256/sha256block_arm64.go` | verified |  |
| go | `src/crypto/internal/fips140test/nistec_ordinv_test.go` | verified | No Mumei atoms were generated from the extracted forge task spec. |
| go | `src/crypto/internal/randutil/randutil.go` | verified |  |
| go | `src/crypto/tls/link_test.go` | verified |  |
| go | `src/debug/buildinfo/buildinfo.go` | verified |  |
| go | `src/go/types/generate.go` | verified |  |
| go | `src/go/types/stdlib_test.go` | verified | No Mumei atoms were generated from the extracted forge task spec. |
| go | `src/internal/trace/internal/tracev1/order.go` | verified |  |
| go | `src/math/big/internal/asmgen/mips64.go` | verified |  |
| go | `src/net/internal/cgotest/resstate.go` | verified |  |
| go | `src/net/tcpsock_windows.go` | verified |  |
| go | `src/os/example_other_test.go` | verified | No Mumei atoms were generated from the extracted forge task spec. |
| go | `src/os/user/lookup_windows.go` | verified |  |
| go | `src/path/path_test.go` | verified |  |
| go | `src/reflect/type_test.go` | verified |  |
| go | `src/regexp/syntax/parse_test.go` | verified | No Mumei atoms were generated from the extracted forge task spec. |
| go | `src/runtime/debug/example_monitor_test.go` | verified | No Mumei atoms were generated from the extracted forge task spec. |
| go | `src/runtime/mpagealloc_test.go` | verified | No Mumei atoms were generated from the extracted forge task spec. |
| go | `src/runtime/os_freebsd_arm.go` | verified |  |
| go | `src/runtime/os_plan9.go` | verified |  |
| go | `src/runtime/signal_linux_mips64x.go` | verified |  |
| go | `src/runtime/sys_s390x.go` | verified |  |
| go | `test/64bit.go` | verified |  |
| go | `test/dwarf/dwarf.dir/z13.go` | verified | No Mumei atoms were generated from the extracted forge task spec. |
| go | `test/escape_struct_return.go` | verified |  |
| go | `test/fixedbugs/bug446.go` | verified |  |
| go | `test/fixedbugs/bug503.go` | verified |  |
| go | `test/fixedbugs/gcc61204.go` | verified |  |
| go | `test/fixedbugs/issue14729.go` | verified |  |
| go | `test/fixedbugs/issue18911.dir/a.go` | verified |  |
| go | `test/fixedbugs/issue26024.go` | verified |  |
| go | `test/fixedbugs/issue37837.dir/a.go` | verified | No Mumei atoms were generated from the extracted forge task spec. |
| go | `test/fixedbugs/issue49100.go` | verified |  |
| go | `test/fixedbugs/issue70189.go` | verified |  |
| go | `test/fixedbugs/issue7153.go` | verified |  |
| go | `test/fixedbugs/issue7214.go` | verified |  |
| go | `test/fixedbugs/issue73200.go` | verified | No Mumei atoms were generated from the extracted forge task spec. |
| go | `test/fixedbugs/issue7525.go` | verified |  |
| go | `test/fixedbugs/issue8004.go` | verified |  |
| go | `test/makemap.go` | verified |  |
| go | `test/turing.go` | verified |  |
| go | `test/typeparam/issue53477.go` | verified |  |
