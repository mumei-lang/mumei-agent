# Target OSS no-LLM dogfooding audit — continuation 457 (batch 458)

Run: 2026-07-23T03:45:00.991347+00:00

## Summary

- Files audited: 50
- Verified: 50
- Refuted: 0
- Unverifiable: 0

All sampled files passed no-LLM verification; no new tool-side fixes were required.

## Sample details

| repo | file | status | notes |
|------|------|--------|-------|
| go | `src/cmd/compile/internal/amd64/ssa.go` | verified |  |
| go | `src/crypto/ecdh/nist.go` | verified |  |
| go | `src/crypto/internal/fips140/sha512/sha512.go` | verified |  |
| go | `src/encoding/json/indent.go` | verified |  |
| go | `src/encoding/json/jsontext/fuzz_test.go` | verified |  |
| go | `src/image/draw/draw.go` | verified |  |
| go | `src/net/http/triv.go` | verified |  |
| go | `src/runtime/metrics.go` | verified |  |
| go | `src/runtime/rand_test.go` | verified |  |
| go | `src/runtime/runtime_linux_test.go` | verified |  |
| go | `src/runtime/runtime_test.go` | verified |  |
| go | `src/runtime/signal_darwin.go` | verified |  |
| go | `src/runtime/signal_riscv64.go` | verified |  |
| go | `src/runtime/start_line_amd64_test.go` | verified |  |
| go | `test/fixedbugs/bug282.go` | verified |  |
| go | `test/fixedbugs/issue18595.go` | verified |  |
| go | `test/typeparam/absdiffimp.dir/a.go` | verified |  |
| grafana | `apps/dashboard/pkg/apis/dashboard/v2beta1/variable_schema_gen.go` | verified |  |
| grafana | `apps/provisioning/pkg/generated/applyconfiguration/provisioning/v0alpha1/repositoryspec.go` | verified |  |
| grafana | `packages/grafana-alerting/tests/test-utils.tsx` | verified |  |
| grafana | `packages/grafana-data/src/types/slider.ts` | verified |  |
| grafana | `packages/grafana-runtime/src/utils/rbac.ts` | verified |  |
| grafana | `packages/grafana-ui/src/components/Forms/Legacy/Switch/Switch.tsx` | verified |  |
| grafana | `pkg/registry/apis/preferences/legacy/sql.go` | verified |  |
| grafana | `pkg/registry/apis/query/query_test.go` | verified |  |
| grafana | `pkg/registry/apis/secret/xkube/annotations.go` | verified |  |
| grafana | `pkg/registry/apps/annotation/authz.go` | verified |  |
| grafana | `pkg/services/annotations/annotationsapi/handler_test.go` | verified |  |
| grafana | `pkg/services/contexthandler/contexthandler.go` | verified |  |
| grafana | `pkg/services/dsquerierclient/qs_datasource_client_builder.go` | verified |  |
| grafana | `pkg/services/ngalert/folder_consumer.go` | verified |  |
| grafana | `pkg/services/ngalert/notifier/org_email_validator_test.go` | verified |  |
| grafana | `pkg/services/store/kind/dashboard/ds_lookup.go` | verified |  |
| grafana | `pkg/setting/setting_folder_test.go` | verified |  |
| grafana | `pkg/storage/unified/search/embed/embedder/batch_embedder.go` | verified |  |
| grafana | `pkg/tests/apis/provisioning/maxfilesize/helper_test.go` | verified |  |
| grafana | `pkg/tsdb/azuremonitor/utils/utils.go` | verified |  |
| grafana | `pkg/tsdb/graphite/standalone/datasource.go` | verified |  |
| grafana | `pkg/util/proxyutil/reverse_proxy.go` | verified |  |
| grafana | `public/app/features/alerting/unified/components/extensions/AlertingRuleQueryExtensionPoint.tsx` | verified |  |
| grafana | `public/app/features/alerting/unified/components/notification-policies/utils.ts` | verified |  |
| grafana | `public/app/features/alerting/unified/insights/mimir/perGroup/RulesPerGroupScene.tsx` | verified |  |
| grafana | `public/app/features/alerting/unified/mocks/server/handlers/plugins/grafana-oncall.ts` | verified |  |
| grafana | `public/app/features/dashboard-scene/settings/variables/editors/ConstantVariableEditor.tsx` | verified |  |
| grafana | `public/app/features/dashboard-scene/v2schema/dashboardSchemaFetcher.ts` | verified |  |
| grafana | `public/app/features/explore/ExplorePaneContainer.tsx` | verified |  |
| grafana | `public/app/features/explore/TraceView/components/model/transform-trace-data.tsx` | verified |  |
| grafana | `public/app/features/provisioning/Repository/DeleteRepositoryButton.tsx` | verified |  |
| grafana | `public/app/features/teams/TeamFolders.tsx` | verified |  |
| grafana | `public/app/plugins/datasource/cloudwatch/components/shared/LogGroups/LogGroupsField.tsx` | verified |  |
