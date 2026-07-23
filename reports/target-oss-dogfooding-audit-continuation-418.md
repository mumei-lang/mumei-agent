# Target OSS no-LLM dogfooding audit — continuation 418 (batch 419)

Run: 2026-07-23T01:25:47.787374+00:00

## Summary

- Files audited: 50
- Verified: 50
- Refuted: 0
- Unverifiable: 0

All sampled files passed no-LLM verification; no new tool-side fixes were required.

## Sample details

| repo | file | status | notes |
|------|------|--------|-------|
| go | `src/cmd/asm/internal/asm/pseudo_test.go` | verified |  |
| go | `src/cmd/cgo/internal/testsanitizers/tsan_test.go` | verified |  |
| go | `src/cmd/compile/internal/ssa/_gen/dec64Ops.go` | verified |  |
| go | `src/cmd/compile/internal/syntax/printer.go` | verified |  |
| go | `src/cmd/go/internal/vcweb/vcstest/vcstest.go` | verified |  |
| go | `src/cmd/link/internal/ld/target.go` | verified |  |
| go | `src/context/net_test.go` | verified |  |
| go | `src/internal/zstd/fse.go` | verified |  |
| go | `src/net/dnsconfig.go` | verified |  |
| go | `src/net/http/doc.go` | verified |  |
| go | `src/net/http/server_test.go` | verified |  |
| go | `src/runtime/error.go` | verified |  |
| go | `src/slices/sort_test.go` | verified |  |
| go | `src/syscall/zerrors_openbsd_amd64.go` | verified |  |
| go | `test/fixedbugs/bug159.go` | verified |  |
| go | `test/fixedbugs/issue19555.go` | verified |  |
| go | `test/fixedbugs/issue43164.go` | verified |  |
| go | `test/fixedbugs/issue52590.go` | verified |  |
| go | `test/fixedbugs/issue66663.go` | verified |  |
| go | `test/if.go` | verified |  |
| go | `test/linkname3.go` | verified |  |
| go | `test/typeparam/dictionaryCapture.go` | verified |  |
| grafana | `apps/provisioning/pkg/connection/tester.go` | verified |  |
| grafana | `devenv/docker/blocks/slow_proxy/main.go` | verified |  |
| grafana | `packages/grafana-flamegraph/src/hooks.ts` | verified |  |
| grafana | `packages/grafana-ui/src/components/Table/TableNG/Cells/DataLinksCell.tsx` | verified |  |
| grafana | `pkg/api/folder_test.go` | verified |  |
| grafana | `pkg/generated/listers/service/v0alpha1/expansion_generated.go` | verified |  |
| grafana | `pkg/registry/apis/dashboard/snapshot/migrator/migrator_test.go` | verified |  |
| grafana | `pkg/registry/apis/iam/team/util.go` | verified |  |
| grafana | `pkg/registry/backgroundsvcs/adapter/service.go` | verified |  |
| grafana | `pkg/services/accesscontrol/fixedrolesloader.go` | verified |  |
| grafana | `pkg/services/ngalert/api/provisioning_test.go` | verified |  |
| grafana | `pkg/services/sqlstore/database_config_test.go` | verified |  |
| grafana | `pkg/services/sqlstore/migrations/datasource_mig.go` | verified |  |
| grafana | `pkg/storage/unified/sql/queries.go` | verified |  |
| grafana | `pkg/tests/apis/alerting/notifications/receivers/receiver_test.go` | verified |  |
| grafana | `pkg/tests/apis/dashboard/search_test.go` | verified |  |
| grafana | `pkg/tsdb/azuremonitor/utils/utils_test.go` | verified |  |
| grafana | `public/app/core/utils/richHistoryTypes.ts` | verified |  |
| grafana | `public/app/features/alerting/unified/components/import-to-gma/Wizard/steps.ts` | verified |  |
| grafana | `public/app/features/alerting/unified/group-details/Title.tsx` | verified |  |
| grafana | `public/app/features/alerting/unified/utils/config.ts` | verified |  |
| grafana | `public/app/features/browse-dashboards/api/recentlyViewed.ts` | verified |  |
| grafana | `public/app/features/correlations/components/Wizard/WizardContent.tsx` | verified |  |
| grafana | `public/app/features/dashboard-scene/scene/layouts-shared/DashboardLayoutSelector.tsx` | verified |  |
| grafana | `public/app/features/playlist/utils.ts` | verified |  |
| grafana | `public/app/features/plugins/admin/hooks/usePluginInfo.tsx` | verified |  |
| grafana | `public/app/features/provisioning/Wizard/hooks/useModeOptions.ts` | verified |  |
| grafana | `public/app/features/transformers/fieldToConfigMapping/FieldConfigMappingHandlerArgumentsEditor.tsx` | verified |  |
