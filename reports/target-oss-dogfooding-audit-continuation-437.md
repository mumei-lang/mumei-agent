# Target OSS no-LLM dogfooding audit — continuation 437 (batch 438)

Run: 2026-07-23T02:18:34.763412+00:00

## Summary

- Files audited: 50
- Verified: 50
- Refuted: 0
- Unverifiable: 0

All sampled files passed no-LLM verification; no new tool-side fixes were required.

## Sample details

| repo | file | status | notes |
|------|------|--------|-------|
| go | `src/bytes/compare_test.go` | verified |  |
| go | `src/cmd/compile/internal/ssa/loopreschedchecks.go` | verified |  |
| go | `src/cmd/compile/internal/ssa/nilcheck_test.go` | verified |  |
| go | `src/cmd/go/internal/auth/gitauth.go` | verified |  |
| go | `src/crypto/des/cipher.go` | verified |  |
| go | `src/crypto/sha512/sha512_test.go` | verified |  |
| go | `src/internal/stringslite/strings.go` | verified |  |
| go | `src/internal/syscall/windows/at_windows_test.go` | verified |  |
| go | `src/net/http/internal/http2/connframes_test.go` | verified |  |
| go | `src/net/http/internal/http2/http2_test.go` | verified |  |
| go | `src/os/wait6_netbsd.go` | verified |  |
| go | `src/runtime/callers_test.go` | verified |  |
| go | `src/runtime/cgo/cgo.go` | verified |  |
| go | `src/syscall/netlink_linux.go` | verified |  |
| go | `test/fixedbugs/issue15895.go` | verified |  |
| go | `test/fixedbugs/issue63505.go` | verified |  |
| go | `test/mergemul.go` | verified |  |
| go | `test/typeparam/issue49893.go` | verified |  |
| grafana | `apps/dashboard/pkg/migration/schemaversion/v35_test.go` | verified |  |
| grafana | `apps/example/plugin/src/generated/example/v0alpha1/types.status.gen.ts` | verified |  |
| grafana | `apps/iam/pkg/apis/iam/v0alpha1/globalrolebinding_client_gen.go` | verified |  |
| grafana | `apps/iam/pkg/apis/iam/v0alpha1/team_object_gen.go` | verified |  |
| grafana | `packages/grafana-data/src/transformations/matchers/nameMatcher.ts` | verified |  |
| grafana | `packages/grafana-sql/src/SQLVariableSupport.ts` | verified |  |
| grafana | `packages/grafana-ui/src/components/FeatureBadge/FeatureBadge.tsx` | verified |  |
| grafana | `pkg/components/imguploader/gcs/gcsuploader_test.go` | verified |  |
| grafana | `pkg/models/usertoken/user_token.go` | verified |  |
| grafana | `pkg/registry/apis/folders/cascade_delete.go` | verified |  |
| grafana | `pkg/registry/apis/provisioning/resources/repository.go` | verified |  |
| grafana | `pkg/services/accesscontrol/middleware.go` | verified |  |
| grafana | `pkg/services/ldap/api/support_bundle.go` | verified |  |
| grafana | `pkg/services/ngalert/models/alert_query_test.go` | verified |  |
| grafana | `pkg/services/ngalert/models/receivers_test.go` | verified |  |
| grafana | `pkg/services/ssosettings/errors.go` | verified |  |
| grafana | `pkg/services/ssosettings/ssosettingstests/store_fake.go` | verified |  |
| grafana | `pkg/services/updatemanager/plugins.go` | verified |  |
| grafana | `pkg/storage/unified/informer/store.go` | verified |  |
| grafana | `pkg/tests/api/alerting/api_testing_test.go` | verified |  |
| grafana | `pkg/tests/apis/provisioning/foldermetadata/incremental/incremental_invalid_folder_metadata_test.go` | verified |  |
| grafana | `pkg/util/testutil/context_test.go` | verified |  |
| grafana | `public/app/features/actions/ActionEditorModalContent.tsx` | verified |  |
| grafana | `public/app/features/correlations/Forms/ConfigureCorrelationSourceForm.tsx` | verified |  |
| grafana | `public/app/features/dashboard-scene/panel-edit/PanelEditNext/QueryEditor/StackedEditor/useStackedItemScroll.ts` | verified |  |
| grafana | `public/app/features/dashboard/services/performanceConstants.ts` | verified |  |
| grafana | `public/app/features/dimensions/editors/TextDimensionEditor.tsx` | verified |  |
| grafana | `public/app/features/explore/TraceView/components/CriticalPath/testCases/test2.ts` | verified |  |
| grafana | `public/app/features/live/info.ts` | verified |  |
| grafana | `public/app/plugins/datasource/graphite/configuration/MappingsHelp.tsx` | verified |  |
| grafana | `public/app/plugins/panel/geomap/layers/data/markersLayer.tsx` | verified | No Mumei atoms were generated from the extracted forge task spec. |
| grafana | `public/app/plugins/panel/geomap/migrations.ts` | verified |  |
