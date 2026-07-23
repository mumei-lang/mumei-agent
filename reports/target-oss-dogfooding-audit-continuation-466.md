# Target OSS no-LLM dogfooding audit — continuation 466 (batch 467)

Run: 2026-07-23T04:24:37.579788+00:00

## Summary

- Files audited: 50
- Verified: 50
- Refuted: 0
- Unverifiable: 0

All sampled files passed no-LLM verification; no new tool-side fixes were required.

## Sample details

| repo | file | status | notes |
|------|------|--------|-------|
| go | `src/cmd/go/internal/imports/scan_test.go` | verified |  |
| go | `src/cmd/link/internal/ld/inittask.go` | verified |  |
| go | `src/crypto/purego_test.go` | verified |  |
| go | `src/go/internal/gccgoimporter/importer_test.go` | verified |  |
| go | `src/runtime/os_workdir_ios_arm64.go` | verified |  |
| go | `src/runtime/pprof/pprof.go` | verified |  |
| go | `src/syscall/zsyscall_linux_mips.go` | verified |  |
| go | `test/closure3.go` | verified |  |
| go | `test/devirtualization_with_type_assertions_interleaved.go` | verified |  |
| go | `test/fixedbugs/bug088.dir/bug1.go` | verified |  |
| go | `test/fixedbugs/bug182.go` | verified |  |
| go | `test/fixedbugs/bug266.go` | verified |  |
| go | `test/fixedbugs/bug306.go` | verified |  |
| go | `test/fixedbugs/issue10700.dir/test.go` | verified |  |
| go | `test/fixedbugs/issue16306.go` | verified |  |
| go | `test/fixedbugs/issue19012.go` | verified |  |
| go | `test/fixedbugs/issue19548.dir/b.go` | verified |  |
| go | `test/fixedbugs/issue33013.dir/a.go` | verified |  |
| go | `test/fixedbugs/issue7648.dir/b.go` | verified |  |
| go | `test/newinline.go` | verified |  |
| go | `test/switch2.go` | verified |  |
| go | `test/tailcall.go` | verified |  |
| grafana | `apps/alerting/notifications/pkg/apis/alertingnotifications/v0alpha1/config_schema_gen.go` | verified |  |
| grafana | `apps/dashboard/pkg/migration/schemaversion/v12_test.go` | verified |  |
| grafana | `apps/iam/pkg/apis/iam/v0alpha1/register.go` | verified |  |
| grafana | `apps/provisioning/pkg/safepath/safe_test.go` | verified |  |
| grafana | `packages/grafana-api-clients/src/clients/rtkq/dashboard/v2beta1/endpoints.gen.ts` | verified |  |
| grafana | `packages/grafana-data/src/transformations/transformers/reduce.ts` | verified |  |
| grafana | `packages/grafana-ui/src/components/Select/utils.ts` | verified |  |
| grafana | `pkg/api/dtos/models.go` | verified |  |
| grafana | `pkg/bus/bus.go` | verified |  |
| grafana | `pkg/infra/httpclient/httpclientprovider/datasource_metrics_middleware.go` | verified |  |
| grafana | `pkg/registry/apis/provisioning/jobs/export/resources_test.go` | verified |  |
| grafana | `pkg/services/authz/rbac/service.go` | verified |  |
| grafana | `pkg/services/libraryelements/libraryelements_provisioned_folder_test.go` | verified |  |
| grafana | `pkg/services/ngalert/models/receivers_diff.go` | verified |  |
| grafana | `pkg/storage/unified/search/builders/document.go` | verified |  |
| grafana | `pkg/storage/unified/search/embed/embedder/end_to_end_integration_test.go` | verified |  |
| grafana | `pkg/storage/unified/search/vector/queries.go` | verified |  |
| grafana | `pkg/tests/apis/provisioning/common/permissions.go` | verified |  |
| grafana | `pkg/util/url_test.go` | verified |  |
| grafana | `pkg/util/xorm/sequence_inmem.go` | verified |  |
| grafana | `public/app/core/components/AppChrome/OrganizationSwitcher/types.ts` | verified |  |
| grafana | `public/app/features/alerting/unified/components/rule-editor/VizWrapper.tsx` | verified |  |
| grafana | `public/app/features/alerting/unified/hooks/useReturnTo.ts` | verified |  |
| grafana | `public/app/features/alerting/unified/mocks/server/db.ts` | verified |  |
| grafana | `public/app/features/dashboard-scene/settings/annotations/AnnotationList.tsx` | verified |  |
| grafana | `public/app/features/logs/components/ControlledLogsTable.tsx` | verified |  |
| grafana | `public/app/features/manage-dashboards/PublicDashboardListPage.tsx` | verified |  |
| grafana | `public/app/features/transformers/FilterByValueTransformer/FilterByValueTransformerEditor.tsx` | verified |  |
