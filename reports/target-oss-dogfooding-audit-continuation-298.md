# Target OSS no-LLM dogfooding audit — continuation 298 (batch 299)

Run: 2026-07-22T18:04:20.251438+00:00

## Summary

- Files audited: 50
- Verified: 50
- Refuted: 0
- Unverifiable: 0

All sampled files passed no-LLM verification; no new tool-side fixes were required.

## Sample details

| repo | file | status | notes |
|------|------|--------|-------|
| go | `src/cmd/compile/internal/pkginit/init.go` | verified |  |
| go | `src/cmd/compile/internal/walk/closure.go` | verified |  |
| go | `src/cmd/go/internal/tool/tool.go` | verified |  |
| go | `src/cmd/internal/obj/loong64/asm.go` | verified |  |
| go | `src/net/hosts_test.go` | verified |  |
| go | `src/text/template/link_test.go` | verified |  |
| go | `test/fixedbugs/issue10066.dir/a.go` | verified |  |
| go | `test/fixedbugs/issue10284.go` | verified |  |
| go | `test/fixedbugs/issue13337.go` | verified |  |
| go | `test/fixedbugs/issue23116.go` | verified |  |
| go | `test/fixedbugs/issue5614.go` | verified |  |
| go | `test/fixedbugs/issue68415.go` | verified |  |
| go | `test/fixedbugs/issue7525c.go` | verified |  |
| go | `test/linkname.dir/linkname1.go` | verified |  |
| go | `test/rotate1.go` | verified |  |
| grafana | `apps/dashvalidator/pkg/app/validation_test.go` | verified |  |
| grafana | `apps/provisioning/pkg/apis/auth/session_access_checker.go` | verified |  |
| grafana | `apps/provisioning/pkg/generated/applyconfiguration/provisioning/v0alpha1/connectionstatus.go` | verified |  |
| grafana | `apps/provisioning/pkg/generated/clientset/versioned/typed/provisioning/v0alpha1/repository.go` | verified |  |
| grafana | `e2e-playwright/test-plugins/grafana-test-datasource/datasource.ts` | verified |  |
| grafana | `packages/grafana-ui/src/components/DateTimePickers/TimeZonePicker/TimeZoneDescription.tsx` | verified |  |
| grafana | `pkg/infra/filestorage/db_filestorage.go` | verified |  |
| grafana | `pkg/registry/apis/folders/delete_options_test.go` | verified |  |
| grafana | `pkg/registry/apis/iam/team/validate_test.go` | verified |  |
| grafana | `pkg/registry/apps/shorturl/legacy_storage.go` | verified |  |
| grafana | `pkg/services/accesscontrol/resolvers.go` | verified |  |
| grafana | `pkg/services/apiserver/builder/metrics.go` | verified |  |
| grafana | `pkg/services/folder/folderimpl/conversions_test.go` | verified |  |
| grafana | `pkg/services/pluginsintegration/pluginchecker/fake.go` | verified |  |
| grafana | `pkg/storage/unified/resource/app_manifests.go` | verified |  |
| grafana | `public/app/features/alerting/unified/components/rule-editor/alert-rule-form/simplifiedRouting/route-settings/RouteSettings.tsx` | verified |  |
| grafana | `public/app/features/alerting/unified/components/rules/RuleListGroupView.tsx` | verified |  |
| grafana | `public/app/features/alerting/unified/mocks/server/handlers/plugins/configure-plugins.ts` | verified |  |
| grafana | `public/app/features/dashboard-scene/scene/new-toolbar/utils.tsx` | verified |  |
| grafana | `public/app/features/explore/TraceView/components/utils/DraggableManager/DraggableManager.tsx` | verified |  |
| grafana | `public/app/features/migrate-to-cloud/cloud/EmptyState/MigrationStepsPane.tsx` | verified |  |
| grafana | `public/app/features/plugins/admin/components/GetStartedWithPlugin/GetStartedWithApp.tsx` | verified |  |
| grafana | `public/app/features/plugins/extensions/usePluginLinks.tsx` | verified |  |
| grafana | `public/app/features/provisioning/Shared/BranchValidationError.tsx` | verified |  |
| grafana | `public/app/plugins/datasource/influxdb/components/editor/config/ConfigEditor.tsx` | verified |  |
| prysm | `api/server/structs/conversions_block.go` | verified |  |
| prysm | `api/server/structs/conversions_block_execution_test.go` | verified |  |
| prysm | `beacon-chain/core/transition/transition_fuzz_test.go` | verified |  |
| prysm | `cmd/beacon-chain/jwt/log.go` | verified |  |
| prysm | `config/params/opts.go` | verified |  |
| prysm | `testing/spectest/mainnet/bellatrix__light_client__single_merkle_proof_test.go` | verified |  |
| prysm | `testing/spectest/mainnet/capella__epoch_processing__rewards_and_penalties_test.go` | verified |  |
| prysm | `testing/spectest/minimal/gloas__operations__bls_to_execution_change_test.go` | verified |  |
| prysm | `time/slots/countdown_test.go` | verified |  |
| prysm | `validator/rpc/intercepter_test.go` | verified |  |
