# Target OSS no-LLM dogfooding audit — continuation 347 (batch 348)

Run: 2026-07-22T20:58:45.199428+00:00

## Summary

- Files audited: 50
- Verified: 50
- Refuted: 0
- Unverifiable: 0

All sampled files passed no-LLM verification; no new tool-side fixes were required.

## Sample details

| repo | file | status | notes |
|------|------|--------|-------|
| go | `src/cmd/compile/internal/loopvar/loopvar.go` | verified |  |
| go | `src/cmd/go/internal/toolchain/exec.go` | verified |  |
| go | `src/cmd/go/scriptreadme_test.go` | verified |  |
| go | `src/cmd/internal/script/scripttest/readme.go` | verified |  |
| go | `src/compress/flate/inflate.go` | verified |  |
| go | `src/index/suffixarray/sais2.go` | verified |  |
| go | `src/internal/goos/zgoos_solaris.go` | verified |  |
| go | `src/net/http/internal/http2/writesched_roundrobin.go` | verified |  |
| go | `src/runtime/create_file_unix.go` | verified |  |
| go | `src/runtime/heap_test.go` | verified |  |
| go | `src/runtime/os2_plan9.go` | verified |  |
| go | `test/fixedbugs/issue10654.go` | verified |  |
| go | `test/fixedbugs/issue20682.go` | verified |  |
| go | `test/fixedbugs/issue2615.go` | verified |  |
| go | `test/typeparam/issue48602.go` | verified |  |
| grafana | `apps/annotation/pkg/apis/annotation/v0alpha1/creategraphite_response_body_types_gen.go` | verified |  |
| grafana | `apps/provisioning/pkg/apis/auth/access_checker.go` | verified |  |
| grafana | `packages/grafana-data/src/transformations/matchers/refIdMatcher.ts` | verified |  |
| grafana | `packages/grafana-data/src/transformations/transformers/formatString.ts` | verified |  |
| grafana | `packages/grafana-ui/src/components/Tags/Tag.tsx` | verified |  |
| grafana | `pkg/registry/apis/iam/user_org_hooks.go` | verified |  |
| grafana | `pkg/registry/apis/preferences/preferences_merged.go` | verified |  |
| grafana | `pkg/services/authn/clients/form_test.go` | verified |  |
| grafana | `pkg/services/featuremgmt/registry.go` | verified |  |
| grafana | `pkg/services/ngalert/tests/fakes/rules.go` | verified |  |
| grafana | `pkg/services/star/star.go` | verified |  |
| grafana | `public/app/core/components/RolePicker/RolePickerInput.tsx` | verified |  |
| grafana | `public/app/features/alerting/unified/components/receivers/EditReceiverView.tsx` | verified |  |
| grafana | `public/app/features/dashboard-scene/panel-edit/PanelDataPane/TransformationsDrawer.tsx` | verified |  |
| grafana | `public/app/features/dashboard-scene/panel-edit/PanelEditNext/QueryEditor/StackedEditor/useStackedModeOrchestration.ts` | verified |  |
| grafana | `public/app/features/dashboard-scene/settings/version-history/utils.ts` | verified |  |
| grafana | `public/app/features/dashboard/components/PublicDashboardNotAvailable/PublicDashboardNotAvailable.tsx` | verified |  |
| grafana | `public/app/features/invites/SignupInvited.tsx` | verified |  |
| grafana | `public/app/features/plugins/extensions/test-fixtures/config.apps.ts` | verified |  |
| grafana | `public/app/features/transformers/editors/MergeTransformerEditor.tsx` | verified |  |
| grafana | `public/app/features/variables/adhoc/urlParser.ts` | verified |  |
| grafana | `public/app/features/variables/switch/reducer.ts` | verified |  |
| grafana | `public/app/plugins/datasource/azuremonitor/mocks/argResourcePickerResponse.ts` | verified |  |
| grafana | `public/app/plugins/datasource/cloudwatch/mocks/metric-math-test-data/singleLineEmptyQuery.ts` | verified |  |
| grafana | `public/app/plugins/datasource/grafana/components/TimeRegionEditor.tsx` | verified |  |
| prysm | `beacon-chain/db/kv/kv_test.go` | verified |  |
| prysm | `beacon-chain/db/kv/state_hot_snapshots.go` | verified |  |
| prysm | `beacon-chain/execution/deposit_test.go` | verified |  |
| prysm | `beacon-chain/state/stateutil/validator_map_handler.go` | verified |  |
| prysm | `config/params/testutils.go` | verified |  |
| prysm | `testing/spectest/minimal/altair__epoch_processing__registry_updates_test.go` | verified |  |
| prysm | `testing/spectest/minimal/fulu__light_client__single_merkle_proof_test.go` | verified |  |
| prysm | `third_party/go-bip39/wordlists/korean.go` | verified |  |
| prysm | `validator/client/grpc-api/log.go` | verified |  |
| prysm | `validator/client/service.go` | verified |  |
