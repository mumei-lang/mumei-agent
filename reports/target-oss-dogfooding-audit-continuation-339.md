# Target OSS no-LLM dogfooding audit — continuation 339 (batch 340)

Run: 2026-07-22T20:39:30.395528+00:00

## Summary

- Files audited: 50
- Verified: 50
- Refuted: 0
- Unverifiable: 0

All sampled files passed no-LLM verification; no new tool-side fixes were required.

## Sample details

| repo | file | status | notes |
|------|------|--------|-------|
| go | `src/cmd/cgo/internal/test/cgo_linux_test.go` | verified |  |
| go | `src/crypto/ed25519/ed25519_wycheproof_test.go` | verified |  |
| go | `src/crypto/mldsa/mldsa_fips140v1.0.go` | verified |  |
| go | `src/debug/dwarf/typeunit.go` | verified |  |
| go | `src/fmt/state_test.go` | verified |  |
| go | `src/internal/chacha8rand/chacha8.go` | verified |  |
| go | `src/internal/exportdata/exportdata.go` | verified |  |
| go | `src/internal/goarch/zgoarch_s390x.go` | verified |  |
| go | `src/internal/runtime/syscall/windows/defs_windows_amd64.go` | verified |  |
| go | `src/math/asinh.go` | verified |  |
| go | `src/os/user/listgroups_unix.go` | verified |  |
| go | `src/runtime/signal_dragonfly.go` | verified |  |
| go | `src/syscall/export_linux_test.go` | verified |  |
| go | `test/fixedbugs/bug281.go` | verified |  |
| go | `test/fixedbugs/issue8155.go` | verified |  |
| grafana | `apps/example/pkg/apis/example/v1alpha1/example_codec_gen.go` | verified |  |
| grafana | `apps/logsdrilldown/plugin/src/generated/logsdrilldowndefaultcolumns/v1alpha1/logsdrilldowndefaultcolumns_object_gen.ts` | verified |  |
| grafana | `apps/provisioning/pkg/generated/applyconfiguration/provisioning/v0alpha1/localrepositoryconfig.go` | verified |  |
| grafana | `apps/provisioning/pkg/generated/clientset/versioned/clientset.go` | verified |  |
| grafana | `apps/shorturl/pkg/apis/shorturl/v1beta1/shorturl_getgoto_response_types_gen.go` | verified |  |
| grafana | `packages/grafana-ui/src/components/Segment/Segment.tsx` | verified |  |
| grafana | `packages/grafana-ui/src/utils/SelectionReference.ts` | verified |  |
| grafana | `pkg/apimachinery/identity/requester.go` | verified |  |
| grafana | `pkg/registry/apis/iam/resourcepermission/list_iterator.go` | verified |  |
| grafana | `pkg/registry/apis/provisioning/controller/connection_health_mock.go` | verified |  |
| grafana | `pkg/services/apikey/apikeyimpl/xorm_store_test.go` | verified |  |
| grafana | `pkg/services/ngalert/provisioning/errors_test.go` | verified |  |
| grafana | `pkg/services/provisioning/alerting/notification_policy_types_test.go` | verified |  |
| grafana | `pkg/services/publicdashboards/internal/public_dashboard_service_wrapper_mock.go` | verified |  |
| grafana | `pkg/services/publicdashboards/internal/service/intervalv2/intervalv2.go` | verified |  |
| grafana | `public/app/core/journeys/searchToResource.smoke.ts` | verified |  |
| grafana | `public/app/features/alerting/unified/hooks/usePrometheusConsistencyCheck.ts` | verified |  |
| grafana | `public/app/features/commandPalette/scopes/recentScopesActions.ts` | verified |  |
| grafana | `public/app/features/dashboard/services/DashboardLoaderSrv.ts` | verified |  |
| grafana | `public/app/features/dashboard/state/actions.ts` | verified |  |
| grafana | `public/app/features/explore/spec/helper/assert.ts` | verified |  |
| grafana | `public/app/features/plugins/extensions/usePluginComponents.tsx` | verified |  |
| grafana | `public/app/features/teams/create-team/CreateTeam.tsx` | verified |  |
| grafana | `public/app/plugins/panel/heatmap/HeatmapTooltip.tsx` | verified |  |
| grafana | `public/app/plugins/panel/stat/StatMigrations.ts` | verified |  |
| prysm | `beacon-chain/blockchain/process_block_helpers_test.go` | verified |  |
| prysm | `beacon-chain/execution/engine_client_test.go` | verified |  |
| prysm | `beacon-chain/state/state-native/readonly_validator_test.go` | verified |  |
| prysm | `beacon-chain/sync/checkpoint/file.go` | verified |  |
| prysm | `cmd/log.go` | verified |  |
| prysm | `consensus-types/blocks/roblock.go` | verified |  |
| prysm | `consensus-types/hdiff/state_diff.go` | verified |  |
| prysm | `testing/endtoend/evaluators/node_test.go` | verified |  |
| prysm | `testing/mock/beacon_service_mock.go` | verified |  |
| prysm | `testing/spectest/mainnet/fulu__operations__sync_committee_test.go` | verified |  |
