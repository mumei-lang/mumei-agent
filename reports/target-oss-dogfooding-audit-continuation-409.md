# Target OSS no-LLM dogfooding audit — continuation 409 (batch 410)

Run: 2026-07-23T01:07:06.187329+00:00

## Summary

- Files audited: 50
- Verified: 50
- Refuted: 0
- Unverifiable: 0

All sampled files passed no-LLM verification; no new tool-side fixes were required.

## Sample details

| repo | file | status | notes |
|------|------|--------|-------|
| go | `src/cmd/compile/internal/ssa/rewritePPC64latelower.go` | verified |  |
| go | `src/cmd/internal/objabi/funcid.go` | verified |  |
| go | `src/go/types/typeset_test.go` | verified |  |
| go | `src/internal/asan/noasan.go` | verified |  |
| go | `src/internal/fuzz/encoding_test.go` | verified |  |
| go | `src/internal/poll/fd_plan9.go` | verified |  |
| go | `src/os/export_test.go` | verified |  |
| go | `src/runtime/print.go` | verified |  |
| go | `src/runtime/security_issetugid.go` | verified |  |
| go | `src/sort/search_test.go` | verified |  |
| go | `src/unicode/utf8/utf8.go` | verified |  |
| go | `test/clearfat.go` | verified |  |
| go | `test/fixedbugs/bug386.go` | verified |  |
| go | `test/fixedbugs/bug460.dir/b.go` | verified |  |
| go | `test/fixedbugs/issue19078.go` | verified |  |
| go | `test/fixedbugs/issue19880.go` | verified |  |
| go | `test/fixedbugs/issue49016.dir/b.go` | verified |  |
| go | `test/fixedbugs/issue49016.dir/g.go` | verified |  |
| go | `test/fixedbugs/issue49094.dir/b.go` | verified |  |
| go | `test/fixedbugs/issue63489a.go` | verified |  |
| grafana | `apps/provisioning/pkg/repository/tester.go` | verified |  |
| grafana | `apps/provisioning/pkg/safepath/trie_test.go` | verified |  |
| grafana | `packages/grafana-runtime/src/services/pluginMeta/test-fixtures/config.datasources.ts` | verified |  |
| grafana | `packages/grafana-ui/src/slate-plugins/slate-prism/options.tsx` | verified |  |
| grafana | `pkg/api/org_test.go` | verified |  |
| grafana | `pkg/registry/apis/provisioning/resources/retry_client_test.go` | verified |  |
| grafana | `pkg/registry/apis/secret/decrypt/service_test.go` | verified |  |
| grafana | `pkg/server/instrumentation_service_test.go` | verified |  |
| grafana | `pkg/services/anonymous/anonimpl/client.go` | verified |  |
| grafana | `pkg/services/encryption/provider/cipher_aescfb_test.go` | verified |  |
| grafana | `pkg/services/ngalert/remote/mock/remoteAlertmanager.go` | verified |  |
| grafana | `pkg/services/star/starimpl/xorm_store.go` | verified |  |
| grafana | `pkg/tests/apis/provisioning/disabledfeatures_test.go` | verified |  |
| grafana | `pkg/tests/apis/provisioning/foldermetadata/folder_file_protection_test.go` | verified |  |
| grafana | `pkg/tsdb/influxdb/fsql/fsql_test.go` | verified |  |
| grafana | `pkg/util/testutil/mocks/T.go` | verified |  |
| grafana | `public/app/core/components/NestedFolderPicker/useFoldersQueryLegacy.ts` | verified |  |
| grafana | `public/app/features/alerting/unified/components/contact-points/EditContactPoint.tsx` | verified |  |
| grafana | `public/app/features/alerting/unified/components/receivers/form/fields/TemplateSelector.tsx` | verified |  |
| grafana | `public/app/features/alerting/unified/insights/grafana/alertmanager/AlertsByState.tsx` | verified |  |
| grafana | `public/app/features/alerting/unified/utils/redux.ts` | verified |  |
| grafana | `public/app/features/connections/components/ConnectionsRedirectNotice/ConnectionsRedirectNotice.tsx` | verified |  |
| grafana | `public/app/features/dashboard-scene/scene/DashboardLinksControls.tsx` | verified |  |
| grafana | `public/app/features/explore/Logs/PopoverMenu.tsx` | verified |  |
| grafana | `public/app/features/library-panels/styles.ts` | verified |  |
| grafana | `public/app/features/variables/textbox/TextBoxVariablePicker.tsx` | verified |  |
| grafana | `public/app/plugins/datasource/cloudwatch/components/QueryEditor/LogsQueryEditor/code-editors/LogsQLCodeEditor.tsx` | verified |  |
| grafana | `public/app/plugins/datasource/grafana-testdata-datasource/components/FlakyQueryEditor.tsx` | verified |  |
| grafana | `public/app/plugins/datasource/influxdb/components/editor/config-v2/ConfigEditor.tsx` | verified |  |
| grafana | `public/app/plugins/datasource/loki/jest-setup.js` | verified |  |
