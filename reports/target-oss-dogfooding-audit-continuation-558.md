# Target OSS no-LLM dogfooding audit — continuation 558 (batch 559)

Run: 2026-07-23T11:46:53.359387+00:00

## Summary

- Files audited: 50
- Verified: 50
- Refuted: 0
- Unverifiable: 0

All sampled files passed no-LLM verification; no new tool-side fixes were required.

## Sample details

| repo | file | status | notes |
|------|------|--------|-------|
| go | `src/cmd/cgo/internal/test/cgo_test.go` | verified |  |
| go | `src/cmd/cgo/internal/test/issue30527.go` | verified |  |
| go | `src/cmd/compile/internal/syntax/nodes.go` | verified |  |
| go | `src/cmd/compile/internal/types2/infer.go` | verified |  |
| go | `src/cmd/go/go_windows_test.go` | verified |  |
| go | `src/cmd/go/internal/mvs/errors.go` | verified |  |
| go | `src/cmd/go/internal/str/str_test.go` | verified |  |
| go | `src/cmd/link/internal/sym/compilation_unit.go` | verified |  |
| go | `src/crypto/x509/root_windows.go` | verified |  |
| go | `src/encoding/json/jsontext/errors.go` | verified |  |
| go | `src/go/types/assignments.go` | verified |  |
| go | `src/internal/syscall/unix/siginfo_linux_other.go` | verified |  |
| go | `src/internal/trace/order.go` | verified |  |
| go | `src/log/slog/slogtest_test.go` | verified | No Mumei atoms were generated from the extracted forge task spec. |
| go | `src/math/big/example_test.go` | verified |  |
| go | `src/mime/type_openbsd.go` | verified |  |
| go | `src/net/http/servemux121.go` | verified |  |
| go | `src/net/interface_freebsd.go` | verified |  |
| go | `src/net/sendfile_stub.go` | verified |  |
| go | `src/os/example_windows_test.go` | verified | No Mumei atoms were generated from the extracted forge task spec. |
| go | `src/os/exec/exec_unix.go` | verified |  |
| go | `src/runtime/pprof/protomem.go` | verified |  |
| go | `src/runtime/proc.go` | verified |  |
| go | `src/syscall/types_windows_amd64.go` | verified |  |
| go | `src/syscall/ztypes_linux_mips64le.go` | verified |  |
| go | `src/time/sys_windows.go` | verified |  |
| go | `test/bounds.go` | verified |  |
| go | `test/closure.go` | verified |  |
| go | `test/declbad.go` | verified |  |
| go | `test/dwarf/dwarf.dir/z20.go` | verified | No Mumei atoms were generated from the extracted forge task spec. |
| go | `test/fixedbugs/issue15002.go` | verified |  |
| go | `test/fixedbugs/issue15252.go` | verified |  |
| go | `test/fixedbugs/issue15548.dir/c.go` | verified |  |
| go | `test/fixedbugs/issue17588.go` | verified |  |
| go | `test/fixedbugs/issue26438.go` | verified |  |
| go | `test/fixedbugs/issue29013a.go` | verified |  |
| go | `test/fixedbugs/issue42401.dir/b.go` | verified | No Mumei atoms were generated from the extracted forge task spec. |
| go | `test/fixedbugs/issue48088.go` | verified |  |
| go | `test/fixedbugs/issue52535.go` | verified |  |
| go | `test/fixedbugs/issue59709.dir/cmem.go` | verified | No Mumei atoms were generated from the extracted forge task spec. |
| go | `test/fixedbugs/issue7525d.go` | verified |  |
| go | `test/fixedbugs/issue7648.dir/a.go` | verified |  |
| go | `test/inline_big.go` | verified |  |
| go | `test/ken/simpfun.go` | verified |  |
| go | `test/reflectmethod7.go` | verified |  |
| go | `test/switch5.go` | verified |  |
| go | `test/typeparam/aliasimp.dir/a.go` | verified |  |
| go | `test/typeparam/issue50481b.dir/main.go` | verified | No Mumei atoms were generated from the extracted forge task spec. |
| go | `test/typeparam/mapsimp.dir/main.go` | verified | No Mumei atoms were generated from the extracted forge task spec. |
| go | `test/typeswitch1.go` | verified |  |
