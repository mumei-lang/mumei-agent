# Target OSS no-LLM dogfooding audit — continuation 308 (batch 309)

Run: 2026-07-22T18:40:36.163376+00:00

## Summary

- Files audited: 50
- Verified: 50
- Refuted: 0
- Unverifiable: 0

All sampled files passed no-LLM verification; no new tool-side fixes were required.

## Sample details

| repo | file | status | notes |
|------|------|--------|-------|
| go | `src/cmd/compile/internal/ppc64/ssa.go` | verified |  |
| go | `src/cmd/compile/internal/ssa/_gen/main.go` | verified |  |
| go | `src/cmd/internal/obj/x86/obj6.go` | verified |  |
| go | `src/math/big/arith_decl.go` | verified |  |
| go | `src/math/trig_reduce.go` | verified |  |
| go | `src/runtime/defs_freebsd_386.go` | verified |  |
| go | `src/runtime/mkfastlog2table.go` | verified |  |
| go | `src/simd/archsimd/internal/simd_test/binary_arm64_test.go` | verified |  |
| go | `test/codegen/noextend.go` | verified |  |
| go | `test/fixedbugs/bug418.go` | verified |  |
| go | `test/fixedbugs/issue15091.go` | verified |  |
| go | `test/fixedbugs/issue34966.go` | verified |  |
| go | `test/fixedbugs/issue59293.go` | verified |  |
| go | `test/ken/simparray.go` | verified |  |
| grafana | `apps/iam/pkg/apis/iam/v0alpha1/user_status_gen.go` | verified |  |
| grafana | `packages/grafana-ui/src/components/Select/resetSelectStyles.ts` | verified |  |
| grafana | `pkg/infra/process/process.go` | verified |  |
| grafana | `pkg/plugins/manager/pipeline/bootstrap/factory.go` | verified |  |
| grafana | `pkg/registry/apis/provisioning/resources/ownership_test.go` | verified |  |
| grafana | `pkg/registry/apis/secret/contracts/decrypt.go` | verified |  |
| grafana | `pkg/registry/apis/secret/inline/inline_secure_value.go` | verified |  |
| grafana | `pkg/services/annotations/accesscontrol/models.go` | verified |  |
| grafana | `pkg/services/dashboards/service/service.go` | verified |  |
| grafana | `pkg/services/dashboardsnapshots/service_test.go` | verified |  |
| grafana | `pkg/services/featuremgmt/codeowners.go` | verified |  |
| grafana | `pkg/services/ngalert/eval/testing.go` | verified |  |
| grafana | `pkg/services/secrets/kvstore/kvstore.go` | verified |  |
| grafana | `pkg/services/sqlstore/migrator/types.go` | verified |  |
| grafana | `pkg/tests/apis/provisioning/jobs/folderless_test.go` | verified |  |
| grafana | `pkg/tests/apis/provisioning/librarypanels_test.go` | verified |  |
| grafana | `pkg/tsdb/cloudwatch/metric_find_query.go` | verified |  |
| grafana | `public/app/features/alerting/unified/notifications/NotificationDetailPage.tsx` | verified |  |
| grafana | `public/app/features/auth-config/ProviderConfigPage.tsx` | verified |  |
| grafana | `public/app/features/dashboard-scene/scene/layout-notebook/NotebookCellItem.tsx` | verified |  |
| grafana | `public/app/features/dashboard-scene/settings/variables/LocalVariableEditableElement.tsx` | verified |  |
| grafana | `public/app/features/explore/TraceView/components/utils/test/requestAnimationFrame.ts` | verified |  |
| grafana | `public/app/features/explore/state/main.ts` | verified |  |
| grafana | `public/app/features/variables/query/variableQueryObserver.ts` | verified |  |
| grafana | `public/app/features/variables/switch/adapter.ts` | verified |  |
| grafana | `public/app/plugins/datasource/cloudwatch/components/QueryEditor/MetricsQueryEditor/SQLBuilderEditor/SQLOrderByGroup.tsx` | verified |  |
| prysm | `beacon-chain/operations/slashings/service.go` | verified |  |
| prysm | `beacon-chain/operations/voluntaryexits/log.go` | verified |  |
| prysm | `beacon-chain/rpc/eth/rewards/server.go` | verified |  |
| prysm | `beacon-chain/state/fieldtrie/log.go` | verified |  |
| prysm | `beacon-chain/sync/service_test.go` | verified |  |
| prysm | `beacon-chain/sync/subscriber_beacon_blocks.go` | verified |  |
| prysm | `crypto/bls/common/constants.go` | verified |  |
| prysm | `testing/spectest/mainnet/deneb__forkchoice__forkchoice_test.go` | verified |  |
| prysm | `testing/spectest/shared/gloas/epoch_processing/registry_updates.go` | verified |  |
| prysm | `validator/db/kv/import.go` | verified |  |
