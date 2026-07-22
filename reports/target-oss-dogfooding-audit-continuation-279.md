# Target OSS no-LLM dogfooding audit — continuation 279 (batch 280)

Run: 2026-07-22T16:46:52.759579+00:00

## Summary

- Files audited: 50
- Verified: 50
- Refuted: 0
- Unverifiable: 0

All sampled files passed no-LLM verification; no new tool-side fixes were required.

## Sample details

| repo | file | status | notes |
|------|------|--------|-------|
| go | `src/cmd/go/internal/test/flagdefs_test.go` | verified |  |
| go | `src/image/png/fuzz_test.go` | verified |  |
| go | `src/internal/goexperiment/exp_regabiargs_off.go` | verified |  |
| go | `src/internal/goexperiment/exp_runtimefreegc_off.go` | verified |  |
| go | `src/internal/poll/fstatat_unix.go` | verified |  |
| go | `src/internal/trace/event.go` | verified |  |
| go | `src/os/exec/internal/fdtest/exists_plan9.go` | verified |  |
| go | `src/runtime/defs_freebsd_arm64.go` | verified |  |
| go | `test/complit.go` | verified |  |
| go | `test/fixedbugs/issue15920.dir/a.go` | verified |  |
| go | `test/fixedbugs/issue5614.dir/y.go` | verified |  |
| go | `test/fixedbugs/issue56280.go` | verified |  |
| go | `test/typeparam/issue53406.go` | verified |  |
| grafana | `apps/provisioning/pkg/apis/provisioning/v0alpha1/settings.go` | verified |  |
| grafana | `packages/grafana-ui/src/components/Combobox/SuffixIcon.tsx` | verified |  |
| grafana | `packages/grafana-ui/src/components/Combobox/useLatestAsyncCall.ts` | verified |  |
| grafana | `packages/grafana-ui/src/components/uPlot/geometries/EventsCanvas.tsx` | verified |  |
| grafana | `pkg/components/loki/logproto/types.go` | verified |  |
| grafana | `pkg/infra/httpclient/httpclientprovider/host_redirect_validation_middleware.go` | verified |  |
| grafana | `pkg/registry/apis/preferences/validate.go` | verified |  |
| grafana | `pkg/registry/apps/alerting/notifications/templategroup/conversions.go` | verified |  |
| grafana | `pkg/server/module_registerer.go` | verified |  |
| grafana | `pkg/services/pluginsintegration/pluginsettings/pluginsettings.go` | verified |  |
| grafana | `pkg/setting/setting_openfeature.go` | verified |  |
| grafana | `pkg/util/ring/ring_test.go` | verified |  |
| grafana | `pkg/util/xorm/processors.go` | verified |  |
| grafana | `pkg/util/xorm/session.go` | verified |  |
| grafana | `public/app/core/journeys/__test-utils__/journeyTestHarness.ts` | verified |  |
| grafana | `public/app/features/alerting/unified/components/settings/VersionManager.tsx` | verified |  |
| grafana | `public/app/features/alerting/unified/utils/rule-form.ts` | verified |  |
| grafana | `public/app/features/dashboard/dashgrid/DashboardLibrary/CompatibilityBadge.tsx` | verified |  |
| grafana | `public/app/features/explore/RawPrometheus/RawPrometheusContainer.tsx` | verified |  |
| grafana | `public/app/features/provisioning/Migrate/selection.ts` | verified |  |
| grafana | `public/app/features/variables/pickers/OptionsPicker/OptionsPicker.tsx` | verified |  |
| grafana | `public/app/plugins/datasource/azuremonitor/components/LogsQueryBuilder/FuzzySearch.tsx` | verified |  |
| grafana | `public/app/plugins/datasource/azuremonitor/utils/migrateAnnotation.ts` | verified |  |
| grafana | `public/app/plugins/panel/dashlist/utils.ts` | verified |  |
| grafana | `public/app/plugins/panel/geomap/editor/FrameSelectionEditor.tsx` | verified |  |
| grafana | `public/app/plugins/panel/nodeGraph/panelcfg.gen.ts` | verified |  |
| prysm | `beacon-chain/core/peerdas/verification_test.go` | verified |  |
| prysm | `beacon-chain/db/filesystem/data_column_test.go` | verified |  |
| prysm | `beacon-chain/sync/data_column_sidecars.go` | verified |  |
| prysm | `consensus-types/blocks/testing/mutator.go` | verified |  |
| prysm | `proto/prysm/v1alpha1/beacon_chain.pb.go` | verified |  |
| prysm | `testing/spectest/mainnet/fulu__operations__consolidation_test.go` | verified |  |
| prysm | `testing/spectest/minimal/deneb__epoch_processing__slashings_reset_test.go` | verified |  |
| prysm | `testing/spectest/shared/gloas/epoch_processing/eth1_data_reset.go` | verified |  |
| prysm | `testing/util/block_test.go` | verified |  |
| prysm | `validator/client/iface/options.go` | verified |  |
| prysm | `validator/rpc/handlers_slashing_test.go` | verified |  |
