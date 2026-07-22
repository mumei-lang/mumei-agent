# Target OSS no-LLM dogfooding audit — continuation 323 (batch 324)

Run: 2026-07-22T19:40:04.735578+00:00

## Summary

- Files audited: 50
- Verified: 50
- Refuted: 0
- Unverifiable: 0

All sampled files passed no-LLM verification; no new tool-side fixes were required.

## Sample details

| repo | file | status | notes |
|------|------|--------|-------|
| go | `src/cmd/compile/internal/ssa/rewritedivmod.go` | verified |  |
| go | `src/cmd/internal/disasm/disasm.go` | verified |  |
| go | `src/cmd/internal/obj/riscv/doc.go` | verified |  |
| go | `src/cmd/internal/pathcache/lookpath.go` | verified |  |
| go | `src/crypto/x509/root_linux.go` | verified |  |
| go | `src/flag/flag.go` | verified |  |
| go | `src/internal/goarch/goarch_mips.go` | verified |  |
| go | `src/internal/goversion/goversion.go` | verified |  |
| go | `src/internal/trace/testtrace/helpers_test.go` | verified |  |
| go | `src/math/bits/export_test.go` | verified |  |
| go | `src/mime/mediatype_test.go` | verified |  |
| go | `src/sync/map_reference_test.go` | verified |  |
| go | `test/abi/fibish.go` | verified |  |
| go | `test/fixedbugs/issue23094.go` | verified |  |
| go | `test/fixedbugs/issue47068.dir/main.go` | verified |  |
| go | `test/typeparam/issue51367.go` | verified |  |
| grafana | `apps/iam/pkg/apis/iam/v0alpha1/user_getuserteams_response_object_types_gen.go` | verified |  |
| grafana | `apps/provisioning/pkg/repository/mock_webhook_client.go` | verified |  |
| grafana | `apps/provisioning/pkg/safepath/safe.go` | verified |  |
| grafana | `e2e-playwright/dashboard-new-layouts/page-objects/sidebar/Toolbar.ts` | verified |  |
| grafana | `packages/grafana-data/src/transformations/matchers/simpleFieldMatcher.ts` | verified |  |
| grafana | `packages/grafana-schema/src/raw/composable/text/panelcfg/x/types.gen.ts` | verified |  |
| grafana | `packages/grafana-ui/src/components/RadialGauge/RadialArcPathEndpointMarks.tsx` | verified |  |
| grafana | `packages/grafana-ui/src/components/Table/TableNG/refactored/TableDataGrid.tsx` | verified |  |
| grafana | `packages/grafana-ui/src/options/builder/hideSeries.tsx` | verified |  |
| grafana | `pkg/services/ngalert/schedule/fetcher.go` | verified |  |
| grafana | `pkg/services/sqlstore/migrations/ualert/state_evaluation_duration_mig.go` | verified |  |
| grafana | `pkg/services/store/sanitize.go` | verified |  |
| grafana | `pkg/storage/unified/resource/fieldSelector.go` | verified |  |
| grafana | `pkg/tests/apis/dashboard/bom_test.go` | verified |  |
| grafana | `pkg/tsdb/influxdb/influxql/influxql.go` | verified |  |
| grafana | `public/app/features/admin/UserLdapSyncInfo.tsx` | verified |  |
| grafana | `public/app/features/alerting/unified/components/rule-editor/alert-rule-form/AlertRuleForm.tsx` | verified |  |
| grafana | `public/app/features/alerting/unified/mockGrafanaNotifiers.ts` | verified |  |
| grafana | `public/app/features/auth-config/components/ServerDiscoveryField.tsx` | verified |  |
| grafana | `public/app/features/dashboard/api/utils.ts` | verified |  |
| grafana | `public/app/features/home/analytics/types.ts` | verified |  |
| grafana | `public/app/features/variables/pickers/types.ts` | verified |  |
| grafana | `public/app/plugins/datasource/cloudwatch/language/cloudwatch-sql/definition.ts` | verified |  |
| grafana | `public/app/plugins/datasource/loki/querybuilder/parsingUtils.ts` | verified |  |
| prysm | `api/client/event/fallback.go` | verified |  |
| prysm | `beacon-chain/core/helpers/randao_test.go` | verified |  |
| prysm | `beacon-chain/core/transition/transition_no_verify_sig_test.go` | verified |  |
| prysm | `beacon-chain/startup/clock.go` | verified |  |
| prysm | `config/params/loader.go` | verified |  |
| prysm | `consensus-types/primitives/committee_index_test.go` | verified |  |
| prysm | `crypto/keystore/keccak256.go` | verified |  |
| prysm | `proto/prysm/v1alpha1/phase0.ssz.go` | verified |  |
| prysm | `testing/middleware/engine-api-proxy/proxy.go` | verified |  |
| prysm | `testing/spectest/mainnet/fulu__fork__upgrade_to_fulu_test.go` | verified |  |
