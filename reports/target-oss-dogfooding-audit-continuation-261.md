# Target OSS no-LLM dogfooding audit — continuation 261 (batch 262)

Run: 2026-07-22T15:20:20.819752+00:00

## Summary

- Files audited: 50
- Verified: 50
- Refuted: 0
- Unverifiable: 0

All sampled files passed no-LLM verification after the `_mask_go_function_literals` fix for Go function type fields.

## Sample details

| repo | file | status | notes |
|------|------|--------|-------|
| go | `src/cmd/compile/internal/test/mergelocals_test.go` | verified |  |
| go | `src/cmd/go/internal/work/security_test.go` | verified |  |
| go | `src/crypto/internal/fips140/edwards25519/scalar_fiat.go` | verified |  |
| go | `src/errors/example_test.go` | verified |  |
| go | `src/go/types/range.go` | verified |  |
| go | `src/internal/syscall/unix/kernel_version_freebsd.go` | verified |  |
| go | `src/math/big/internal/asmgen/amd64.go` | verified |  |
| go | `src/math/rand/v2/rand_test.go` | verified |  |
| go | `src/net/port_test.go` | verified |  |
| go | `src/runtime/lfstack_test.go` | verified |  |
| go | `src/runtime/netpoll_kqueue_event.go` | verified |  |
| go | `test/fixedbugs/bug391.go` | verified |  |
| go | `test/fixedbugs/issue44739.go` | verified |  |
| go | `test/fixedbugs/issue47928.go` | verified |  |
| go | `test/fixedbugs/issue67160.go` | verified |  |
| grafana | `apps/dashboard/pkg/apis/dashboard/v2alpha1/types.go` | verified |  |
| grafana | `apps/iam/pkg/apis/iam/v0alpha1/resourcepermission_client_gen.go` | verified |  |
| grafana | `apps/iam/pkg/apis/iam/v0alpha1/user_getuserteams_response_body_types_gen.go` | verified |  |
| grafana | `packages/grafana-flamegraph/src/CallTree/ColorBarCell.tsx` | verified |  |
| grafana | `packages/grafana-schema/src/schema/dashboard/v2beta1/types.status.gen.ts` | verified |  |
| grafana | `packages/grafana-ui/src/utils/tooltipUtils.ts` | verified |  |
| grafana | `pkg/apiserver/auditing/policy.go` | verified |  |
| grafana | `pkg/apiserver/storage/testing/store_tests.go` | verified |  |
| grafana | `pkg/expr/query_convert_test.go` | verified |  |
| grafana | `pkg/plugins/manager/pipeline/bootstrap/steps.go` | verified |  |
| grafana | `pkg/registry/apis/provisioning/jobs/export/resources_specific_test.go` | verified |  |
| grafana | `pkg/services/ngalert/schedule/loaded_metrics_reader_test.go` | verified |  |
| grafana | `pkg/services/ngalert/state/manager_bench_test.go` | verified |  |
| grafana | `pkg/services/notifications/notifications_test.go` | verified |  |
| grafana | `pkg/services/provisioning/dashboards/file_reader.go` | verified |  |
| grafana | `pkg/storage/unified/resource/datastore_test.go` | verified |  |
| grafana | `public/app/api/clients/dashboard/v0alpha1/index.ts` | verified |  |
| grafana | `public/app/features/alerting/unified/rule-list/components/LoadMoreButton.tsx` | verified |  |
| grafana | `public/app/features/dashboard-scene/scene/VizPanelSubHeader.tsx` | verified |  |
| grafana | `public/app/features/dashboard-scene/sharing/ShareButton/ShareMenu.tsx` | verified |  |
| grafana | `public/app/features/dashboard/dashgrid/liveTimer.ts` | verified |  |
| grafana | `public/app/features/live/index.ts` | verified |  |
| grafana | `public/app/features/transformers/regression/constants.ts` | verified |  |
| grafana | `public/app/plugins/datasource/cloudwatch/language/cloudwatch-sql/completion/types.ts` | verified |  |
| grafana | `public/test/mocks/nearMembraneDom.ts` | verified |  |
| prysm | `beacon-chain/operations/attestations/prepare_forkchoice.go` | verified |  |
| prysm | `beacon-chain/slasher/helpers_test.go` | verified |  |
| prysm | `beacon-chain/sync/initial-sync/fsm_benchmark_test.go` | verified |  |
| prysm | `config/params/export_test.go` | verified |  |
| prysm | `proto/prysm/v1alpha1/beacon_block.pb.go` | verified |  |
| prysm | `proto/prysm/v1alpha1/gloas.pb.go` | verified |  |
| prysm | `testing/endtoend/evaluators/beaconapi/types.go` | verified |  |
| prysm | `testing/spectest/minimal/gloas__epoch_processing__participation_flag_updates_test.go` | verified |  |
| prysm | `validator/db/alias.go` | verified |  |
| prysm | `validator/db/iface/interface.go` | verified |  |
