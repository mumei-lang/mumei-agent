# Target OSS no-LLM dogfooding audit — continuation 511 (batch 512)

Run: 2026-07-23T07:25:20.439585+00:00

## Summary

- Files audited: 50
- Verified: 50
- Refuted: 0
- Unverifiable: 0

All sampled files passed no-LLM verification; no new tool-side fixes were required.

## Sample details

| repo | file | status | notes |
|------|------|--------|-------|
| go | `src/cmd/go/internal/mvs/graph.go` | verified |  |
| go | `src/container/ring/ring_test.go` | verified |  |
| go | `src/crypto/boring/notboring_test.go` | verified |  |
| go | `src/crypto/issue21104_test.go` | verified |  |
| go | `src/crypto/mlkem/mlkemtest/mlkemtest.go` | verified |  |
| go | `src/crypto/rsa/boring_test.go` | verified |  |
| go | `src/go/doc/comment.go` | verified |  |
| go | `src/syscall/zerrors_solaris_amd64.go` | verified |  |
| go | `src/syscall/zsyscall_freebsd_arm.go` | verified |  |
| go | `src/testing/synctest/example_test.go` | verified |  |
| go | `test/alias3.dir/a.go` | verified |  |
| go | `test/fixedbugs/bug223.go` | verified |  |
| go | `test/fixedbugs/bug228a.go` | verified |  |
| go | `test/fixedbugs/gcc101994.go` | verified |  |
| go | `test/fixedbugs/issue12133.go` | verified |  |
| go | `test/fixedbugs/issue23311.dir/main.go` | verified |  |
| go | `test/simd/bug3.go` | verified |  |
| go | `test/unsafe_string_data.go` | verified |  |
| grafana | `apps/advisor/pkg/app/checks/plugincheck/deprecation_step.go` | verified |  |
| grafana | `apps/iam/pkg/apis/iam/v0alpha1/team_schema_gen.go` | verified |  |
| grafana | `apps/provisioning/pkg/connection/metrics.go` | verified |  |
| grafana | `apps/provisioning/pkg/generated/applyconfiguration/provisioning/v0alpha1/resourceref.go` | verified |  |
| grafana | `packages/grafana-ui/src/components/Forms/FieldSet.tsx` | verified |  |
| grafana | `packages/grafana-ui/src/components/Table/TableNG/Cells/BarGaugeCell.tsx` | verified |  |
| grafana | `pkg/api/admin_test.go` | verified |  |
| grafana | `pkg/cmd/grafana-cli/commands/upgrade_command.go` | verified |  |
| grafana | `pkg/codegen/jenny_k8_resources.go` | verified |  |
| grafana | `pkg/generated/clientset/versioned/typed/service/v0alpha1/fake/fake_service_client.go` | verified |  |
| grafana | `pkg/registry/apis/provisioning/jobs/perftest/worker_test.go` | verified |  |
| grafana | `pkg/registry/apis/secret/secretkeeper/metrics/metrics.go` | verified |  |
| grafana | `pkg/registry/apps/alerting/notifications/routingtree/authorize.go` | verified |  |
| grafana | `pkg/registry/apps/annotation/metrics_test.go` | verified |  |
| grafana | `pkg/registry/apps/dashvalidator/register.go` | verified |  |
| grafana | `pkg/services/frontend/settings_service.go` | verified |  |
| grafana | `pkg/services/ngalert/api/tooling/definitions/contact_points.go` | verified |  |
| grafana | `pkg/services/ngalert/api/tooling/definitions/testing_test.go` | verified |  |
| grafana | `pkg/services/ngalert/notifier/testreceivers.go` | verified |  |
| grafana | `pkg/storage/unified/resource/kv/kv_test.go` | verified |  |
| grafana | `public/app/core/components/Animations/SlideDown.tsx` | verified |  |
| grafana | `public/app/features/browse-dashboards/utils/notifications.ts` | verified |  |
| grafana | `public/app/features/dashboard-scene/scene/layouts-shared/scrollCanvasElementIntoView.ts` | verified |  |
| grafana | `public/app/features/dashboard-scene/settings/links/utils.ts` | verified |  |
| grafana | `public/app/features/explore/Graph/ExploreGraphLabel.tsx` | verified |  |
| grafana | `public/app/features/logs/components/fieldSelector/getFieldsWithStats.ts` | verified |  |
| grafana | `public/app/features/plugins/extensions/logs/filterTransformation.ts` | verified |  |
| grafana | `public/app/features/profile/UserProfileEditTabs.tsx` | verified |  |
| grafana | `public/app/features/provisioning/Repository/RepositoryActions.tsx` | verified |  |
| grafana | `public/app/features/provisioning/mocks/factories.ts` | verified |  |
| grafana | `public/app/plugins/datasource/graphite/migrations.ts` | verified |  |
| grafana | `public/app/plugins/panel/news/utils.ts` | verified |  |
