# Target OSS no-LLM dogfooding audit — continuation 526 (batch 527)

Run: 2026-07-23T08:20:18.891334+00:00

## Summary

- Files audited: 50
- Verified: 50
- Refuted: 0
- Unverifiable: 0

All sampled files passed no-LLM verification; no new tool-side fixes were required.

## Sample details

| repo | file | status | notes |
|------|------|--------|-------|
| go | `src/cmd/compile/internal/s390x/ssa.go` | verified |  |
| go | `src/cmd/compile/internal/ssa/generate_test.go` | verified |  |
| go | `src/cmd/internal/obj/ppc64/asm9_gtables.go` | verified |  |
| go | `src/compress/flate/level3.go` | verified |  |
| go | `src/compress/zlib/writer_test.go` | verified |  |
| go | `src/crypto/internal/fips140/ecdsa/ecdsa_test.go` | verified |  |
| go | `src/encoding/asn1/asn1.go` | verified |  |
| go | `src/errors/join.go` | verified |  |
| go | `src/image/color/color.go` | verified |  |
| go | `src/internal/goexperiment/exp_heapminimum512kib_on.go` | verified |  |
| go | `src/internal/syscall/unix/nofollow_posix.go` | verified |  |
| go | `src/math/exp2_noasm.go` | verified |  |
| go | `src/net/interface.go` | verified |  |
| go | `src/runtime/defs_openbsd.go` | verified |  |
| go | `src/runtime/runtime-lldb_test.go` | verified |  |
| go | `src/runtime/secret.go` | verified |  |
| go | `src/runtime/vdso_in_none.go` | verified |  |
| go | `src/sort/zsortinterface.go` | verified |  |
| go | `src/unique/handle_test.go` | verified |  |
| go | `test/fixedbugs/bug448.go` | verified |  |
| go | `test/fixedbugs/gcc65755.go` | verified |  |
| go | `test/fixedbugs/issue31053.dir/main.go` | verified |  |
| go | `test/fixedbugs/issue33020.dir/a.go` | verified |  |
| go | `test/fixedbugs/issue43701.go` | verified |  |
| go | `test/fixedbugs/issue6295.dir/p2.go` | verified |  |
| go | `test/fixedbugs/issue68292.go` | verified |  |
| go | `test/ken/divconst.go` | verified |  |
| go | `test/typeparam/issue51303.go` | verified |  |
| grafana | `apps/plugins/pkg/app/meta/core_test.go` | verified |  |
| grafana | `apps/provisioning/pkg/generated/listers/provisioning/v0alpha1/job.go` | verified |  |
| grafana | `apps/secret/consolidate/v1beta1/consolidate.pb.go` | verified |  |
| grafana | `packages/grafana-schema/src/schema/dashboard/v2alpha1/types.status.gen.ts` | verified |  |
| grafana | `packages/grafana-ui/src/components/Drawer/Drawer.tsx` | verified |  |
| grafana | `pkg/registry/apis/dashboard/mutate.go` | verified |  |
| grafana | `pkg/services/annotations/annotationsapi/api_client_test.go` | verified |  |
| grafana | `pkg/services/annotations/annotationsimpl/cleanup.go` | verified |  |
| grafana | `pkg/services/anonymous/anonimpl/impl.go` | verified |  |
| grafana | `pkg/storage/unified/migrations/fake_migrator_test.go` | verified |  |
| grafana | `pkg/storage/unified/search/kv_remote_index_store.go` | verified |  |
| grafana | `pkg/tsdb/cloudwatch/mocks/accounts_service.go` | verified |  |
| grafana | `pkg/util/ring/adaptive_chan_bench_test.go` | verified |  |
| grafana | `public/app/core/actions/cleanUp.ts` | verified |  |
| grafana | `public/app/features/alerting/unified/components/receivers/PayloadEditor.tsx` | verified |  |
| grafana | `public/app/features/alerting/unified/components/silences/SilenceViewContent.tsx` | verified |  |
| grafana | `public/app/features/alerting/unified/utils/time.ts` | verified |  |
| grafana | `public/app/features/annotations/utils/savedQueryUtils.ts` | verified |  |
| grafana | `public/app/features/provisioning/Wizard/hooks/useWizardNavigation.ts` | verified |  |
| grafana | `public/app/features/query/state/runRequest.ts` | verified |  |
| grafana | `public/app/plugins/datasource/cloudwatch/language/monarch/LinkedToken.ts` | verified |  |
| grafana | `public/app/plugins/panel/geomap/style/types.ts` | verified |  |
