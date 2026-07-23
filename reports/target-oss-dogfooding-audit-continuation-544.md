# Target OSS no-LLM dogfooding audit — continuation 544 (batch 545)

Run: 2026-07-23T09:58:38.931322+00:00

## Summary

- Files audited: 50
- Verified: 50
- Refuted: 0
- Unverifiable: 0

All sampled files passed no-LLM verification; no new tool-side fixes were required.

## Sample details

| repo | file | status | notes |
|------|------|--------|-------|
| go | `src/cmd/compile/internal/rangefunc/rangefunc_test.go` | verified |  |
| go | `src/cmd/compile/internal/reflectdata/map.go` | verified |  |
| go | `src/cmd/compile/internal/types2/check_test.go` | verified |  |
| go | `src/cmd/internal/src/xpos_test.go` | verified |  |
| go | `src/crypto/internal/fips140/sha256/sha256block_s390x.go` | verified |  |
| go | `src/crypto/internal/fips140test/check_test.go` | verified |  |
| go | `src/crypto/x509/oid.go` | verified |  |
| go | `src/database/sql/internal/sql.go` | verified |  |
| go | `src/index/suffixarray/gen.go` | verified |  |
| go | `src/internal/goarch/zgoarch_mips64le.go` | verified |  |
| go | `src/math/erfinv.go` | verified |  |
| go | `src/net/dial_unix_test.go` | verified |  |
| go | `src/net/http/internal/chunked_test.go` | verified |  |
| go | `src/net/http/transport_internal_test.go` | verified |  |
| go | `src/net/interface_bsd_test.go` | verified |  |
| go | `src/os/executable.go` | verified |  |
| go | `src/os/path_windows_test.go` | verified |  |
| go | `src/runtime/create_file_nounix.go` | verified |  |
| go | `src/runtime/syscall_aix.go` | verified |  |
| go | `src/runtime/traceback_system_test.go` | verified |  |
| go | `src/runtime/traceruntime.go` | verified |  |
| go | `src/syscall/forkpipe2.go` | verified |  |
| go | `src/syscall/ztypes_freebsd_386.go` | verified |  |
| go | `test/chan/doubleselect.go` | verified |  |
| go | `test/fixedbugs/bug337.go` | verified |  |
| go | `test/fixedbugs/issue48558.go` | verified |  |
| go | `test/fixedbugs/issue60945.dir/b.go` | verified |  |
| go | `test/fixedbugs/issue78081.go` | verified |  |
| go | `test/slice3.go` | verified |  |
| go | `test/typeparam/mdempsky/5.go` | verified |  |
| grafana | `apps/collections/pkg/apis/manifestdata/collections_manifest.go` | verified |  |
| grafana | `apps/dashboard/pkg/apis/dashboard/v2/dashboard_codec_gen.go` | verified |  |
| grafana | `apps/dashboard/pkg/migration/schemaversion/v10.go` | verified |  |
| grafana | `packages/grafana-runtime/src/analyticsFramework/main.ts` | verified |  |
| grafana | `packages/grafana-schema/src/schema/dashboard/v0alpha1/types.metadata.gen.ts` | verified |  |
| grafana | `pkg/infra/nats/subscriber.go` | verified |  |
| grafana | `pkg/registry/apis/dashboard/snapshot/sub_dashboard.go` | verified |  |
| grafana | `pkg/services/accesscontrol/ossaccesscontrol/routes.go` | verified |  |
| grafana | `pkg/services/apiserver/builder/runner/resource_info.go` | verified |  |
| grafana | `pkg/services/pluginsintegration/pluginstore/store.go` | verified |  |
| grafana | `pkg/services/queryhistory/models.go` | verified |  |
| grafana | `pkg/services/store/config.go` | verified |  |
| grafana | `pkg/storage/unified/client.go` | verified |  |
| grafana | `pkg/web/response_writer_test.go` | verified |  |
| grafana | `public/app/core/utils/shortLinks.ts` | verified |  |
| grafana | `public/app/features/gops/configuration-tracker/incidents/hooks.ts` | verified |  |
| grafana | `public/app/features/transformers/partitionByValues/PartitionByValuesEditor.tsx` | verified |  |
| grafana | `public/app/features/variables/state/types.ts` | verified |  |
| grafana | `public/app/plugins/datasource/mysql/configuration/ConfigurationEditor.tsx` | verified |  |
| grafana | `public/app/plugins/panel/dashlist/migrations.ts` | verified |  |
