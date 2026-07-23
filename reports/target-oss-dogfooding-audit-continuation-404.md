# Target OSS no-LLM dogfooding audit — continuation 404 (batch 405)

Run: 2026-07-23T00:49:36.763296+00:00

## Summary

- Files audited: 50
- Verified: 50
- Refuted: 0
- Unverifiable: 0

All sampled files passed no-LLM verification; no new tool-side fixes were required.

## Sample details

| repo | file | status | notes |
|------|------|--------|-------|
| go | `src/cmd/asm/internal/arch/arch.go` | verified |  |
| go | `src/cmd/compile/internal/syntax/type.go` | verified |  |
| go | `src/crypto/internal/fips140/edwards25519/field/fe_bench_test.go` | verified |  |
| go | `src/crypto/internal/fips140/sha3/cast.go` | verified |  |
| go | `src/internal/strconv/atob.go` | verified |  |
| go | `src/internal/strconv/decimal_test.go` | verified |  |
| go | `src/path/filepath/example_test.go` | verified |  |
| go | `src/runtime/defs_linux.go` | verified |  |
| go | `src/runtime/pprof/pprof_test.go` | verified |  |
| go | `src/runtime/runtime_noclearenv.go` | verified |  |
| go | `src/sync/example_test.go` | verified |  |
| go | `test/fixedbugs/bug444.go` | verified |  |
| go | `test/fixedbugs/issue15281.go` | verified |  |
| go | `test/fixedbugs/issue30041.go` | verified |  |
| go | `test/fixedbugs/issue52871.go` | verified |  |
| go | `test/fixedbugs/issue59338.go` | verified |  |
| go | `test/fixedbugs/issue59411.go` | verified |  |
| go | `test/fixedbugs/issue73309b.go` | verified |  |
| go | `test/solitaire.go` | verified |  |
| grafana | `apps/alerting/rules/pkg/app/util/group_validation.go` | verified |  |
| grafana | `apps/provisioning/pkg/generated/clientset/versioned/typed/provisioning/v0alpha1/fake/fake_historicjob.go` | verified |  |
| grafana | `packages/grafana-data/src/field/decoupleHideFromState.ts` | verified |  |
| grafana | `packages/grafana-data/src/text/markdown.ts` | verified |  |
| grafana | `packages/grafana-data/src/transformations/matchers/valueMatchers/substringMatchers.ts` | verified |  |
| grafana | `packages/grafana-plugin-configs/webpack.config.ts` | verified |  |
| grafana | `pkg/clientauth/providers_test.go` | verified |  |
| grafana | `pkg/cmd/grafana-cli/commands/commandstest/context.go` | verified |  |
| grafana | `pkg/registry/apis/folders/validate.go` | verified |  |
| grafana | `pkg/registry/apis/secret/contracts/clock.go` | verified |  |
| grafana | `pkg/registry/apis/secret/secretkeeper/sqlkeeper/keeper.go` | verified |  |
| grafana | `pkg/services/authz/zanzana/server/reconciler/metrics.go` | verified |  |
| grafana | `pkg/services/authz/zanzana/server/server_mutate_folder_test.go` | verified |  |
| grafana | `pkg/services/ldap/multildap/multildap_test.go` | verified |  |
| grafana | `pkg/services/ngalert/api/prometheus_conversion.go` | verified |  |
| grafana | `pkg/services/ngalert/api/tooling/definitions/alertmanager_validation.go` | verified |  |
| grafana | `pkg/services/notifications/smtp.go` | verified |  |
| grafana | `pkg/storage/unified/sql/db/mocks/Rows.go` | verified |  |
| grafana | `public/app/core/components/NestedFolderPicker/FolderParent.tsx` | verified |  |
| grafana | `public/app/core/journeys/__smoke__/playwright-utils.ts` | verified |  |
| grafana | `public/app/features/alerting/unified/components/receivers/editor/snippets.ts` | verified |  |
| grafana | `public/app/features/alerting/unified/triage/rows/InstanceRow.tsx` | verified |  |
| grafana | `public/app/features/browse-dashboards/components/BrowseActions/DeleteModal.tsx` | verified |  |
| grafana | `public/app/features/dashboard/components/PanelEditor/getFieldOverrideElements.tsx` | verified |  |
| grafana | `public/app/features/dimensions/editors/FileUploader.tsx` | verified |  |
| grafana | `public/app/features/migrate-to-cloud/api/index.ts` | verified |  |
| grafana | `public/app/features/profile/ChangePasswordForm.tsx` | verified |  |
| grafana | `public/app/features/transformers/lookupGazetteer/FieldLookupTransformerEditor.tsx` | verified |  |
| grafana | `public/app/plugins/datasource/grafana-testdata-datasource/components/GrafanaLiveEditor.tsx` | verified |  |
| grafana | `public/app/plugins/datasource/grafana-testdata-datasource/constants.ts` | verified |  |
| grafana | `public/app/plugins/panel/debug/CursorView.tsx` | verified |  |
