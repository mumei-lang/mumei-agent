# Target OSS no-LLM dogfooding audit — continuation 384 (batch 385)

Run: 2026-07-22T23:45:23.511305+00:00

## Summary

- Files audited: 50
- Verified: 50
- Refuted: 0
- Unverifiable: 0

All sampled files passed no-LLM verification; no new tool-side fixes were required.

## Sample details

| repo | file | status | notes |
|------|------|--------|-------|
| go | `src/arena/arena_test.go` | verified |  |
| go | `src/cmd/link/internal/ld/asmb.go` | verified |  |
| go | `src/cmd/link/internal/wasm/obj.go` | verified |  |
| go | `src/crypto/internal/rand/random_fips140v1.0.go` | verified |  |
| go | `src/errors/wrap_test.go` | verified |  |
| go | `src/internal/goexperiment/exp_dwarf5_off.go` | verified |  |
| go | `src/internal/goos/zgoos_linux.go` | verified |  |
| go | `src/internal/platform/zosarch.go` | verified |  |
| go | `src/internal/sysinfo/export_test.go` | verified |  |
| go | `src/net/interface_darwin.go` | verified |  |
| go | `src/os/tempfile.go` | verified |  |
| go | `src/simd/archsimd/_gen/unify/pos.go` | verified |  |
| go | `src/simd/archsimd/internal/simd_test/ternary_arm64_test.go` | verified |  |
| go | `src/syscall/zsysctl_openbsd.go` | verified |  |
| go | `src/syscall/ztypes_netbsd_arm.go` | verified |  |
| go | `test/fixedbugs/bug480.go` | verified |  |
| go | `test/fixedbugs/issue18636.go` | verified |  |
| go | `test/fixedbugs/issue19699.go` | verified |  |
| go | `test/fixedbugs/issue4590.go` | verified |  |
| go | `test/fixedbugs/issue8385.go` | verified |  |
| go | `test/typeparam/issue52228.go` | verified |  |
| grafana | `apps/advisor/pkg/apis/advisor/v0alpha1/createregister_response_object_types_gen.go` | verified |  |
| grafana | `apps/alerting/notifications/pkg/apis/alertingnotifications/v0alpha1/timeinterval_codec_gen.go` | verified |  |
| grafana | `apps/provisioning/pkg/generated/applyconfiguration/provisioning/v0alpha1/repositorystatus.go` | verified |  |
| grafana | `packages/grafana-data/src/transformations/matchers/compareValues.ts` | verified |  |
| grafana | `packages/grafana-data/src/types/logs.ts` | verified |  |
| grafana | `packages/grafana-sql/src/components/visual-query-builder/AwesomeQueryBuilder.tsx` | verified |  |
| grafana | `packages/grafana-ui/src/components/UsersIndicator/Avatar.tsx` | verified |  |
| grafana | `pkg/registry/apis/appplugin/register.go` | verified |  |
| grafana | `pkg/registry/apis/dashboard/schema_validation.go` | verified |  |
| grafana | `pkg/registry/apis/datasource/authorizer.go` | verified |  |
| grafana | `pkg/registry/apis/provisioning/resources/parser_mock.go` | verified |  |
| grafana | `pkg/registry/apis/secret/garbagecollectionworker/worker_test.go` | verified |  |
| grafana | `pkg/services/authz/rbac.go` | verified |  |
| grafana | `pkg/storage/unified/parquet/writer.go` | verified |  |
| grafana | `pkg/tests/apis/provisioning/git/incrementaldiffthreshold/helper_test.go` | verified |  |
| grafana | `pkg/tests/apis/provisioning/jobs/deletejob_auth_test.go` | verified |  |
| grafana | `pkg/util/shortid_generator_race_test.go` | verified |  |
| grafana | `pkg/util/validation.go` | verified |  |
| grafana | `public/app/features/alerting/unified/components/GrafanaAlertmanagerWarning.tsx` | verified |  |
| grafana | `public/app/features/alerting/unified/createRouteGroupsMatcherWorker.ts` | verified |  |
| grafana | `public/app/features/alerting/unified/hooks/abilities/rules/rulerRuleAbilities.ts` | verified |  |
| grafana | `public/app/features/connections/tabs/ConnectData/constants.ts` | verified |  |
| grafana | `public/app/features/dashboard-scene/scene/types/LayoutItemTypeGuards.ts` | verified |  |
| grafana | `public/app/features/inspector/InspectStatsTab.tsx` | verified |  |
| grafana | `public/app/features/provisioning/components/Dashboards/SaveProvisionedDashboard.tsx` | verified |  |
| grafana | `public/app/features/provisioning/utils/time.ts` | verified |  |
| grafana | `public/app/features/serviceaccounts/components/ServiceAccountRoleRow.tsx` | verified |  |
| grafana | `public/app/features/variables/state/getNextVariableIndex.ts` | verified |  |
| grafana | `public/app/features/variables/textbox/reducer.ts` | verified |  |
