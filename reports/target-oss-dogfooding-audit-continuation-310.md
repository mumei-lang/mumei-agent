# Target OSS no-LLM dogfooding audit — continuation 310 (batch 311)

Run: 2026-07-22T18:46:19.823352+00:00

## Summary

- Files audited: 50
- Verified: 50
- Refuted: 0
- Unverifiable: 0

All sampled files passed no-LLM verification; no new tool-side fixes were required.

## Sample details

| repo | file | status | notes |
|------|------|--------|-------|
| go | `src/cmd/compile/internal/ir/check_reassign_no.go` | verified |  |
| go | `src/cmd/compile/internal/types2/builtins_test.go` | verified |  |
| go | `src/cmd/internal/obj/loong64/instOp.go` | verified |  |
| go | `src/crypto/tls/handshake_server_test.go` | verified |  |
| go | `src/go/printer/example_test.go` | verified |  |
| go | `src/net/http/filetransport.go` | verified |  |
| go | `src/net/timeout_test.go` | verified |  |
| go | `src/os/writeto_linux_test.go` | verified |  |
| go | `src/runtime/netpoll_wasip1.go` | verified |  |
| go | `src/slices/slices.go` | verified |  |
| go | `test/dwarf/dwarf.dir/z1.go` | verified |  |
| go | `test/fixedbugs/issue6269.go` | verified |  |
| go | `test/initcomma.go` | verified |  |
| grafana | `apps/iam/pkg/apis/iam/v0alpha1/getsearchteams_request_params_object_gen.go` | verified |  |
| grafana | `packages/grafana-alerting/src/grafana/notificationPolicies/components/RoutingTreeSelector/RoutingTreeSelector.scenario.ts` | verified |  |
| grafana | `packages/grafana-data/src/dataframe/StreamingDataFrame.ts` | verified |  |
| grafana | `packages/grafana-data/src/transformations/transformers/nulls/nullToValue.ts` | verified |  |
| grafana | `pkg/generated/clientset/versioned/clientset.go` | verified |  |
| grafana | `pkg/registry/apis/preferences/legacy/queries.go` | verified |  |
| grafana | `pkg/registry/apis/query/queryschema/oas_helper.go` | verified |  |
| grafana | `pkg/services/ngalert/remote/remote_primary_forked_alertmanager.go` | verified |  |
| grafana | `pkg/services/provisioning/dashboards/file_reader_symlink_test.go` | verified |  |
| grafana | `pkg/services/screenshot/cache_test.go` | verified |  |
| grafana | `pkg/services/store/storage_disk.go` | verified |  |
| grafana | `pkg/storage/unified/federated/client.go` | verified |  |
| grafana | `pkg/storage/unified/search/embed/embedder/provider/provider.go` | verified |  |
| grafana | `pkg/tsdb/loki/types.go` | verified |  |
| grafana | `public/app/core/components/ColorScale/ColorScale.tsx` | verified |  |
| grafana | `public/app/core/components/PasswordField/PasswordField.tsx` | verified |  |
| grafana | `public/app/features/alerting/unified/components/rule-editor/PreviewRule.tsx` | verified |  |
| grafana | `public/app/features/alerting/unified/hooks/useSyncedUrlDrawerParam.ts` | verified |  |
| grafana | `public/app/features/canvas/elements/droneFront.tsx` | verified |  |
| grafana | `public/app/features/dashboard-scene/conditional-rendering/group/ConditionalRenderingGroupCondition.tsx` | verified |  |
| grafana | `public/app/features/dashboard-scene/panel-edit/PanelEditControls.tsx` | verified |  |
| grafana | `public/app/features/expressions/components/SqlExpressions/SchemaInspector/SchemaInspectorPanel.tsx` | verified |  |
| grafana | `public/app/features/org/state/reducers.ts` | verified |  |
| grafana | `public/app/plugins/datasource/azuremonitor/components/LogsQueryBuilder/LogsQueryBuilder.tsx` | verified |  |
| grafana | `public/app/plugins/datasource/influxdb/components/editor/config-v2/DatabaseConnectionSection.tsx` | verified |  |
| grafana | `public/app/plugins/panel/bargauge/BarGaugePanel.tsx` | verified |  |
| prysm | `beacon-chain/p2p/types/types.go` | verified |  |
| prysm | `beacon-chain/rpc/eth/node/server.go` | verified |  |
| prysm | `beacon-chain/rpc/eth/shared/testing/json.go` | verified |  |
| prysm | `beacon-chain/verification/payload_attestation_mock.go` | verified |  |
| prysm | `cmd/beacon-chain/db/db.go` | verified |  |
| prysm | `consensus-types/blocks/roblock_test.go` | verified |  |
| prysm | `crypto/hash/hash.go` | verified |  |
| prysm | `testing/spectest/mainnet/deneb__operations__withdrawals_test.go` | verified |  |
| prysm | `testing/spectest/mainnet/electra__epoch_processing__effective_balance_updates_test.go` | verified |  |
| prysm | `testing/spectest/shared/gloas/ssz_static/ssz_static.go` | verified |  |
| prysm | `validator/accounts/wallet_create.go` | verified |  |
