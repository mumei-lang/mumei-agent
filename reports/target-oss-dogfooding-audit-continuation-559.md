# Target OSS no-LLM dogfooding audit — continuation 559 (batch 560)

Run: 2026-07-23T11:57:20.251429+00:00

## Summary

- Files audited: 50
- Verified: 50
- Refuted: 0
- Unverifiable: 0

All sampled files passed no-LLM verification; no new tool-side fixes were required.

## Sample details

| repo | file | status | notes |
|------|------|--------|-------|
| go | `src/cmd/compile/internal/ssa/merge_conditional_branches_test.go` | verified | No Mumei atoms were generated from the extracted forge task spec. |
| go | `src/cmd/go/internal/modcmd/graph.go` | verified |  |
| go | `src/cmd/internal/obj/ppc64/doc.go` | verified |  |
| go | `src/cmd/link/internal/ld/util.go` | verified |  |
| go | `src/crypto/fips140/fips140.go` | verified |  |
| go | `src/crypto/internal/fips140/aes/aes_s390x.go` | verified |  |
| go | `src/encoding/json/jsontext/encode.go` | verified |  |
| go | `src/go/parser/parser.go` | verified |  |
| go | `src/html/template/clone_test.go` | verified |  |
| go | `src/html/template/transition_test.go` | verified |  |
| go | `src/internal/bytealg/index_arm64.go` | verified |  |
| go | `src/internal/fuzz/worker.go` | verified |  |
| go | `src/internal/gate/gate.go` | verified |  |
| go | `src/internal/goexperiment/exp_runtimefreegc_on.go` | verified |  |
| go | `src/internal/poll/fd_fsync_posix.go` | verified |  |
| go | `src/internal/routebsd/message_darwin_test.go` | verified |  |
| go | `src/internal/runtime/atomic/atomic_s390x.go` | verified |  |
| go | `src/internal/runtime/atomic/xchg8_test.go` | verified |  |
| go | `src/internal/trace/trace_test.go` | verified | No Mumei atoms were generated from the extracted forge task spec. |
| go | `src/net/http/httptest/server.go` | verified | No Mumei atoms were generated from the extracted forge task spec. |
| go | `src/net/http/httputil/dump_test.go` | verified | No Mumei atoms were generated from the extracted forge task spec. |
| go | `src/net/http/internal/http2/client_conn_pool.go` | verified |  |
| go | `src/net/tcpsockopt_windows.go` | verified |  |
| go | `src/os/executable_darwin.go` | verified |  |
| go | `src/os/read_test.go` | verified | No Mumei atoms were generated from the extracted forge task spec. |
| go | `src/runtime/atomic_pointer.go` | verified |  |
| go | `src/runtime/defs1_netbsd_arm.go` | verified |  |
| go | `src/runtime/select.go` | verified |  |
| go | `src/runtime/trace/example_test.go` | verified | No Mumei atoms were generated from the extracted forge task spec. |
| go | `src/runtime/write_err_android.go` | verified |  |
| go | `test/chan/select6.go` | verified |  |
| go | `test/fixedbugs/bug148.go` | verified |  |
| go | `test/fixedbugs/bug399.go` | verified |  |
| go | `test/fixedbugs/bug460.go` | verified |  |
| go | `test/fixedbugs/bug468.go` | verified |  |
| go | `test/fixedbugs/issue13777.go` | verified |  |
| go | `test/fixedbugs/issue15311.go` | verified |  |
| go | `test/fixedbugs/issue16760.go` | verified |  |
| go | `test/fixedbugs/issue19699.dir/a.go` | verified | No Mumei atoms were generated from the extracted forge task spec. |
| go | `test/fixedbugs/issue20682.dir/r.go` | verified |  |
| go | `test/fixedbugs/issue46304.go` | verified |  |
| go | `test/fixedbugs/issue46653.go` | verified |  |
| go | `test/fixedbugs/issue54467.go` | verified |  |
| go | `test/fixedbugs/issue68734.go` | verified |  |
| go | `test/fixedbugs/issue77779.go` | verified |  |
| go | `test/syntax/chan1.go` | verified |  |
| go | `test/syntax/import.go` | verified |  |
| go | `test/typeparam/factimp.dir/main.go` | verified | No Mumei atoms were generated from the extracted forge task spec. |
| go | `test/typeparam/issue49536.go` | verified |  |
| go | `test/typeparam/issue50486.dir/goerror_fp.go` | verified | No Mumei atoms were generated from the extracted forge task spec. |
