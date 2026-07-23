# Target OSS no-LLM dogfooding audit — continuation 461 (batch 462)

Run: 2026-07-23T04:04:10.475333+00:00

## Summary

- Files audited: 50
- Verified: 50
- Refuted: 0
- Unverifiable: 0

All sampled files passed no-LLM verification; no new tool-side fixes were required.

## Sample details

| repo | file | status | notes |
|------|------|--------|-------|
| go | `src/cmd/compile/internal/arm/galign.go` | verified |  |
| go | `src/cmd/compile/internal/walk/expr.go` | verified |  |
| go | `src/cmd/internal/obj/fips140.go` | verified |  |
| go | `src/crypto/internal/cryptotest/wycheproof/schemaversion.go` | verified |  |
| go | `src/crypto/internal/fips140/aes/ctr_s390x.go` | verified |  |
| go | `src/crypto/tls/example_test.go` | verified |  |
| go | `src/go/doc/comment/doc.go` | verified |  |
| go | `src/internal/bytealg/index_amd64.go` | verified |  |
| go | `src/internal/diff/diff_test.go` | verified |  |
| go | `src/internal/gover/gover_test.go` | verified |  |
| go | `src/log/slog/record_test.go` | verified |  |
| go | `src/net/main_plan9_test.go` | verified |  |
| go | `src/runtime/os_linux_loong64.go` | verified |  |
| go | `src/time/format.go` | verified |  |
| go | `test/escape_slice.go` | verified |  |
| go | `test/fixedbugs/bug151.go` | verified |  |
| go | `test/fixedbugs/issue14136.go` | verified |  |
| go | `test/fixedbugs/issue31636.dir/c.go` | verified |  |
| go | `test/fixedbugs/issue4097.go` | verified |  |
| go | `test/fixedbugs/issue4405.go` | verified |  |
| go | `test/typeparam/issue48598.go` | verified |  |
| go | `test/typeparam/issue49667.dir/a.go` | verified |  |
| grafana | `apps/dashboard/pkg/apis/dashboard/v0alpha1/snapshot.go` | verified |  |
| grafana | `apps/iam/pkg/apis/iam/v0alpha1/serviceaccount_codec_gen.go` | verified |  |
| grafana | `apps/provisioning/pkg/repository/git/repository_test.go` | verified |  |
| grafana | `packages/grafana-ui/src/components/PanelChrome/PanelChrome.tsx` | verified |  |
| grafana | `packages/grafana-ui/src/components/VizLegend/VizLegendStatsList.tsx` | verified |  |
| grafana | `packages/grafana-ui/src/graveyard/TableInputCSV/TableInputCSV.tsx` | verified |  |
| grafana | `packages/grafana-ui/src/themes/GlobalStyles/fonts.ts` | verified |  |
| grafana | `pkg/infra/log/databaseQueryTimer_test.go` | verified |  |
| grafana | `pkg/middleware/csrf/csrf.go` | verified |  |
| grafana | `pkg/registry/apis/provisioning/webhooks/pullrequest/render_mock.go` | verified |  |
| grafana | `pkg/registry/apis/secret/decrypt/noop_authorizer.go` | verified |  |
| grafana | `pkg/registry/apps/alerting/rules/common/selectors.go` | verified |  |
| grafana | `pkg/ruleguard.rules.go` | verified |  |
| grafana | `pkg/services/apiserver/auth/authorizer/namespace_test.go` | verified |  |
| grafana | `pkg/services/ngalert/api/errors.go` | verified |  |
| grafana | `pkg/services/ngalert/notifier/images_test.go` | verified |  |
| grafana | `pkg/tests/api/alerting/api_remote_alertmanager_test.go` | verified |  |
| grafana | `pkg/tests/apis/provisioning/helper_test.go` | verified |  |
| grafana | `pkg/util/xorm/helpers.go` | verified |  |
| grafana | `pkg/util/xorm/session_schema.go` | verified |  |
| grafana | `public/app/features/alerting/unified/components/rule-viewer/pageNav.ts` | verified |  |
| grafana | `public/app/features/alerting/unified/hooks/useGroupedAlerts.ts` | verified |  |
| grafana | `public/app/features/dashboard-scene/panel-edit/PanelEditNext/QueryEditor/StackedEditor/utils.ts` | verified |  |
| grafana | `public/app/features/plugins/components/PluginStateInfo.tsx` | verified |  |
| grafana | `public/app/plugins/datasource/cloudwatch/migrations/useMigratedMetricsQuery.ts` | verified |  |
| grafana | `public/app/plugins/datasource/loki/components/LokiQueryField.tsx` | verified |  |
| grafana | `public/app/plugins/datasource/loki/querybuilder/types.ts` | verified |  |
| grafana | `scripts/webpack/rules.ts` | verified |  |
