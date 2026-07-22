# Target OSS no-LLM dogfooding audit — continuation 276 (batch 277)

Run: 2026-07-22T16:29:51.696352+00:00

## Summary

- Files audited: 50
- Verified: 50
- Refuted: 0
- Unverifiable: 0

All sampled files passed no-LLM verification; no new tool-side fixes were required.

## Sample details

| repo | file | status | notes |
|------|------|--------|-------|
| go | `src/cmd/link/internal/ld/go_test.go` | verified |  |
| go | `src/encoding/json/v2/example_test.go` | verified |  |
| go | `src/html/template/template.go` | verified |  |
| go | `src/internal/runtime/atomic/atomic_mipsx.go` | verified |  |
| go | `src/net/url/url_test.go` | verified |  |
| go | `src/os/signal/doc.go` | verified |  |
| go | `src/runtime/complex_test.go` | verified |  |
| go | `src/runtime/pinner_test.go` | verified |  |
| go | `src/runtime/start_line_test.go` | verified |  |
| go | `test/fixedbugs/issue29943.go` | verified |  |
| go | `test/fixedbugs/issue32595.dir/a.go` | verified |  |
| go | `test/fixedbugs/issue34577.dir/b.go` | verified |  |
| go | `test/fixedbugs/issue37716.go` | verified |  |
| go | `test/fixedbugs/issue4964.dir/a.go` | verified |  |
| go | `test/typeparam/issue46461b.go` | verified |  |
| grafana | `apps/dashvalidator/pkg/validator/types.go` | verified |  |
| grafana | `apps/example/pkg/apis/example/v1alpha1/getother_request_params_object_gen.go` | verified |  |
| grafana | `apps/provisioning/pkg/apis/auth/author_test.go` | verified |  |
| grafana | `packages/grafana-data/src/dataframe/dimensions.ts` | verified |  |
| grafana | `packages/grafana-ui/src/components/Dropdown/Dropdown.tsx` | verified |  |
| grafana | `packages/grafana-ui/src/components/StatsPicker/pickComboboxLayout.ts` | verified |  |
| grafana | `packages/grafana-ui/src/themes/GlobalStyles/legacySelect.ts` | verified |  |
| grafana | `pkg/apis/datasource/v0alpha1/zz_generated.defaults.go` | verified |  |
| grafana | `pkg/registry/apis/appplugin/sub_proxy.go` | verified |  |
| grafana | `pkg/registry/apis/iam/teambinding/store.go` | verified |  |
| grafana | `pkg/services/accesscontrol/noop_iam_roles_syncer.go` | verified |  |
| grafana | `pkg/services/authz/rbac/models.go` | verified |  |
| grafana | `pkg/services/ngalert/notifier/multiorg_alertmanager_remote_test.go` | verified |  |
| grafana | `pkg/tsdb/influxdb/influxql/converter/converter_test.go` | verified |  |
| grafana | `public/app/features/alerting/unified/components/mute-timings/timezones.tsx` | verified |  |
| grafana | `public/app/features/alerting/unified/components/rule-editor/query-and-alert-condition/useAlertQueryRunner.tsx` | verified |  |
| grafana | `public/app/features/alerting/unified/hooks/useHasInhibitionRules.ts` | verified |  |
| grafana | `public/app/features/dashboard-scene/panel-edit/PanelEditNext/constants.ts` | verified |  |
| grafana | `public/app/features/dashboard-scene/settings/variables/VariableSetEditableElement.tsx` | verified |  |
| grafana | `public/app/features/dashboard/components/DashNav/ShareButton.tsx` | verified |  |
| grafana | `public/app/features/explore/TraceView/utils/transform.ts` | verified |  |
| grafana | `public/app/features/plugins/admin/state/reducer.ts` | verified |  |
| grafana | `public/app/features/profile/routes.tsx` | verified |  |
| grafana | `public/app/features/provisioning/Wizard/hooks/useCreateSyncJob.ts` | verified |  |
| grafana | `public/app/features/search/page/components/columns.tsx` | verified |  |
| prysm | `api/client/beacon/template.go` | verified |  |
| prysm | `beacon-chain/builder/service_test.go` | verified |  |
| prysm | `beacon-chain/operations/slashings/service_new_test.go` | verified |  |
| prysm | `beacon-chain/slasher/process_slashings_test.go` | verified |  |
| prysm | `cmd/validator/slashing-protection/import.go` | verified |  |
| prysm | `consensus-types/blocks/proto_test.go` | verified |  |
| prysm | `monitoring/progress/progress.go` | verified |  |
| prysm | `proto/prysm/v1alpha1/attestation/aggregation/attestations/maxcover.go` | verified |  |
| prysm | `proto/ssz_query/response.ssz.go` | verified |  |
| prysm | `testing/endtoend/components/validator_test.go` | verified |  |
