# Target OSS no-LLM dogfooding audit — continuation 554 (batch 555)

Run: 2026-07-23T11:26:24.067310+00:00

## Summary

- Files audited: 50
- Verified: 50
- Refuted: 0
- Unverifiable: 0

All sampled files passed no-LLM verification; no new tool-side fixes were required.

## Sample details

| repo | file | status | notes |
|------|------|--------|-------|
| go | `src/bytes/bytes_test.go` | verified | No Mumei atoms were generated from the extracted forge task spec. |
| go | `src/cmd/compile/internal/escape/escape.go` | verified |  |
| go | `src/cmd/compile/internal/ir/mknode.go` | verified | No Mumei atoms were generated from the extracted forge task spec. |
| go | `src/cmd/compile/internal/ssa/_gen/386Ops.go` | verified |  |
| go | `src/cmd/compile/internal/ssa/likelyadjust.go` | verified |  |
| go | `src/cmd/compile/internal/types2/lookup_test.go` | verified |  |
| go | `src/cmd/link/internal/ld/heap_test.go` | verified | No Mumei atoms were generated from the extracted forge task spec. |
| go | `src/crypto/cipher/cbc.go` | verified |  |
| go | `src/crypto/dsa/dsa.go` | verified |  |
| go | `src/crypto/internal/fips140/aes/gcm/gcm_ppc64x.go` | verified |  |
| go | `src/crypto/internal/fips140/rsa/pkcs1v15.go` | verified |  |
| go | `src/encoding/json/v2_options.go` | verified |  |
| go | `src/go/doc/comment/print.go` | verified |  |
| go | `src/go/types/objset.go` | verified |  |
| go | `src/io/pipe_test.go` | verified | No Mumei atoms were generated from the extracted forge task spec. |
| go | `src/math/cmplx/log.go` | verified |  |
| go | `src/math/signbit.go` | verified |  |
| go | `src/mime/multipart/writer.go` | verified |  |
| go | `src/net/conf_test.go` | verified | No Mumei atoms were generated from the extracted forge task spec. |
| go | `src/net/error_unix.go` | verified |  |
| go | `src/net/http/roundtrip.go` | verified |  |
| go | `src/os/user/cgo_lookup_unix_test.go` | verified |  |
| go | `src/runtime/list_manual_test.go` | verified | No Mumei atoms were generated from the extracted forge task spec. |
| go | `src/simd/archsimd/_gen/simdgen/arch.go` | verified |  |
| go | `src/simd/archsimd/ops_internal_amd64.go` | verified |  |
| go | `src/slices/iter_test.go` | verified | No Mumei atoms were generated from the extracted forge task spec. |
| go | `src/syscall/env_unix_test.go` | verified | No Mumei atoms were generated from the extracted forge task spec. |
| go | `src/syscall/flock_bsd.go` | verified |  |
| go | `src/unicode/tables.go` | verified |  |
| go | `test/fixedbugs/bug094.go` | verified |  |
| go | `test/fixedbugs/bug130.go` | verified |  |
| go | `test/fixedbugs/bug133.dir/bug0.go` | verified |  |
| go | `test/fixedbugs/bug309.go` | verified |  |
| go | `test/fixedbugs/bug347.go` | verified |  |
| go | `test/fixedbugs/bug361.go` | verified |  |
| go | `test/fixedbugs/bug484.go` | verified |  |
| go | `test/fixedbugs/issue15646.go` | verified |  |
| go | `test/fixedbugs/issue20232.go` | verified |  |
| go | `test/fixedbugs/issue30679.go` | verified |  |
| go | `test/fixedbugs/issue33158.dir/b.go` | verified | No Mumei atoms were generated from the extracted forge task spec. |
| go | `test/fixedbugs/issue42401.go` | verified |  |
| go | `test/fixedbugs/issue51101.go` | verified |  |
| go | `test/fixedbugs/issue56105.go` | verified |  |
| go | `test/fixedbugs/issue66066.go` | verified |  |
| go | `test/fixedbugs/issue66066b.go` | verified |  |
| go | `test/fixedbugs/issue75063.go` | verified |  |
| go | `test/fixedbugs/issue77919.go` | verified |  |
| go | `test/fixedbugs/walk_bounded_overshift_empty_bound.go` | verified |  |
| go | `test/typeparam/issue47684c.go` | verified |  |
| go | `test/typeparam/issue47892.dir/main.go` | verified | No Mumei atoms were generated from the extracted forge task spec. |
