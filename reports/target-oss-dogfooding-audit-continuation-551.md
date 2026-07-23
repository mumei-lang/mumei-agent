# Target OSS no-LLM dogfooding audit — continuation 551 (batch 552)

Run: 2026-07-23T11:09:42.747384+00:00

## Summary

- Files audited: 50
- Verified: 50
- Refuted: 0
- Unverifiable: 0

All sampled files passed no-LLM verification; no new tool-side fixes were required.

## Sample details

| repo | file | status | notes |
|------|------|--------|-------|
| go | `src/cmd/cgo/internal/test/issue24161_darwin_test.go` | verified |  |
| go | `src/cmd/compile/internal/escape/leaks.go` | verified |  |
| go | `src/cmd/compile/internal/importer/support.go` | verified |  |
| go | `src/cmd/compile/internal/inline/inlheur/tserial_test.go` | verified |  |
| go | `src/cmd/compile/internal/noder/export.go` | verified |  |
| go | `src/cmd/compile/internal/ssa/deadstore.go` | verified |  |
| go | `src/cmd/go/internal/search/search.go` | verified |  |
| go | `src/cmd/internal/edit/edit.go` | verified |  |
| go | `src/cmd/internal/quoted/quoted_test.go` | verified |  |
| go | `src/compress/zlib/reader.go` | verified |  |
| go | `src/crypto/mlkem/mlkem.go` | verified |  |
| go | `src/crypto/tls/certificates_generator_test.go` | verified |  |
| go | `src/debug/elf/reader.go` | verified |  |
| go | `src/go/types/api_test.go` | verified |  |
| go | `src/html/template/exec_test.go` | verified |  |
| go | `src/html/template/js_test.go` | verified |  |
| go | `src/internal/reflectlite/tostring_test.go` | verified |  |
| go | `src/math/bits/bits_errors.go` | verified |  |
| go | `src/math/rand/zipf.go` | verified |  |
| go | `src/net/http/cookiejar/punycode_test.go` | verified |  |
| go | `src/net/http/internal/http2/gotrack.go` | verified |  |
| go | `src/net/rpc/client_test.go` | verified |  |
| go | `src/os/file_windows.go` | verified |  |
| go | `src/os/user/lookup_unix_test.go` | verified |  |
| go | `src/runtime/closure_test.go` | verified |  |
| go | `src/runtime/importx_test.go` | verified |  |
| go | `src/runtime/nbpipe_pipe.go` | verified |  |
| go | `src/runtime/race/sched_test.go` | verified |  |
| go | `src/time/tzdata_test.go` | verified |  |
| go | `src/weak/pointer.go` | verified |  |
| go | `test/codegen/addrcalc.go` | verified |  |
| go | `test/codegen/mapaccess.go` | verified |  |
| go | `test/fixedbugs/bug021.go` | verified |  |
| go | `test/fixedbugs/issue11286.go` | verified |  |
| go | `test/fixedbugs/issue12577.go` | verified |  |
| go | `test/fixedbugs/issue14988.go` | verified |  |
| go | `test/fixedbugs/issue27695b.go` | verified |  |
| go | `test/fixedbugs/issue32347.go` | verified |  |
| go | `test/fixedbugs/issue44370.dir/a.go` | verified |  |
| go | `test/fixedbugs/issue5162.go` | verified |  |
| go | `test/fixedbugs/issue58341.go` | verified |  |
| go | `test/fixedbugs/issue65808.go` | verified |  |
| go | `test/fixedbugs/issue65962.go` | verified |  |
| go | `test/fixedbugs/issue78303_1.go` | verified |  |
| go | `test/fixedbugs/issue9076.go` | verified |  |
| go | `test/linkx_run.go` | verified |  |
| go | `test/typeparam/gencrawler.dir/a.go` | verified |  |
| go | `test/typeparam/issue49027.go` | verified |  |
| go | `test/typeparam/min.go` | verified |  |
| go | `test/zerodivide.go` | verified |  |
