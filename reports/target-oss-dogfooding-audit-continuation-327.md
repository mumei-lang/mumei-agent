# Target OSS no-LLM dogfooding audit — continuation 327 (batch 328)

Run: 2026-07-22T19:51:54.767518+00:00

## Summary

- Files audited: 50
- Verified: 50
- Refuted: 0
- Unverifiable: 0

All sampled files passed no-LLM verification; no new tool-side fixes were required.

## Sample details

| repo | file | status | notes |
|------|------|--------|-------|
| go | `src/cmd/go/internal/modload/edit.go` | verified |  |
| go | `src/cmd/internal/sys/args.go` | verified |  |
| go | `src/log/slog/example_logvaluer_secret_test.go` | verified |  |
| go | `src/os/stat_darwin.go` | verified |  |
| go | `src/os/user/listgroups_stub.go` | verified |  |
| go | `src/runtime/debug/garbage_test.go` | verified |  |
| go | `src/runtime/map_fast64.go` | verified |  |
| go | `src/runtime/vdso_elf32.go` | verified |  |
| go | `src/syscall/types_windows.go` | verified |  |
| go | `test/fixedbugs/bug420.go` | verified |  |
| go | `test/fixedbugs/issue19056.go` | verified |  |
| go | `test/fixedbugs/issue49016.dir/f.go` | verified |  |
| go | `test/fixedbugs/issue5753.go` | verified |  |
| grafana | `apps/alerting/rules/pkg/apis/alerting/v0alpha1/alertrule_client_gen.go` | verified |  |
| grafana | `apps/plugins/pkg/apis/plugins/v0alpha1/plugin_object_gen.go` | verified |  |
| grafana | `apps/secret/pkg/apis/secret/v1beta1/securevalue_codec_gen.go` | verified |  |
| grafana | `packages/grafana-api-clients/src/clients/rtkq/folder/v1beta1/baseAPI.ts` | verified |  |
| grafana | `packages/grafana-test-utils/src/fixtures/preferences.ts` | verified |  |
| grafana | `packages/grafana-ui/src/components/RadialGauge/colors.ts` | verified |  |
| grafana | `pkg/registry/apis/iam/common/common.go` | verified |  |
| grafana | `pkg/services/apiserver/builder/openapi_test.go` | verified |  |
| grafana | `pkg/services/authn/authnimpl/usage_stats.go` | verified |  |
| grafana | `pkg/services/authz/rbac/store/store.go` | verified |  |
| grafana | `pkg/services/ngalert/evaluation_runner_test.go` | verified |  |
| grafana | `pkg/services/pluginsintegration/loader/loader.go` | verified |  |
| grafana | `public/app/features/admin/ldap/LdapGroupMapping.tsx` | verified |  |
| grafana | `public/app/features/alerting/unified/components/rules/Filter/RulesFilter.v1.tsx` | verified |  |
| grafana | `public/app/features/alerting/unified/testSetup/plugins.ts` | verified |  |
| grafana | `public/app/features/dashboard-scene/settings/variables/components/DataSourceVariableForm.tsx` | verified |  |
| grafana | `public/app/features/dashboard-scene/settings/variables/editors/SwitchVariableEditor.tsx` | verified |  |
| grafana | `public/app/features/dashboard-scene/utils/djb2Hash.ts` | verified |  |
| grafana | `public/app/features/dashboard/dashgrid/DashboardLibrary/SuggestedDashboardsModal.tsx` | verified |  |
| grafana | `public/app/features/dimensions/editors/FolderPickerTab.tsx` | verified |  |
| grafana | `public/app/features/explore/TraceView/components/TraceTimelineViewer/Ticks.tsx` | verified |  |
| grafana | `public/app/features/explore/hooks/useStateSync/migrators/v1.ts` | verified |  |
| grafana | `public/app/features/logs/utils.ts` | verified |  |
| grafana | `public/app/features/plugins/extensions/registry/AddedComponentsRegistry.ts` | verified |  |
| grafana | `public/app/features/transformers/calculateHeatmap/utils.ts` | verified |  |
| grafana | `public/app/features/users/state/selectors.ts` | verified |  |
| grafana | `public/app/features/variables/shared/testing/datasourceVariableBuilder.ts` | verified |  |
| prysm | `beacon-chain/db/kv/migration_archived_index.go` | verified |  |
| prysm | `beacon-chain/node/registration/p2p_test.go` | verified |  |
| prysm | `beacon-chain/p2p/discovery.go` | verified |  |
| prysm | `beacon-chain/state/stategen/cacher.go` | verified |  |
| prysm | `beacon-chain/sync/pending_payload_envelope_test.go` | verified |  |
| prysm | `encoding/ssz/query/tag_parser.go` | verified |  |
| prysm | `proto/migration/enums.go` | verified |  |
| prysm | `testing/spectest/shared/deneb/operations/withdrawals.go` | verified |  |
| prysm | `testing/spectest/shared/phase0/operations/helpers.go` | verified |  |
| prysm | `validator/db/common/structs.go` | verified |  |
