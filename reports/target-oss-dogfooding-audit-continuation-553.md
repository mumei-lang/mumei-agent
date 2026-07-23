# Target OSS no-LLM dogfooding audit — continuation 553 (batch 554)

Run: 2026-07-23T11:17:25.179312+00:00

## Summary

- Files audited: 50
- Verified: 50
- Refuted: 0
- Unverifiable: 0

All sampled files passed no-LLM verification; no new tool-side fixes were required.

## Sample details

| repo | file | status | notes |
|------|------|--------|-------|
| go | `src/bufio/export_test.go` | verified |  |
| go | `src/cmd/cgo/internal/test/issue8756.go` | verified |  |
| go | `src/cmd/compile/internal/inline/interleaved/interleaved.go` | verified |  |
| go | `src/cmd/compile/internal/ssa/_gen/divmodOps.go` | verified |  |
| go | `src/cmd/compile/internal/test/global_test.go` | verified |  |
| go | `src/cmd/compile/internal/test/locals_test.go` | verified |  |
| go | `src/cmd/go/internal/doc/pkgsite_bootstrap.go` | verified |  |
| go | `src/cmd/go/internal/gover/mod_test.go` | verified |  |
| go | `src/cmd/internal/obj/arm/anames.go` | verified |  |
| go | `src/crypto/internal/cryptotest/x509limbo/schemaversion.go` | verified |  |
| go | `src/crypto/internal/fips140/nistec/fiat/p521.go` | verified |  |
| go | `src/crypto/internal/fips140/sha3/sha3_noasm.go` | verified |  |
| go | `src/debug/dwarf/line.go` | verified |  |
| go | `src/encoding/csv/writer.go` | verified |  |
| go | `src/internal/chacha8rand/export_test.go` | verified |  |
| go | `src/internal/nettest/packetconn.go` | verified |  |
| go | `src/internal/poll/fd.go` | verified |  |
| go | `src/internal/reflectlite/export_test.go` | verified |  |
| go | `src/internal/syscall/windows/exec_windows_test.go` | verified |  |
| go | `src/net/example_test.go` | verified |  |
| go | `src/net/main_unix_test.go` | verified |  |
| go | `src/net/protoconn_test.go` | verified |  |
| go | `src/net/rpc/debug.go` | verified |  |
| go | `src/os/timeout_windows_test.go` | verified |  |
| go | `src/runtime/export_unix_test.go` | verified |  |
| go | `src/runtime/tracemap.go` | verified |  |
| go | `src/runtime/type.go` | verified |  |
| go | `src/sort/gen_sort_variants.go` | verified |  |
| go | `src/strings/export_test.go` | verified |  |
| go | `src/syscall/zerrors_linux_mips64.go` | verified |  |
| go | `src/unique/canonmap_test.go` | verified |  |
| go | `test/codegen/regabi_regalloc.go` | verified |  |
| go | `test/fixedbugs/bug207.go` | verified |  |
| go | `test/fixedbugs/bug341.go` | verified |  |
| go | `test/fixedbugs/bug377.dir/two.go` | verified |  |
| go | `test/fixedbugs/issue19548.go` | verified |  |
| go | `test/fixedbugs/issue20097.go` | verified |  |
| go | `test/fixedbugs/issue21988.go` | verified |  |
| go | `test/fixedbugs/issue25727.go` | verified |  |
| go | `test/fixedbugs/issue30722.go` | verified |  |
| go | `test/fixedbugs/issue37513.dir/main.go` | verified |  |
| go | `test/fixedbugs/issue43762.go` | verified |  |
| go | `test/fixedbugs/issue52072.go` | verified |  |
| go | `test/fixedbugs/issue57184.go` | verified |  |
| go | `test/fixedbugs/issue7272.go` | verified |  |
| go | `test/fuse.go` | verified |  |
| go | `test/interface/embed.go` | verified |  |
| go | `test/method7.go` | verified |  |
| go | `test/sieve.go` | verified |  |
| go | `test/typeparam/issue51832.go` | verified |  |
