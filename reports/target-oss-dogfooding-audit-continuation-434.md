# Target OSS no-LLM dogfooding audit — continuation 434 (batch 435)

Run: 2026-07-23T02:11:06.597577+00:00

## Summary

- Files audited: 50
- Verified: 50
- Refuted: 0
- Unverifiable: 0

All sampled files passed no-LLM verification; no new tool-side fixes were required.

## Sample details

| repo | file | status | notes |
|------|------|--------|-------|
| go | `src/cmd/cgo/gcc.go` | verified |  |
| go | `src/cmd/compile/internal/types2/selection.go` | verified |  |
| go | `src/cmd/go/terminal_test.go` | verified |  |
| go | `src/cmd/internal/src/pos_test.go` | verified |  |
| go | `src/cmd/test2json/main.go` | verified |  |
| go | `src/crypto/internal/fips140/nistec/fiat/p224_invert.go` | verified |  |
| go | `src/crypto/sha1/sha1block_amd64.go` | verified |  |
| go | `src/html/template/urlpart_string.go` | verified |  |
| go | `src/math/big/arith.go` | verified |  |
| go | `src/net/tcpsockopt_posix.go` | verified |  |
| go | `src/plugin/plugin_test.go` | verified |  |
| go | `src/runtime/export_pipe2_test.go` | verified |  |
| go | `src/syscall/zsyscall_aix_ppc64.go` | verified |  |
| go | `src/syscall/zsysnum_linux_mips64.go` | verified |  |
| go | `test/codegen/issue75203.go` | verified |  |
| go | `test/fixedbugs/issue33219.go` | verified |  |
| go | `test/fixedbugs/issue4252.dir/main.go` | verified |  |
| go | `test/fixedbugs/issue7129.go` | verified |  |
| go | `test/winbatch.go` | verified |  |
| grafana | `apps/dashboard/pkg/migration/migrate.go` | verified |  |
| grafana | `apps/dashboard/pkg/migration/schemaversion/v36.go` | verified |  |
| grafana | `apps/provisioning/pkg/apis/manifestdata/provisioning_manifest.go` | verified |  |
| grafana | `apps/provisioning/pkg/generated/applyconfiguration/provisioning/v0alpha1/connectionspec.go` | verified |  |
| grafana | `packages/grafana-flamegraph/src/utils/storybook/withTimeZone.tsx` | verified |  |
| grafana | `pkg/apis/datasource/v0alpha1/types.go` | verified |  |
| grafana | `pkg/cmd/grafana-cli/services/io_util.go` | verified |  |
| grafana | `pkg/expr/sql/frame_db.go` | verified |  |
| grafana | `pkg/registry/apis/secret/encryption/manager/oss_dek_cache.go` | verified |  |
| grafana | `pkg/registry/apps/shorturl/register.go` | verified |  |
| grafana | `pkg/services/featuremgmt/types.go` | verified |  |
| grafana | `pkg/services/live/pipeline/frame_condition_checker.go` | verified |  |
| grafana | `pkg/services/ngalert/api/tooling/definitions/cortex-ruler.go` | verified |  |
| grafana | `pkg/services/ngalert/image/service.go` | verified |  |
| grafana | `pkg/storage/unified/resourcepb/resourcewatch.pb.go` | verified |  |
| grafana | `pkg/tests/apis/provisioning/jobs/conflict/conflict_test.go` | verified |  |
| grafana | `pkg/tests/apis/provisioning/jobs/deletejob_test.go` | verified |  |
| grafana | `pkg/util/xorm/dialect_postgres.go` | verified |  |
| grafana | `public/app/features/alerting/unified/home/Home.tsx` | verified |  |
| grafana | `public/app/features/alerting/unified/rule-list/components/GroupIntervalMetadata.tsx` | verified |  |
| grafana | `public/app/features/dashboard-scene/serialization/transformSaveModelToScene.ts` | verified |  |
| grafana | `public/app/features/dashboard/components/DashExportModal/DashboardExporter.ts` | verified |  |
| grafana | `public/app/features/dashboard/components/ShareModal/SharePublicDashboard/SupportedPubdashDatasources.ts` | verified |  |
| grafana | `public/app/features/explore/Logs/utils/table/logsTable.ts` | verified |  |
| grafana | `public/app/features/manage-dashboards/components/PublicDashboardListTable/PublicDashboardListTable.tsx` | verified |  |
| grafana | `public/app/features/plugins/admin/components/PluginDetailsPage.tsx` | verified |  |
| grafana | `public/app/features/plugins/extensions/registry/useRegistrySlice.tsx` | verified |  |
| grafana | `public/app/features/transformers/extractFields/types.ts` | verified |  |
| grafana | `public/app/plugins/datasource/azuremonitor/components/MetricsQueryEditor/MetricsQueryEditor.tsx` | verified |  |
| grafana | `public/app/plugins/panel/geomap/layers/basemaps/index.ts` | verified |  |
| grafana | `public/app/plugins/panel/text/panelcfg.gen.ts` | verified |  |
