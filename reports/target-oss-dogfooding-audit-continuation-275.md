# Target OSS no-LLM dogfooding audit — continuation 275 (batch 276)

Run: 2026-07-22T16:25:33.027046+00:00

## Summary

- Files audited: 50
- Verified: 50
- Refuted: 0
- Unverifiable: 0

All sampled files passed no-LLM verification; no new tool-side fixes were required.

## Sample details

| repo | file | status | notes |
|------|------|--------|-------|
| go | `src/cmd/asm/internal/lex/lex_test.go` | verified |  |
| go | `src/cmd/internal/obj/line_test.go` | verified |  |
| go | `src/crypto/internal/fips140test/cmac_test.go` | verified |  |
| go | `src/debug/macho/macho.go` | verified |  |
| go | `src/go/types/labels.go` | verified |  |
| go | `src/io/fs/readdir_test.go` | verified |  |
| go | `src/simd/archsimd/compare_gen_arm64.go` | verified |  |
| go | `src/simd/internal/bridge/tofrom_emulated.go` | verified |  |
| go | `src/syscall/net.go` | verified |  |
| go | `src/syscall/zsysnum_darwin_arm64.go` | verified |  |
| go | `test/fixedbugs/bug133.dir/bug2.go` | verified |  |
| go | `test/fixedbugs/issue9604b.go` | verified |  |
| go | `test/loopbce.go` | verified |  |
| go | `test/prove_invert_loop_with_unused_iterators.go` | verified |  |
| go | `test/recover2.go` | verified |  |
| go | `test/typeparam/issue45722.go` | verified |  |
| go | `test/wasmexport.go` | verified |  |
| grafana | `apps/iam/pkg/apis/iam/v0alpha1/globalrole_client_gen.go` | verified |  |
| grafana | `packages/grafana-ui/src/components/Forms/FieldContext.ts` | verified |  |
| grafana | `pkg/registry/apis/secret/contracts/inline.go` | verified |  |
| grafana | `pkg/services/dashboards/accesscontrol.go` | verified |  |
| grafana | `pkg/services/live/pipeline/devdata.go` | verified |  |
| grafana | `pkg/services/ngalert/notifier/multiorg_alertmanager.go` | verified |  |
| grafana | `pkg/services/org/orgtest/fake.go` | verified |  |
| grafana | `pkg/services/pluginsintegration/clientmiddleware/contextual_logger_middleware.go` | verified |  |
| grafana | `pkg/services/ssosettings/ssosettingsimpl/metrics.go` | verified |  |
| grafana | `public/app/features/alerting/unified/components/create-folder/CreateNewFolder.tsx` | verified |  |
| grafana | `public/app/features/alerting/unified/components/rule-viewer/tabs/version-history/UpdatedBy.tsx` | verified |  |
| grafana | `public/app/features/alerting/unified/components/silences/SilenceMetadataGrid.tsx` | verified |  |
| grafana | `public/app/features/alerting/unified/components/silences/utils.ts` | verified |  |
| grafana | `public/app/features/alerting/unified/rule-list/components/RuleActionsSkeleton.tsx` | verified |  |
| grafana | `public/app/features/alerting/unified/test/test-utils.ts` | verified |  |
| grafana | `public/app/features/browse-dashboards/api/useRecentlyDeletedStateManager.ts` | verified |  |
| grafana | `public/app/features/connections/tabs/ConnectData/components/PluginContentView.tsx` | verified |  |
| grafana | `public/app/features/dashboard-scene/settings/annotations/AnnotationSetEditableElement.tsx` | verified |  |
| grafana | `public/app/features/dashboard-scene/sharing/ShareButton/share-externally/ShareExternally.tsx` | verified |  |
| grafana | `public/app/features/dashboard/dashgrid/DashboardLibrary/utils/provisionedDashboardHelpers.ts` | verified |  |
| grafana | `public/app/features/explore/TraceView/components/TraceTimelineViewer/SpanDetail/AccordionKeyValues.markers.tsx` | verified |  |
| grafana | `public/app/features/home/DashboardTabs/DashboardTabError.tsx` | verified |  |
| grafana | `public/app/plugins/datasource/azuremonitor/module.ts` | verified |  |
| prysm | `api/apiutil/common_test.go` | verified |  |
| prysm | `beacon-chain/core/electra/transition_test.go` | verified |  |
| prysm | `beacon-chain/verification/initializer_test.go` | verified |  |
| prysm | `crypto/bls/common/mock/interface_mock.go` | verified |  |
| prysm | `io/logs/mock/mock_stream.go` | verified |  |
| prysm | `proto/prysm/v1alpha1/attestation/attestation_utils_test.go` | verified |  |
| prysm | `proto/prysm/v1alpha1/sync_committee.pb.go` | verified |  |
| prysm | `runtime/tos/log.go` | verified |  |
| prysm | `testing/endtoend/components/eth1/transactions_test.go` | verified |  |
| prysm | `testing/spectest/shared/deneb/operations/helpers.go` | verified |  |
