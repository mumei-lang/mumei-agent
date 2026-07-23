# Target OSS no-LLM dogfooding audit — continuation 513 (batch 514)

Run: 2026-07-23T07:38:23.283358+00:00

## Summary

- Files audited: 50
- Verified: 50
- Refuted: 0
- Unverifiable: 0

All sampled files passed no-LLM verification; no new tool-side fixes were required.

## Sample details

| repo | file | status | notes |
|------|------|--------|-------|
| go | `src/cmd/compile/internal/riscv64/gsubr.go` | verified |  |
| go | `src/cmd/compile/internal/ssa/copyelim_test.go` | verified |  |
| go | `src/cmd/go/internal/modload/list.go` | verified |  |
| go | `src/cmd/link/internal/ld/outbuf.go` | verified |  |
| go | `src/compress/gzip/issue14937_test.go` | verified |  |
| go | `src/crypto/internal/fips140/nistec/p256_asm_test.go` | verified |  |
| go | `src/encoding/binary/binary.go` | verified |  |
| go | `src/fmt/scan.go` | verified |  |
| go | `src/go/ast/print.go` | verified |  |
| go | `src/internal/runtime/maps/memhash_aes.go` | verified |  |
| go | `src/internal/saferio/io.go` | verified |  |
| go | `src/internal/syscall/unix/faccessat_solaris.go` | verified |  |
| go | `src/internal/zstd/fse_test.go` | verified |  |
| go | `src/net/http/internal/http2/frame_test.go` | verified |  |
| go | `src/runtime/trace/annotation_test.go` | verified |  |
| go | `test/abi/s_sif_sif.go` | verified |  |
| go | `test/codegen/shift.go` | verified |  |
| go | `test/fixedbugs/bug136.go` | verified |  |
| go | `test/fixedbugs/issue69434.go` | verified |  |
| go | `test/fixedbugs/issue8076.go` | verified |  |
| go | `test/switch6.go` | verified |  |
| go | `test/typeparam/equal.go` | verified |  |
| grafana | `apps/dashboard/pkg/migration/schemaversion/v40_test.go` | verified |  |
| grafana | `apps/folder/pkg/apis/folder/v1/constants.go` | verified |  |
| grafana | `apps/provisioning/pkg/apis/provisioning/v0alpha1/zz_generated.deepcopy.go` | verified |  |
| grafana | `packages/grafana-runtime/src/services/index.ts` | verified |  |
| grafana | `pkg/clientauth/providers.go` | verified |  |
| grafana | `pkg/expr/sql_command_test.go` | verified |  |
| grafana | `pkg/infra/localcache/cache_test.go` | verified |  |
| grafana | `pkg/registry/apis/iam/authorizer/team_binding_authorizer.go` | verified |  |
| grafana | `pkg/registry/apis/preferences/legacy/sql_test.go` | verified |  |
| grafana | `pkg/services/accesscontrol/annotations.go` | verified |  |
| grafana | `pkg/services/apiserver/endpoints/request/namespace.go` | verified |  |
| grafana | `pkg/services/ngalert/provisioning/errors.go` | verified |  |
| grafana | `pkg/services/ngalert/store/alert_rule.go` | verified |  |
| grafana | `pkg/services/star/starimpl/xorm_store_test.go` | verified |  |
| grafana | `pkg/storage/secret/metadata/secure_value_store.go` | verified |  |
| grafana | `pkg/tsdb/influxdb/models/models.go` | verified |  |
| grafana | `pkg/util/proxyutil/proxyutil.go` | verified |  |
| grafana | `public/app/features/alerting/unified/components/import-to-gma/Wizard/useCancelWizardModal.tsx` | verified |  |
| grafana | `public/app/features/alerting/unified/group-details/GroupDetailsPage.tsx` | verified |  |
| grafana | `public/app/features/correlations/components/EmptyCorrelationsCTA.tsx` | verified |  |
| grafana | `public/app/features/dashboard/services/DashboardAnalyticsAggregator.ts` | verified |  |
| grafana | `public/app/features/datasources/components/picker/DataSourceList.tsx` | verified |  |
| grafana | `public/app/features/explore/state/history.ts` | verified |  |
| grafana | `public/app/features/expressions/utils/metaSqlExpr.ts` | verified |  |
| grafana | `public/app/features/manage-dashboards/types.ts` | verified |  |
| grafana | `public/app/features/scopes/selector/useKeyboardInteractions.tsx` | verified |  |
| grafana | `public/app/features/teams/TeamSettings.tsx` | verified |  |
| grafana | `public/app/plugins/datasource/azuremonitor/components/MetricsQueryEditor/setQueryValue.ts` | verified |  |
