# Target OSS no-LLM dogfooding audit — continuation 370 (batch 371)

Run: 2026-07-22T22:18:40.735297+00:00

## Summary

- Files audited: 50
- Verified: 50
- Refuted: 0
- Unverifiable: 0

All sampled files passed no-LLM verification; no new tool-side fixes were required.

## Sample details

| repo | file | status | notes |
|------|------|--------|-------|
| go | `src/cmd/link/internal/mips64/obj.go` | verified |  |
| go | `src/crypto/internal/entropy/entropy.go` | verified |  |
| go | `src/crypto/internal/fips140test/alias_test.go` | verified |  |
| go | `src/go/token/tree.go` | verified |  |
| go | `src/hash/crc32/crc32_test.go` | verified |  |
| go | `src/internal/syscall/unix/eaccess.go` | verified |  |
| go | `src/internal/trace/gc_test.go` | verified |  |
| go | `src/runtime/env_posix.go` | verified |  |
| go | `src/runtime/memmove_linux_amd64_test.go` | verified |  |
| go | `src/runtime/stubs_loong64.go` | verified |  |
| go | `src/simd/madd_test.go` | verified |  |
| go | `src/strconv/isprint.go` | verified |  |
| go | `src/sync/atomic/value.go` | verified |  |
| go | `src/syscall/linkname_openbsd.go` | verified |  |
| go | `src/syscall/ztypes_openbsd_arm.go` | verified |  |
| go | `test/fixedbugs/issue36085.dir/b.go` | verified |  |
| go | `test/fixedbugs/issue54959.go` | verified |  |
| go | `test/typeparam/typeswitch3.go` | verified |  |
| grafana | `packages/grafana-data/src/types/alerts.ts` | verified |  |
| grafana | `packages/grafana-data/src/utils/binaryOperators.ts` | verified |  |
| grafana | `packages/grafana-runtime/src/services/pluginExtensions/usePluginFunctions.ts` | verified |  |
| grafana | `packages/grafana-ui/src/components/Carousel/Carousel.tsx` | verified |  |
| grafana | `packages/grafana-ui/src/components/Select/SingleValue.tsx` | verified |  |
| grafana | `pkg/api/admin_encryption.go` | verified |  |
| grafana | `pkg/api/pluginproxy/ds_proxy_test.go` | verified |  |
| grafana | `pkg/plugins/openapi/loader.go` | verified |  |
| grafana | `pkg/registry/apis/dashboard/snapshot/storage_without_create.go` | verified |  |
| grafana | `pkg/services/live/pipeline/frame_output_remote_write.go` | verified |  |
| grafana | `pkg/services/live/pipeline/subscribe_managed_stream.go` | verified |  |
| grafana | `pkg/services/ngalert/store/namespace_test.go` | verified |  |
| grafana | `pkg/services/screenshot/option_test.go` | verified |  |
| grafana | `pkg/services/screenshot/ratelimit_test.go` | verified |  |
| grafana | `pkg/services/sqlstore/migrations/accesscontrol/datasource_drilldown_removal.go` | verified |  |
| grafana | `pkg/storage/unified/resource/pruner.go` | verified |  |
| grafana | `pkg/tests/apis/provisioning/jobs/releaseresourcesjob_auth_test.go` | verified |  |
| grafana | `public/app/core/utils/CorsSharedWorker.ts` | verified |  |
| grafana | `public/app/features/alerting/unified/plugins/useRulePluginLinkExtensions.ts` | verified |  |
| grafana | `public/app/features/alerting/unified/rule-list/components/RuleLocation.tsx` | verified |  |
| grafana | `public/app/features/alerting/unified/utils/access-control.ts` | verified |  |
| grafana | `public/app/features/dashboard-scene/components/DashboardTemplateEditBanner.tsx` | verified |  |
| grafana | `public/app/features/dashboard-scene/serialization/transformSaveModelSchemaV2ToScene.ts` | verified |  |
| grafana | `public/app/features/dashboard-scene/settings/variables/components/SelectionOptionsForm.tsx` | verified |  |
| grafana | `public/app/features/dashboard-scene/settings/version-history/VersionHistoryComparison.tsx` | verified |  |
| grafana | `public/app/features/datasources/components/DataSourceCategories.tsx` | verified |  |
| grafana | `public/app/features/scopes/selector/ScopesTree.tsx` | verified |  |
| grafana | `public/app/plugins/datasource/azuremonitor/components/LogsQueryEditor/AzureCheatSheetModal.tsx` | verified |  |
| grafana | `public/app/plugins/datasource/azuremonitor/components/MetricsQueryEditor/AdvancedResourcePicker.tsx` | verified |  |
| grafana | `public/app/plugins/datasource/cloudwatch/components/shared/LogGroups/LogGroupPrefixInput.tsx` | verified |  |
| grafana | `public/app/plugins/datasource/cloudwatch/utils/datalinks.ts` | verified |  |
| grafana | `public/app/plugins/datasource/loki/components/monaco-query-field/monaco-completion-provider/NeverCaseError.ts` | verified |  |
