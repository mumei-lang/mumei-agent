# Target OSS no-LLM dogfooding audit — continuation 283 (batch 284)

Run: 2026-07-22T17:01:14.847327+00:00

## Summary

- Files audited: 50
- Verified: 50
- Refuted: 0
- Unverifiable: 0

All sampled files passed no-LLM verification; no new tool-side fixes were required.

## Sample details

| repo | file | status | notes |
|------|------|--------|-------|
| go | `src/archive/tar/format.go` | verified |  |
| go | `src/cmd/compile/internal/ssagen/abi.go` | verified |  |
| go | `src/cmd/compile/internal/types2/validtype.go` | verified |  |
| go | `src/cmd/test2json/signal_notunix.go` | verified |  |
| go | `src/crypto/internal/fips140/aes/cast.go` | verified |  |
| go | `src/mime/multipart/readmimeheader.go` | verified |  |
| go | `src/net/netip/export_test.go` | verified |  |
| go | `src/os/exec/internal/fdtest/exists_unix.go` | verified |  |
| go | `src/simd/archsimd/ops_wasm.go` | verified |  |
| go | `src/simd/tofrom_wasm.go` | verified |  |
| go | `src/syscall/zsysnum_solaris_amd64.go` | verified |  |
| go | `test/fixedbugs/bug080.go` | verified |  |
| go | `test/fixedbugs/issue19678.go` | verified |  |
| go | `test/typeparam/typeswitch1.go` | verified |  |
| grafana | `apps/example/pkg/apis/example/v1alpha1/example_status_gen.go` | verified |  |
| grafana | `apps/provisioning/pkg/connection/mutator_test.go` | verified |  |
| grafana | `apps/provisioning/pkg/repository/factory.go` | verified |  |
| grafana | `packages/grafana-alerting/src/grafana/api/notifications/v0alpha1/mocks/handlers/index.ts` | verified |  |
| grafana | `packages/grafana-api-clients/src/clients/rtkq/plugins/v0alpha1/endpoints.gen.ts` | verified |  |
| grafana | `packages/grafana-data/src/transformations/transformers/filterByRefId.ts` | verified |  |
| grafana | `packages/grafana-ui/src/components/CodeMirror/InlineInput.tsx` | verified |  |
| grafana | `packages/grafana-ui/src/components/RadialGauge/RadialArcPath.tsx` | verified |  |
| grafana | `pkg/registry/apis/dashboard/variable_test.go` | verified |  |
| grafana | `pkg/registry/apis/ofrep/http_routes_test.go` | verified |  |
| grafana | `pkg/registry/apps/annotation/grpc_store_test.go` | verified |  |
| grafana | `pkg/services/apikey/apikeyimpl/store_test.go` | verified |  |
| grafana | `pkg/services/folder/folderimpl/access_control_test.go` | verified |  |
| grafana | `pkg/services/folder/folderimpl/folder_unifiedstorage_test.go` | verified |  |
| grafana | `pkg/services/ngalert/accesscontrol/receivers_test.go` | verified |  |
| grafana | `pkg/services/ngalert/eval/eval.go` | verified |  |
| grafana | `pkg/services/ngalert/schedule/metrics.go` | verified |  |
| grafana | `pkg/services/ngalert/writer/datasourcewriter_test.go` | verified |  |
| grafana | `pkg/storage/unified/resource/document.go` | verified |  |
| grafana | `pkg/storage/unified/resource/tenant_deleter_test.go` | verified |  |
| grafana | `pkg/tests/apis/provisioning/quota/exportjob_quota_test.go` | verified |  |
| grafana | `public/app/features/alerting/unified/api/alertRuleApi.ts` | verified |  |
| grafana | `public/app/features/canvas/runtime/frame.tsx` | verified |  |
| grafana | `public/app/features/dashboard-scene/scene/layout-tabs/TabsLayoutManagerRenderer.tsx` | verified |  |
| grafana | `public/app/plugins/datasource/azuremonitor/components/LogsQueryEditor/utils.ts` | verified |  |
| grafana | `public/app/plugins/datasource/azuremonitor/components/shared/Field.tsx` | verified |  |
| prysm | `beacon-chain/blockchain/init_sync_process_block_test.go` | verified |  |
| prysm | `beacon-chain/rpc/prysm/v1alpha1/validator/status.go` | verified |  |
| prysm | `consensus-types/primitives/basis_points.go` | verified |  |
| prysm | `crypto/bls/signature_batch_test.go` | verified |  |
| prysm | `runtime/logging/logrus-prefixed-formatter/prefix-replacements.go` | verified |  |
| prysm | `testing/spectest/mainnet/altair__epoch_processing__eth1_data_reset_test.go` | verified |  |
| prysm | `testing/spectest/mainnet/capella__sanity__slots_test.go` | verified |  |
| prysm | `testing/spectest/minimal/deneb__forkchoice__forkchoice_test.go` | verified |  |
| prysm | `tools/analyzers/modernize/stringscutprefix/analyzer.go` | verified |  |
| prysm | `validator/helpers/node_connection_test.go` | verified |  |
