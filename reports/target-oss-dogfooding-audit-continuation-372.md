# Target OSS no-LLM dogfooding audit — continuation 372 (batch 373)

Run: 2026-07-22T22:25:25.411468+00:00

## Summary

- Files audited: 50
- Verified: 50
- Refuted: 0
- Unverifiable: 0

All sampled files passed no-LLM verification; no new tool-side fixes were required.

## Sample details

| repo | file | status | notes |
|------|------|--------|-------|
| go | `src/cmd/internal/goobj/objfile_test.go` | verified |  |
| go | `src/crypto/cipher/cbc_test.go` | verified |  |
| go | `src/debug/pe/pe.go` | verified |  |
| go | `src/go/ast/walk.go` | verified |  |
| go | `src/math/bits/bits_test.go` | verified |  |
| go | `src/syscall/lsf_linux.go` | verified |  |
| go | `test/bigmap.go` | verified |  |
| go | `test/fixedbugs/bug401.go` | verified |  |
| go | `test/fixedbugs/bug410.go` | verified |  |
| go | `test/fixedbugs/bug500.go` | verified |  |
| go | `test/fixedbugs/issue11361.go` | verified |  |
| go | `test/fixedbugs/issue14405.go` | verified |  |
| go | `test/fixedbugs/issue23414.go` | verified |  |
| go | `test/fixedbugs/issue28053.dir/main.go` | verified |  |
| go | `test/fixedbugs/issue29329.go` | verified |  |
| go | `test/fixedbugs/issue30476.go` | verified |  |
| go | `test/fixedbugs/issue4370.dir/p1.go` | verified |  |
| go | `test/typeparam/issue50481c.dir/a.go` | verified |  |
| go | `test/typeparam/issue50481c.go` | verified |  |
| grafana | `apps/dashboard/pkg/migration/schemaversion/v14.go` | verified |  |
| grafana | `apps/iam/pkg/apis/iam/v0alpha1/role_codec_gen.go` | verified |  |
| grafana | `apps/provisioning/pkg/apis/admission/admission.go` | verified |  |
| grafana | `e2e-playwright/dashboard-new-layouts/page-objects/sidebar/VariableOptions.ts` | verified |  |
| grafana | `e2e-playwright/test-plugins/grafana-extensionstest-app/plugins/grafana-extensionexample1-app/components/App/index.tsx` | verified |  |
| grafana | `packages/grafana-data/test/index.ts` | verified |  |
| grafana | `packages/grafana-runtime/src/internal/openFeature/index.ts` | verified |  |
| grafana | `pkg/api/ds_query_diagnostics_test.go` | verified |  |
| grafana | `pkg/infra/log/databaseCounter.go` | verified |  |
| grafana | `pkg/infra/slugify/slugify_test.go` | verified |  |
| grafana | `pkg/registry/apis/iam/serviceaccount/mutate_test.go` | verified |  |
| grafana | `pkg/registry/apis/provisioning/jobs/loki_client_mock.go` | verified |  |
| grafana | `pkg/services/accesscontrol/authorizer.go` | verified |  |
| grafana | `pkg/services/accesscontrol/database/cleanup.go` | verified |  |
| grafana | `pkg/services/libraryelements/libraryelements_get_all_test.go` | verified |  |
| grafana | `pkg/services/ngalert/metrics/historian.go` | verified |  |
| grafana | `pkg/services/ngalert/schedule/registry.go` | verified |  |
| grafana | `pkg/services/pluginsintegration/advisor/advisor_test.go` | verified |  |
| grafana | `pkg/services/promtypemigration/azure_prom_mig.go` | verified |  |
| grafana | `pkg/tests/apis/playlist/playlist_test.go` | verified |  |
| grafana | `pkg/tests/apis/provisioning/foldermetadata/folder_title_normalization_test.go` | verified |  |
| grafana | `pkg/util/scheduler/scheduler_bench_test.go` | verified |  |
| grafana | `public/app/api/utils.ts` | verified |  |
| grafana | `public/app/features/alerting/unified/components/mute-timings/useMuteTimings.tsx` | verified |  |
| grafana | `public/app/features/canvas/elements/parallelogram.tsx` | verified |  |
| grafana | `public/app/features/dashboard-scene/scene/types/DashboardDropTarget.ts` | verified |  |
| grafana | `public/app/features/scopes/tests/utils/actions.ts` | verified |  |
| grafana | `public/app/plugins/datasource/cloudwatch/components/CheatSheet/sampleQueries.ts` | verified |  |
| grafana | `public/app/plugins/datasource/cloudwatch/components/ConfigEditor/ConfigEditor.tsx` | verified |  |
| grafana | `public/app/plugins/datasource/cloudwatch/migrations/dashboardMigrations.ts` | verified |  |
| grafana | `public/app/plugins/datasource/graphite/state/store.ts` | verified |  |
