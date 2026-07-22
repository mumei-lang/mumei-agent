# Target OSS no-LLM dogfooding audit — continuation 315 (batch 316)

Run: 2026-07-22T18:59:32.019394+00:00

## Summary

- Files audited: 50
- Verified: 50
- Refuted: 0
- Unverifiable: 0

All sampled files passed no-LLM verification; no new tool-side fixes were required.

## Sample details

| repo | file | status | notes |
|------|------|--------|-------|
| go | `src/cmd/go/internal/lockedfile/lockedfile_filelock.go` | verified |  |
| go | `src/cmd/go/internal/telemetrycmd/telemetry.go` | verified |  |
| go | `src/cmd/link/internal/ld/deadcode_test.go` | verified |  |
| go | `src/crypto/internal/fips140/nistec/fiat/p384_fiat64.go` | verified |  |
| go | `src/crypto/sha256/sha256_test.go` | verified |  |
| go | `test/const7.go` | verified |  |
| go | `test/fixedbugs/bug353.go` | verified |  |
| go | `test/fixedbugs/issue12677.dir/p.go` | verified |  |
| go | `test/fixedbugs/issue29612.go` | verified |  |
| go | `test/fixedbugs/issue62203.go` | verified |  |
| go | `test/fixedbugs/issue6405.go` | verified |  |
| go | `test/fixedbugs/issue7346.go` | verified |  |
| go | `test/initexp.go` | verified |  |
| go | `test/inline_caller.go` | verified |  |
| go | `test/shift3.go` | verified |  |
| go | `test/typeparam/issue48280.dir/main.go` | verified |  |
| grafana | `apps/collections/pkg/apis/collections/v1alpha1/stars_test.go` | verified |  |
| grafana | `apps/playlist/pkg/apis/playlist/v1/playlist_status_gen.go` | verified |  |
| grafana | `apps/secret/pkg/apis/secret/v1beta1/keeper_spec_gen.go` | verified |  |
| grafana | `packages/grafana-api-clients/src/utils/backendSrv.mock.ts` | verified |  |
| grafana | `packages/grafana-ui/src/components/Forms/InlineLabel.tsx` | verified |  |
| grafana | `packages/grafana-ui/src/components/uPlot/config/UPlotScaleBuilder.ts` | verified |  |
| grafana | `pkg/apis/iam/v0alpha1/zz_generated.deepcopy.go` | verified |  |
| grafana | `pkg/infra/filestorage/wrapper_test.go` | verified |  |
| grafana | `pkg/plugins/backendplugin/ifaces.go` | verified |  |
| grafana | `pkg/plugins/manager/loader/angular/angulardetector/angulardetector.go` | verified |  |
| grafana | `pkg/registry/apis/iam/globalrole/inmemory/rest.go` | verified |  |
| grafana | `pkg/services/authn/clients/proxy_test.go` | verified |  |
| grafana | `pkg/services/dashboardsnapshots/models.go` | verified |  |
| grafana | `pkg/services/folder/folderimpl/unifiedstore.go` | verified |  |
| grafana | `pkg/services/ngalert/notifier/status.go` | verified |  |
| grafana | `pkg/services/ngalert/provisioning/contactpoints_test.go` | verified |  |
| grafana | `pkg/services/ssosettings/database/database.go` | verified |  |
| grafana | `pkg/storage/unified/parquet/reader.go` | verified |  |
| grafana | `pkg/tests/apis/provisioning/jobs/jobs_validation_test.go` | verified |  |
| grafana | `public/app/features/panel/components/VizTypePicker/VisualizationSuggestionCard.tsx` | verified |  |
| grafana | `public/app/features/provisioning/Wizard/ConnectPage.tsx` | verified |  |
| grafana | `public/app/features/provisioning/utils/managedResource.ts` | verified |  |
| grafana | `public/app/plugins/datasource/loki/components/stats.ts` | verified |  |
| grafana | `public/app/plugins/panel/state-timeline/StateTimelinePanel.tsx` | verified |  |
| prysm | `beacon-chain/core/helpers/private_access_fuzz_noop_test.go` | verified |  |
| prysm | `beacon-chain/execution/engine_client_fuzz_test.go` | verified |  |
| prysm | `beacon-chain/execution/log_processing_test.go` | verified |  |
| prysm | `beacon-chain/light-client/log.go` | verified |  |
| prysm | `beacon-chain/sync/subscriber_data_column_sidecar_test.go` | verified |  |
| prysm | `proto/eth/v1/validator.pb.go` | verified |  |
| prysm | `testing/spectest/minimal/phase0__shuffling__core_shuffle_test.go` | verified |  |
| prysm | `testing/spectest/shared/common/forkchoice/builder_test.go` | verified |  |
| prysm | `validator/client/beacon-api/execution_payload_envelope_test.go` | verified |  |
| prysm | `validator/client/beacon-api/mock/duties_mock.go` | verified |  |
