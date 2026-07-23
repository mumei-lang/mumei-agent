# Target OSS no-LLM dogfooding audit — continuation 555 (batch 556)

Run: 2026-07-23T11:28:18.327312+00:00

## Summary

- Files audited: 50
- Verified: 50
- Refuted: 0
- Unverifiable: 0

All sampled files passed no-LLM verification; no new tool-side fixes were required.

## Sample details

| repo | file | status | notes |
|------|------|--------|-------|
| go | `src/cmd/cgo/internal/test/callback_windows.go` | verified | No Mumei atoms were generated from the extracted forge task spec. |
| go | `src/cmd/internal/obj/arm64/sysRegEnc.go` | verified |  |
| go | `src/cmd/internal/obj/ppc64/anames.go` | verified |  |
| go | `src/cmd/internal/telemetry/telemetry_bootstrap.go` | verified |  |
| go | `src/cmd/link/internal/ppc64/obj.go` | verified |  |
| go | `src/cmd/link/internal/s390x/l.go` | verified |  |
| go | `src/crypto/hkdf/hkdf.go` | verified |  |
| go | `src/crypto/internal/fips140/alias/alias.go` | verified |  |
| go | `src/crypto/internal/fips140/bigmod/_asm/nat_amd64_asm.go` | verified |  |
| go | `src/crypto/internal/fips140/edwards25519/tables.go` | verified |  |
| go | `src/crypto/internal/fips140/sha256/_asm/sha256block_amd64_shani.go` | verified |  |
| go | `src/crypto/internal/fips140deps/time/time.go` | verified |  |
| go | `src/go/format/internal.go` | verified |  |
| go | `src/go/types/check.go` | verified |  |
| go | `src/go/types/errorcalls_test.go` | verified | No Mumei atoms were generated from the extracted forge task spec. |
| go | `src/go/types/type.go` | verified |  |
| go | `src/internal/cpu/cpu_arm64_linux.go` | verified |  |
| go | `src/internal/runtime/gc/malloc.go` | verified |  |
| go | `src/internal/runtime/maps/runtime_alg.go` | verified |  |
| go | `src/net/dnsclient_unix.go` | verified |  |
| go | `src/net/sock_cloexec_solaris.go` | verified |  |
| go | `src/net/sockopt_fake.go` | verified |  |
| go | `src/net/sockoptip4_posix_nonlinux.go` | verified |  |
| go | `src/os/zero_copy_posix.go` | verified |  |
| go | `src/runtime/defs_netbsd_386.go` | verified |  |
| go | `src/runtime/memmove_test.go` | verified | No Mumei atoms were generated from the extracted forge task spec. |
| go | `src/runtime/os_aix.go` | verified |  |
| go | `src/runtime/tracestring.go` | verified |  |
| go | `src/syscall/zsysnum_linux_arm64.go` | verified |  |
| go | `src/syscall/zsysnum_plan9.go` | verified |  |
| go | `src/time/zoneinfo_android_test.go` | verified |  |
| go | `test/abi/return_stuff.go` | verified |  |
| go | `test/fixedbugs/bug234.go` | verified |  |
| go | `test/fixedbugs/bug414.dir/p1.go` | verified | No Mumei atoms were generated from the extracted forge task spec. |
| go | `test/fixedbugs/issue16193.go` | verified |  |
| go | `test/fixedbugs/issue16369.go` | verified |  |
| go | `test/fixedbugs/issue25984.go` | verified |  |
| go | `test/fixedbugs/issue34968.go` | verified |  |
| go | `test/fixedbugs/issue44325.dir/a.go` | verified | No Mumei atoms were generated from the extracted forge task spec. |
| go | `test/fixedbugs/issue46386.go` | verified |  |
| go | `test/fixedbugs/issue59378.go` | verified |  |
| go | `test/fixedbugs/issue66585.go` | verified |  |
| go | `test/fixedbugs/issue68054.go` | verified |  |
| go | `test/interface/embed1.go` | verified |  |
| go | `test/linkobj.go` | verified |  |
| go | `test/syntax/semi4.go` | verified |  |
| go | `test/typeparam/issue42758.go` | verified |  |
| go | `test/typeparam/issue49497.dir/a.go` | verified | No Mumei atoms were generated from the extracted forge task spec. |
| go | `test/typeparam/issue49538.go` | verified |  |
| go | `test/typeparam/listimp.go` | verified |  |
