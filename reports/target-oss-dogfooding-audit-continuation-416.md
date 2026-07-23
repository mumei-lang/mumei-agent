# Target OSS no-LLM dogfooding audit — continuation 416 (batch 417)

Run: 2026-07-23T01:22:09.839499+00:00

## Summary

- Files audited: 50
- Verified: 50
- Refuted: 0
- Unverifiable: 0

All sampled files passed no-LLM verification; no new tool-side fixes were required.

## Sample details

| repo | file | status | notes |
|------|------|--------|-------|
| go | `src/cmd/asm/internal/asm/asm.go` | verified |  |
| go | `src/cmd/compile/internal/mips/ssa.go` | verified |  |
| go | `src/cmd/compile/internal/types2/type.go` | verified |  |
| go | `src/cmd/go/internal/gover/version.go` | verified |  |
| go | `src/go/format/format_test.go` | verified |  |
| go | `src/go/types/lookup_test.go` | verified |  |
| go | `src/internal/syscall/unix/fchmodat_other.go` | verified |  |
| go | `src/net/rpc/jsonrpc/client.go` | verified |  |
| go | `src/runtime/os_openbsd_arm64.go` | verified |  |
| go | `src/syscall/ztypes_netbsd_amd64.go` | verified |  |
| go | `test/fixedbugs/bug009.go` | verified |  |
| go | `test/fixedbugs/bug374.go` | verified |  |
| go | `test/fixedbugs/issue22200.go` | verified |  |
| go | `test/fixedbugs/issue43619.go` | verified |  |
| go | `test/fixedbugs/issue4517d.go` | verified |  |
| go | `test/fixedbugs/issue76950.go` | verified |  |
| grafana | `apps/correlations/pkg/app/app.go` | verified |  |
| grafana | `apps/example/plugin/src/generated/example/v1alpha1/types.status.gen.ts` | verified |  |
| grafana | `apps/provisioning/pkg/repository/github/mutator.go` | verified |  |
| grafana | `apps/provisioning/pkg/repository/metrics.go` | verified |  |
| grafana | `e2e-playwright/utils/annotation-api-mock.ts` | verified |  |
| grafana | `packages/grafana-data/src/events/eventFactory.ts` | verified |  |
| grafana | `packages/grafana-ui/src/components/Card/CardContainer.tsx` | verified |  |
| grafana | `packages/grafana-ui/src/components/SingleStatShared/SingleStatBaseOptions.ts` | verified |  |
| grafana | `packages/grafana-ui/src/utils/storybook/StoryExample.tsx` | verified |  |
| grafana | `pkg/components/simplejson/simplejson_test.go` | verified |  |
| grafana | `pkg/registry/apps/annotation/dashboard_folder_lookup.go` | verified |  |
| grafana | `pkg/registry/apps/annotation/memory_store.go` | verified |  |
| grafana | `pkg/services/auth/jwt/key_sets_test.go` | verified |  |
| grafana | `pkg/services/authn/clients/basic.go` | verified |  |
| grafana | `pkg/services/ldap/settings.go` | verified |  |
| grafana | `pkg/services/ngalert/store/image.go` | verified |  |
| grafana | `pkg/services/pluginsintegration/clientmiddleware/caching_middleware_test.go` | verified |  |
| grafana | `pkg/services/store/utils.go` | verified |  |
| grafana | `pkg/tests/api/alerting/api_available_channel_test.go` | verified |  |
| grafana | `public/app/api/clients/provisioning/utils/httpUtils.ts` | verified |  |
| grafana | `public/app/core/components/NestedFolderPicker/useFoldersQuery.ts` | verified |  |
| grafana | `public/app/core/components/VersionHistory/VersionHistoryComparison.tsx` | verified |  |
| grafana | `public/app/features/alerting/unified/components/expressions/util.ts` | verified |  |
| grafana | `public/app/features/alerting/unified/hooks/useAbilities.ts` | verified |  |
| grafana | `public/app/features/alerting/unified/utils/cloud-alertmanager-notifier-types.ts` | verified |  |
| grafana | `public/app/features/dashboard-scene/panel-edit/PanelEditNext/QueryEditor/Sidebar/Alerts/AlertsView.tsx` | verified |  |
| grafana | `public/app/features/dashboard-scene/settings/links/actions.ts` | verified |  |
| grafana | `public/app/features/explore/TraceView/components/CriticalPath/index.tsx` | verified |  |
| grafana | `public/app/features/provisioning/Connection/ConnectionList.tsx` | verified |  |
| grafana | `public/app/features/teams/TeamPages.tsx` | verified |  |
| grafana | `public/app/plugins/datasource/cloudwatch/components/Errors/ThrottlingErrorMessage.tsx` | verified |  |
| grafana | `public/app/plugins/datasource/grafana-testdata-datasource/components/CSVFileEditor.tsx` | verified |  |
| grafana | `public/app/plugins/panel/state-timeline/module.tsx` | verified |  |
| grafana | `scripts/webpack/plugins/FeatureFlaggedSriPlugin.ts` | verified |  |
