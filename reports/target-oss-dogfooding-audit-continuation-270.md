# Target OSS no-LLM dogfooding audit — continuation 270 (batch 271)

Run: 2026-07-22T16:01:45.643000+00:00

## Summary

- Files audited: 50
- Verified: 50
- Refuted: 0
- Unverifiable: 0

All sampled files passed no-LLM verification; no new tool-side fixes were required.

## Sample details

| repo | file | status | notes |
|------|------|--------|-------|
| go | `src/archive/tar/tar_test.go` | verified |  |
| go | `src/cmd/asm/internal/arch/arm64.go` | verified |  |
| go | `src/cmd/go/internal/work/gc.go` | verified |  |
| go | `src/crypto/internal/boring/boring.go` | verified |  |
| go | `src/crypto/tls/defaults_fips140.go` | verified |  |
| go | `src/go/types/map.go` | verified |  |
| go | `src/internal/fuzz/trace.go` | verified |  |
| go | `src/os/sys_solaris.go` | verified |  |
| go | `test/fixedbugs/bug123.go` | verified |  |
| go | `test/fixedbugs/bug126.go` | verified |  |
| go | `test/fixedbugs/issue46234.go` | verified |  |
| go | `test/typeparam/issue54497.go` | verified |  |
| grafana | `apps/alerting/notifications/pkg/apis/alertingnotifications/v1beta1/receiver_createreceiverintegrationtest_response_object_types_gen.go` | verified |  |
| grafana | `apps/annotation/pkg/apis/annotation/v0alpha1/annotation_client_gen.go` | verified |  |
| grafana | `apps/collections/pkg/apis/collections/v1alpha1/stars_object_gen.go` | verified |  |
| grafana | `apps/iam/pkg/apis/iam/v0alpha1/team_getteammembers_response_body_types_gen.go` | verified |  |
| grafana | `packages/grafana-runtime/src/services/pluginMeta/hooks.tsx` | verified |  |
| grafana | `packages/grafana-schema/src/raw/composable/geomap/panelcfg/x/types.gen.ts` | verified |  |
| grafana | `packages/grafana-ui/src/components/DataLinks/DataLinksInlineEditor/DataLinksListItem.tsx` | verified |  |
| grafana | `packages/grafana-ui/src/components/uPlot/plugins/CloseButton.tsx` | verified |  |
| grafana | `pkg/expr/ml/node.go` | verified |  |
| grafana | `pkg/server/instrumentation_service.go` | verified |  |
| grafana | `pkg/services/auth/idimpl/signer.go` | verified |  |
| grafana | `pkg/services/ngalert/eval/eval_mocks/ConditionEvaluator.go` | verified |  |
| grafana | `pkg/services/ngalert/models/testing.go` | verified |  |
| grafana | `pkg/services/plugindashboards/service/service_test.go` | verified |  |
| grafana | `pkg/services/secrets/kvstore/model.go` | verified |  |
| grafana | `pkg/services/team/teamk8s/team_test.go` | verified |  |
| grafana | `pkg/setting/settingtest/provider_mock.go` | verified |  |
| grafana | `pkg/storage/unified/resource/errors_test.go` | verified |  |
| grafana | `pkg/util/xorm/statement_columnmap.go` | verified |  |
| grafana | `public/app/core/components/PageInfo/PageInfo.tsx` | verified |  |
| grafana | `public/app/features/browse-dashboards/components/NameCell.tsx` | verified |  |
| grafana | `public/app/features/explore/Logs/LogsSamplePanel.tsx` | verified |  |
| grafana | `public/app/features/explore/hooks/useStateSync/index.ts` | verified |  |
| grafana | `public/app/features/provisioning/types/form.ts` | verified |  |
| grafana | `public/app/features/visualization/data-hover/DataHoverView.tsx` | verified |  |
| grafana | `public/app/plugins/datasource/influxdb/fsql/datasource.flightsql.ts` | verified |  |
| prysm | `beacon-chain/blockchain/receive_attestation_test.go` | verified |  |
| prysm | `beacon-chain/db/kv/state_summary_test.go` | verified |  |
| prysm | `beacon-chain/operations/attestations/pool_test.go` | verified |  |
| prysm | `beacon-chain/p2p/types/rpc_goodbye_codes.go` | verified |  |
| prysm | `beacon-chain/state/state-native/getters_participation.go` | verified |  |
| prysm | `beacon-chain/sync/pending_attestations_queue_bucket_test.go` | verified |  |
| prysm | `consensus-types/blocks/execution_payload_envelope_test.go` | verified |  |
| prysm | `proto/prysm/v1alpha1/validator.pb.go` | verified |  |
| prysm | `testing/spectest/mainnet/fulu__epoch_processing__registry_updates_test.go` | verified |  |
| prysm | `testing/spectest/shared/bellatrix/fork/upgrade_to_bellatrix.go` | verified |  |
| prysm | `tools/enr-calculator/main.go` | verified |  |
| prysm | `validator/keymanager/remote-web3signer/internal/log.go` | verified |  |
