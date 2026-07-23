# Target OSS no-LLM dogfooding audit — continuation 476 (batch 477)

Run: 2026-07-23T04:54:30.495347+00:00

## Summary

- Files audited: 50
- Verified: 50
- Refuted: 0
- Unverifiable: 0

All sampled files passed no-LLM verification; no new tool-side fixes were required.

## Sample details

| repo | file | status | notes |
|------|------|--------|-------|
| go | `src/cmd/cgo/internal/test/issue9026.go` | verified |  |
| go | `src/cmd/compile/internal/inline/inlheur/callsite.go` | verified |  |
| go | `src/cmd/internal/obj/arm64/anames_gen.go` | verified |  |
| go | `src/cmd/internal/obj/mips/anames0.go` | verified |  |
| go | `src/compress/flate/level5.go` | verified |  |
| go | `src/internal/cpu/cpu_s390x_test.go` | verified |  |
| go | `src/internal/goarch/zgoarch_s390.go` | verified |  |
| go | `src/internal/goexperiment/exp_greenteagc_on.go` | verified |  |
| go | `src/internal/syscall/unix/tcsetpgrp_bsd.go` | verified |  |
| go | `src/internal/testenv/testenv_windows.go` | verified |  |
| go | `src/os/user/listgroups_unix_test.go` | verified |  |
| go | `src/runtime/defs_darwin_amd64.go` | verified |  |
| go | `src/runtime/map_test.go` | verified |  |
| go | `test/fixedbugs/bug232.go` | verified |  |
| go | `test/fixedbugs/bug517.go` | verified |  |
| go | `test/fixedbugs/issue37837.dir/b.go` | verified |  |
| go | `test/fixedbugs/issue73483.go` | verified |  |
| go | `test/interface/embed1.dir/embed0.go` | verified |  |
| go | `test/linkmain.go` | verified |  |
| go | `test/typeparam/issue50121b.dir/d.go` | verified |  |
| go | `test/typeswitch2b.go` | verified |  |
| grafana | `apps/alerting/notifications/pkg/apis/alertingnotifications/v0alpha1/inhibitionrule_schema_gen.go` | verified |  |
| grafana | `apps/dashboard/pkg/apis/dashboard/v2beta1/notebook_object_gen.go` | verified |  |
| grafana | `apps/iam/pkg/apis/iam/v0alpha1/user_client_gen.go` | verified |  |
| grafana | `apps/provisioning/pkg/apis/auth/token_access_checker_test.go` | verified |  |
| grafana | `apps/secret/inline/v1beta1/inline_grpc.pb.go` | verified |  |
| grafana | `e2e-playwright/test-plugins/grafana-test-panel/i18next.config.ts` | verified |  |
| grafana | `packages/grafana-data/src/valueFormats/dateTimeFormatters.ts` | verified |  |
| grafana | `packages/grafana-schema/src/raw/composable/googlecloudmonitoring/dataquery/x/types.gen.ts` | verified |  |
| grafana | `pkg/apis/iam/v0alpha1/register.go` | verified |  |
| grafana | `pkg/codegen/util_go.go` | verified |  |
| grafana | `pkg/infra/nats/discovery.go` | verified |  |
| grafana | `pkg/registry/apis/preferences/utils/names.go` | verified |  |
| grafana | `pkg/registry/apis/provisioning/webhooks/register_test.go` | verified |  |
| grafana | `pkg/registry/apps/annotation/graphite_handler_test.go` | verified |  |
| grafana | `pkg/services/anonymous/anontest/fake.go` | verified |  |
| grafana | `pkg/services/authn/clients/oauth_test.go` | verified |  |
| grafana | `pkg/services/ngalert/notifier/crypto_test.go` | verified |  |
| grafana | `pkg/services/provisioning/dashboards/dashboard.go` | verified |  |
| grafana | `pkg/services/provisioning/plugins/config_reader_test.go` | verified |  |
| grafana | `pkg/services/stats/statstest/stats.go` | verified |  |
| grafana | `pkg/storage/unified/search/vector/pgvector_test.go` | verified |  |
| grafana | `public/app/core/utils/timePicker.ts` | verified |  |
| grafana | `public/app/features/alerting/unified/hooks/useEnrichmentUrlParams.ts` | verified |  |
| grafana | `public/app/features/alerting/unified/hooks/useTestContactPoint.ts` | verified |  |
| grafana | `public/app/features/alerting/unified/notifications/RelatedNotificationsSidebar.tsx` | verified |  |
| grafana | `public/app/features/dashboard-scene/inspect/HelpWizard/SupportSnapshotService.ts` | verified |  |
| grafana | `public/app/features/dashboard-scene/scene/layout-default/row-actions/RowActions.tsx` | verified |  |
| grafana | `public/app/features/migrate-to-cloud/onprem/EmptyState/CallToAction/ConnectModal.tsx` | verified |  |
| grafana | `public/app/plugins/datasource/cloudwatch/language/logs/definition.ts` | verified |  |
