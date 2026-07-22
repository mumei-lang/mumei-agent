# Target OSS no-LLM dogfooding audit — continuation 282 (batch 283)

Run: 2026-07-22T16:58:32.951387+00:00

## Summary

- Files audited: 50
- Verified: 50
- Refuted: 0
- Unverifiable: 0

All sampled files passed no-LLM verification; no new tool-side fixes were required.

## Sample details

| repo | file | status | notes |
|------|------|--------|-------|
| go | `src/cmd/go/internal/vcweb/svn.go` | verified |  |
| go | `src/cmd/internal/obj/arm/anames5.go` | verified |  |
| go | `src/cmd/internal/obj/line.go` | verified |  |
| go | `src/cmd/link/script_test.go` | verified |  |
| go | `src/crypto/internal/fips140/sha512/cast.go` | verified |  |
| go | `src/crypto/x509/root_linux_test.go` | verified |  |
| go | `src/encoding/json/internal/jsonflags/flags_test.go` | verified |  |
| go | `src/go/version/version_test.go` | verified |  |
| go | `src/html/template/multi_test.go` | verified |  |
| go | `src/syscall/zsysnum_linux_ppc64.go` | verified |  |
| go | `src/time/sys_plan9.go` | verified |  |
| go | `test/copy1.go` | verified |  |
| go | `test/fixedbugs/bug369.dir/main.go` | verified |  |
| go | `test/fixedbugs/issue19977.go` | verified |  |
| grafana | `apps/advisor/pkg/app/checks/plugincheck/twinmaker_sceneviewer_step_test.go` | verified |  |
| grafana | `apps/dashboard/pkg/apis/dashboard/v1/types.go` | verified |  |
| grafana | `apps/dashboard/pkg/migration/schemaversion/v30.go` | verified |  |
| grafana | `apps/provisioning/pkg/generated/informers/externalversions/generic.go` | verified |  |
| grafana | `packages/grafana-data/src/types/plugin.ts` | verified |  |
| grafana | `packages/grafana-data/src/types/transformations.ts` | verified |  |
| grafana | `packages/grafana-e2e-selectors/src/selectors/index.ts` | verified |  |
| grafana | `packages/grafana-ui/src/components/RadialGauge/constants.ts` | verified |  |
| grafana | `pkg/generated/applyconfiguration/utils.go` | verified |  |
| grafana | `pkg/infra/leaderelection/options.go` | verified |  |
| grafana | `pkg/infra/nats/publisher_test.go` | verified |  |
| grafana | `pkg/infra/usagestats/service/service.go` | verified |  |
| grafana | `pkg/services/featuremgmt/feature_toggle_api/types.go` | verified |  |
| grafana | `pkg/tsdb/graphite/graphite_test.go` | verified |  |
| grafana | `public/app/api/clients/folder/v1beta1/utils.ts` | verified |  |
| grafana | `public/app/core/components/Layers/AddLayerButton.tsx` | verified |  |
| grafana | `public/app/core/lifecycle-hooks.ts` | verified |  |
| grafana | `public/app/features/alerting/unified/components/rule-editor/labels/LabelsFieldInForm.tsx` | verified |  |
| grafana | `public/app/features/alerting/unified/hooks/useRuleSourcesWithRuler.ts` | verified |  |
| grafana | `public/app/features/dashboard-scene/mutation-api/commands/layoutPathResolver.ts` | verified |  |
| grafana | `public/app/features/dashboard-scene/scene/new-toolbar/actions/PlayListStopButton.tsx` | verified |  |
| grafana | `public/app/features/dashboard-scene/scene/types/LayoutParent.ts` | verified |  |
| grafana | `public/app/features/explore/TraceView/components/TraceTimelineViewer/ListView/Positions.tsx` | verified |  |
| grafana | `public/app/plugins/datasource/grafana/components/AnnotationQueryEditor.tsx` | verified |  |
| grafana | `public/app/plugins/panel/dashlist/panelcfg.gen.ts` | verified |  |
| grafana | `scripts/cuj-new.ts` | verified |  |
| prysm | `api/client/event/stream_guard.go` | verified |  |
| prysm | `beacon-chain/cache/subscribed_validators_test.go` | verified |  |
| prysm | `beacon-chain/p2p/sender_test.go` | verified |  |
| prysm | `beacon-chain/state/stateutil/trie_helpers_test.go` | verified |  |
| prysm | `config/params/mainnet_config.go` | verified |  |
| prysm | `consensus-types/interfaces/validator.go` | verified |  |
| prysm | `testing/spectest/mainnet/deneb__operations__bls_to_execution_change_test.go` | verified |  |
| prysm | `testing/spectest/mainnet/deneb__operations__voluntary_exit_test.go` | verified |  |
| prysm | `testing/spectest/minimal/capella__operations__block_header_test.go` | verified |  |
| prysm | `testing/spectest/shared/gloas/fork/upgrade_to_gloas.go` | verified |  |
