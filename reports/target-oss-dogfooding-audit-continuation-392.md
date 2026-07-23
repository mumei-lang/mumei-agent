# Target OSS no-LLM dogfooding audit — continuation 392 (batch 393)

Run: 2026-07-23T00:16:19.880798+00:00

## Summary

- Files audited: 50
- Verified: 50
- Refuted: 0
- Unverifiable: 0

All sampled files passed no-LLM verification; no new tool-side fixes were required.

## Sample details

| repo | file | status | notes |
|------|------|--------|-------|
| go | `src/cmd/cgo/internal/test/issue1435.go` | verified |  |
| go | `src/cmd/compile/internal/types2/universe.go` | verified |  |
| go | `src/crypto/internal/boring/sha.go` | verified |  |
| go | `src/crypto/internal/fips140/aes/cbc_noasm.go` | verified |  |
| go | `src/crypto/internal/fips140/nistec/p256_table.go` | verified |  |
| go | `src/encoding/json/fold.go` | verified |  |
| go | `src/encoding/json/jsontext/quote.go` | verified |  |
| go | `src/internal/reflectlite/all_test.go` | verified |  |
| go | `src/internal/runtime/syscall/linux/defs_linux_386.go` | verified |  |
| go | `src/internal/strconv/deps.go` | verified |  |
| go | `src/simd/archsimd/string.go` | verified |  |
| go | `test/abi/wrapdefer_largetmp.go` | verified |  |
| go | `test/fixedbugs/bug031.go` | verified |  |
| go | `test/fixedbugs/bug335.dir/b.go` | verified |  |
| go | `test/fixedbugs/issue19261.dir/p.go` | verified |  |
| go | `test/fixedbugs/issue7150.go` | verified |  |
| go | `test/fixedbugs/issue78314.go` | verified |  |
| go | `test/typeparam/issue52117.dir/b.go` | verified |  |
| grafana | `apps/secret/pkg/apis/secret/v1beta1/keeper_type.go` | verified |  |
| grafana | `packages/grafana-api-clients/src/clients/rtkq/migrate-to-cloud/endpoints.gen.ts` | verified |  |
| grafana | `packages/grafana-data/src/themes/createVisualizationColors.ts` | verified |  |
| grafana | `packages/grafana-data/src/types/config.ts` | verified |  |
| grafana | `packages/grafana-runtime/src/services/pluginExtensions/utils.tsx` | verified |  |
| grafana | `packages/grafana-ui/src/components/Table/Cells/BarGaugeCell.tsx` | verified |  |
| grafana | `pkg/expr/mathexp/reduce.go` | verified |  |
| grafana | `pkg/infra/localcache/cache.go` | verified |  |
| grafana | `pkg/infra/log/logtest/slog.go` | verified |  |
| grafana | `pkg/registry/apis/iam/team/rest_add_member.go` | verified |  |
| grafana | `pkg/registry/apis/provisioning/types.go` | verified |  |
| grafana | `pkg/services/annotations/accesscontrol/accesscontrol_test.go` | verified |  |
| grafana | `pkg/services/ngalert/api/api_ruler.go` | verified |  |
| grafana | `pkg/services/ngalert/notifier/legacy_storage/compat_test.go` | verified |  |
| grafana | `pkg/services/pluginsintegration/plugincontext/base_plugincontext.go` | verified |  |
| grafana | `pkg/storage/legacysql/dualwrite/runtime_test.go` | verified |  |
| grafana | `pkg/tests/api/correlations/common_test.go` | verified |  |
| grafana | `pkg/tests/apis/provisioning/git/sourcepath_guard/helper_test.go` | verified |  |
| grafana | `pkg/tsdb/graphite/null_float.go` | verified |  |
| grafana | `pkg/util/xorm/logger.go` | verified |  |
| grafana | `pkg/util/xorm/statement.go` | verified |  |
| grafana | `public/app/features/auth-config/utils/guards.ts` | verified |  |
| grafana | `public/app/features/dashboard-scene/saving/shared.tsx` | verified |  |
| grafana | `public/app/features/dashboard-scene/sharing/ExportButton/ResourceExport.tsx` | verified |  |
| grafana | `public/app/features/explore/spec/helper/query.ts` | verified |  |
| grafana | `public/app/features/plugins/extensions/logs/testUtils.ts` | verified |  |
| grafana | `public/app/features/serviceaccounts/state/actionsServiceAccountPage.ts` | verified |  |
| grafana | `public/app/plugins/datasource/azuremonitor/components/shared/FormatAsField.tsx` | verified |  |
| grafana | `public/app/plugins/datasource/cloudwatch/language/cloudwatch-ppl/definition.ts` | verified |  |
| grafana | `public/app/plugins/datasource/cloudwatch/query-runner/CloudWatchMetricsQueryRunner.ts` | verified |  |
| grafana | `public/app/plugins/datasource/loki/logsTimeSplitting.ts` | verified |  |
| grafana | `public/app/types/eslint.d.ts` | verified |  |
