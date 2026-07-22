# Target OSS no-LLM dogfooding audit — continuation 351 (batch 352)

Run: 2026-07-22T21:06:11.391428+00:00

## Summary

- Files audited: 50
- Verified: 50
- Refuted: 0
- Unverifiable: 0

All sampled files passed no-LLM verification; no new tool-side fixes were required.

## Sample details

| repo | file | status | notes |
|------|------|--------|-------|
| go | `src/cmd/cover/func.go` | verified |  |
| go | `src/compress/flate/reader_test.go` | verified |  |
| go | `src/html/entity_test.go` | verified |  |
| go | `src/internal/runtime/syscall/linux/syscall_linux_test.go` | verified |  |
| go | `src/math/big/internal/asmgen/asm.go` | verified |  |
| go | `src/math/big/internal/asmgen/pipe.go` | verified |  |
| go | `src/runtime/panic_test.go` | verified |  |
| go | `src/unicode/utf16/export_test.go` | verified |  |
| go | `test/fixedbugs/bug197.go` | verified |  |
| go | `test/fixedbugs/issue19699b.go` | verified |  |
| go | `test/fixedbugs/issue73920.go` | verified |  |
| go | `test/fixedbugs/issue7538a.go` | verified |  |
| go | `test/syntax/semi2.go` | verified |  |
| go | `test/typeparam/issue46461b.dir/b.go` | verified |  |
| go | `test/typeparam/issue50552.dir/a.go` | verified |  |
| grafana | `packages/grafana-api-clients/src/clients/rtkq/correlations/v0alpha1/endpoints.gen.ts` | verified |  |
| grafana | `packages/grafana-data/src/field/scale.ts` | verified |  |
| grafana | `packages/grafana-data/src/text/string.ts` | verified |  |
| grafana | `pkg/api/render.go` | verified |  |
| grafana | `pkg/infra/leaderelection/kvlease/elector_test.go` | verified |  |
| grafana | `pkg/plugins/backendplugin/backendplugin.go` | verified |  |
| grafana | `pkg/registry/apis/collections/stars_update_test.go` | verified |  |
| grafana | `pkg/registry/apis/iam/legacy/user_test.go` | verified |  |
| grafana | `pkg/registry/apis/provisioning/jobs/migrate/clean.go` | verified |  |
| grafana | `pkg/registry/apps/playlist/legacy.go` | verified |  |
| grafana | `pkg/services/accesscontrol/resourcepermissions/models.go` | verified |  |
| grafana | `pkg/services/ngalert/notifier/silence_svc.go` | verified |  |
| grafana | `pkg/services/signingkeys/signingkeystore/store_test.go` | verified |  |
| grafana | `pkg/storage/secret/metadata/query.go` | verified |  |
| grafana | `pkg/storage/unified/search/embed/embedder/bedrock/client.go` | verified |  |
| grafana | `pkg/tsdb/jaeger/querydata.go` | verified |  |
| grafana | `public/app/core/components/Page/PluginPage.tsx` | verified |  |
| grafana | `public/app/features/alerting/unified/components/rules/AlertInstanceDetails.tsx` | verified |  |
| grafana | `public/app/features/alerting/unified/triage/instance-details/InstanceStateInfoBanner.tsx` | verified |  |
| grafana | `public/app/features/dashboard-scene/edit-pane/outline/DashboardOutlineNode.tsx` | verified |  |
| grafana | `public/app/features/explore/extensions/AddToDashboard/index.tsx` | verified |  |
| grafana | `public/app/features/plugins/components/PluginsErrorsInfo.tsx` | verified |  |
| grafana | `public/app/features/variables/adhoc/picker/AdHocFilterKey.tsx` | verified |  |
| grafana | `public/app/plugins/datasource/loki/querybuilder/components/QueryPreview.tsx` | verified |  |
| grafana | `public/app/plugins/panel/xychart/panelcfgold.gen.ts` | verified |  |
| prysm | `api/rest/rest_connection_provider_test.go` | verified |  |
| prysm | `api/server/structs/block_execution.go` | verified |  |
| prysm | `beacon-chain/core/epoch/precompute/slashing_test.go` | verified |  |
| prysm | `beacon-chain/sync/rpc_goodbye_test.go` | verified |  |
| prysm | `container/slice/slice.go` | verified |  |
| prysm | `proto/prysm/v1alpha1/p2p_messages_gloas.pb.go` | verified |  |
| prysm | `proto/prysm/v1alpha1/phase0.minimal.ssz.go` | verified |  |
| prysm | `runtime/fdlimits/fdlimits.go` | verified |  |
| prysm | `validator/client/beacon-api/propose_beacon_block_test.go` | verified |  |
| prysm | `validator/client/beacon-api/subscribe_committee_subnets_test.go` | verified |  |
