# Target OSS no-LLM dogfooding audit — continuation 265 (batch 266)

Run: 2026-07-22T15:40:49.836010+00:00

## Summary

- Files audited: 50
- Verified: 50
- Refuted: 0
- Unverifiable: 0

All sampled files passed no-LLM verification; no new tool-side fixes were required.

## Sample details

| repo | file | status | notes |
|------|------|--------|-------|
| go | `src/cmd/compile/internal/types/fmt.go` | verified |  |
| go | `src/cmd/go/internal/lockedfile/internal/filelock/filelock.go` | verified |  |
| go | `src/cmd/go/stop_other_test.go` | verified |  |
| go | `src/cmd/gofmt/gofmt.go` | verified |  |
| go | `src/cmd/trace/jsontrace.go` | verified |  |
| go | `src/embed/internal/embedtest/embed_test.go` | verified |  |
| go | `src/internal/runtime/gc/internal/gen/gp.go` | verified |  |
| go | `src/syscall/ztypes_linux_arm.go` | verified |  |
| go | `test/fixedbugs/bug052.go` | verified |  |
| go | `test/fixedbugs/issue14999.go` | verified |  |
| go | `test/fixedbugs/issue43633.dir/a.go` | verified |  |
| go | `test/fixedbugs/issue54343.go` | verified |  |
| go | `test/fixedbugs/issue6298.go` | verified |  |
| grafana | `apps/dashboard/pkg/apis/dashboard/v1/conversion.go` | verified |  |
| grafana | `apps/dashvalidator/pkg/validator/prometheus/interpolation_test.go` | verified |  |
| grafana | `packages/grafana-schema/src/raw/composable/statetimeline/panelcfg/x/types.gen.ts` | verified |  |
| grafana | `packages/grafana-ui/src/components/InteractiveTable/InteractiveTable.tsx` | verified |  |
| grafana | `packages/grafana-ui/src/components/MatchersUI/FieldNameMatcherEditor.tsx` | verified |  |
| grafana | `packages/grafana-ui/src/components/Menu/MenuDivider.tsx` | verified |  |
| grafana | `packages/grafana-ui/src/components/Table/TableNG/Filter/utils.ts` | verified |  |
| grafana | `pkg/infra/usagestats/service/usage_stats_test.go` | verified |  |
| grafana | `pkg/plugins/localfiles_test.go` | verified |  |
| grafana | `pkg/registry/apis/provisioning/jobs/history_reader.go` | verified |  |
| grafana | `pkg/services/accesscontrol/resourcepermissions/hook.go` | verified |  |
| grafana | `pkg/services/auth/idimpl/service.go` | verified |  |
| grafana | `pkg/services/auth/jwt/auth.go` | verified |  |
| grafana | `pkg/services/dashboardsnapshots/service_mock.go` | verified |  |
| grafana | `pkg/services/ngalert/api/api_testing_test.go` | verified |  |
| grafana | `pkg/services/ngalert/store/database.go` | verified |  |
| grafana | `pkg/services/ngalert/store/provisioning_store_test.go` | verified |  |
| grafana | `pkg/services/pluginsintegration/clientmiddleware/clear_auth_headers_middleware_test.go` | verified |  |
| grafana | `pkg/storage/unified/resource/pruner_history_limits_test.go` | verified |  |
| grafana | `pkg/util/cmputil/reporter_test.go` | verified |  |
| grafana | `public/app/features/dashboard/components/SaveDashboard/useDashboardSave.tsx` | verified |  |
| grafana | `public/app/features/explore/TraceView/components/common/CopyIcon.tsx` | verified |  |
| grafana | `public/app/features/migrate-to-cloud/onprem/resourceInfo.ts` | verified |  |
| grafana | `public/app/features/plugins/admin/components/UpdateAllButton.tsx` | verified |  |
| grafana | `public/app/plugins/datasource/azuremonitor/utils/common.ts` | verified |  |
| grafana | `public/app/plugins/datasource/influxdb/fsql/flightsqlMetaQuery.ts` | verified |  |
| grafana | `public/app/plugins/panel/logs/types.ts` | verified |  |
| prysm | `api/grpc/log.go` | verified |  |
| prysm | `beacon-chain/rpc/prysm/node/custody_test.go` | verified |  |
| prysm | `cache/lru/lru_wrpr_test.go` | verified |  |
| prysm | `cmd/prysmctl/testnet/log.go` | verified |  |
| prysm | `consensus-types/primitives/wei_test.go` | verified |  |
| prysm | `proto/prysm/v1alpha1/bellatrix.minimal.ssz.go` | verified |  |
| prysm | `testing/spectest/mainnet/capella__sanity__blocks_test.go` | verified |  |
| prysm | `testing/spectest/mainnet/electra__operations__sync_committee_test.go` | verified |  |
| prysm | `testing/spectest/minimal/capella__operations__execution_payload_test.go` | verified |  |
| prysm | `validator/db/filesystem/genesis.go` | verified |  |
