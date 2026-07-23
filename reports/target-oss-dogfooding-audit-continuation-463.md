# Target OSS no-LLM dogfooding audit — continuation 463 (batch 464)

Run: 2026-07-23T04:07:43.423324+00:00

## Summary

- Files audited: 50
- Verified: 50
- Refuted: 0
- Unverifiable: 0

All sampled files passed no-LLM verification; no new tool-side fixes were required.

## Sample details

| repo | file | status | notes |
|------|------|--------|-------|
| go | `src/cmd/compile/internal/ir/package.go` | verified |  |
| go | `src/cmd/go/internal/toolchain/path_plan9.go` | verified |  |
| go | `src/cmd/link/internal/ld/outbuf_linux.go` | verified |  |
| go | `src/crypto/ecdsa/ecdsa.go` | verified |  |
| go | `src/image/internal/imageutil/imageutil.go` | verified |  |
| go | `src/internal/runtime/gc/scan/mem_unix_test.go` | verified |  |
| go | `src/internal/zstd/window_test.go` | verified |  |
| go | `src/runtime/coro_test.go` | verified |  |
| go | `src/runtime/signal_netbsd_arm.go` | verified |  |
| go | `src/sync/waitgroup.go` | verified |  |
| go | `test/closure5.go` | verified |  |
| go | `test/fixedbugs/bug252.go` | verified |  |
| go | `test/fixedbugs/bug516.go` | verified |  |
| go | `test/fixedbugs/issue13559.go` | verified |  |
| go | `test/fixedbugs/issue23522.go` | verified |  |
| go | `test/fixedbugs/issue35586.dir/a.go` | verified |  |
| go | `test/fixedbugs/issue5291.dir/prog.go` | verified |  |
| go | `test/fixedbugs/issue5755.go` | verified |  |
| go | `test/fixedbugs/issue6750.go` | verified |  |
| go | `test/typeparam/issue47929.go` | verified |  |
| grafana | `apps/dashvalidator/pkg/apis/dashvalidator/v1alpha1/dashboardcompatibilityscore_codec_gen.go` | verified |  |
| grafana | `apps/dashvalidator/pkg/validator/benchmark_test.go` | verified |  |
| grafana | `apps/folder/pkg/apis/folder/v1/folder_object_gen.go` | verified |  |
| grafana | `apps/iam/pkg/apis/iam/v0alpha1/teamlbacrule_schema_gen.go` | verified |  |
| grafana | `apps/provisioning/pkg/apis/provisioning/v0alpha1/webhook.go` | verified |  |
| grafana | `packages/grafana-i18n/src/dates.ts` | verified |  |
| grafana | `packages/grafana-ui/src/components/Slider/styles.ts` | verified |  |
| grafana | `pkg/apis/iam/v0alpha1/types_display.go` | verified |  |
| grafana | `pkg/infra/log/interface.go` | verified |  |
| grafana | `pkg/infra/remotecache/test_utils.go` | verified |  |
| grafana | `pkg/registry/apis/iam/user/legacy_search.go` | verified |  |
| grafana | `pkg/registry/apis/ofrep/publicflags.go` | verified |  |
| grafana | `pkg/registry/apis/provisioning/jobs/migrate/worker_test.go` | verified |  |
| grafana | `pkg/services/accesscontrol/resourcepermissions/api.go` | verified |  |
| grafana | `pkg/services/apiserver/restcfg/restcfg.go` | verified |  |
| grafana | `pkg/services/ngalert/notifier/receiver_svc.go` | verified |  |
| grafana | `pkg/services/sqlstore/migrations/stats_mig.go` | verified |  |
| grafana | `pkg/services/team/teamapi/api.go` | verified |  |
| grafana | `pkg/services/updatemanager/plugins_test.go` | verified |  |
| grafana | `pkg/util/scheduler/scheduler.go` | verified |  |
| grafana | `public/app/core/journeys/utils.ts` | verified |  |
| grafana | `public/app/features/alerting/unified/components/contact-points/NotificationTemplates.tsx` | verified |  |
| grafana | `public/app/features/alerting/unified/components/notification-policies/notificationPolicyAnalytics.ts` | verified |  |
| grafana | `public/app/features/alerting/unified/rule-list/LoadMoreHelper.tsx` | verified |  |
| grafana | `public/app/features/auth-config/utils/url.ts` | verified |  |
| grafana | `public/app/features/canvas/frame.ts` | verified |  |
| grafana | `public/app/features/dashboard/components/GenAI/tracking.ts` | verified |  |
| grafana | `public/app/features/explore/Logs/LogsTableWrap.tsx` | verified |  |
| grafana | `public/app/plugins/datasource/cloudwatch/mocks/cloudwatch-sql-test-data/multiLineIncompleteQueryWithoutNamespace.ts` | verified |  |
| grafana | `public/app/plugins/datasource/grafana-postgresql-datasource/PostgresQueryModel.ts` | verified |  |
