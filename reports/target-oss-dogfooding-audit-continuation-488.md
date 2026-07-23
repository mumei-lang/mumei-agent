# Target OSS no-LLM dogfooding audit — continuation 488 (batch 489)

Run: 2026-07-23T06:14:16.571325+00:00

## Summary

- Files audited: 50
- Verified: 50
- Refuted: 0
- Unverifiable: 0

All sampled files passed no-LLM verification; no new tool-side fixes were required.

## Sample details

| repo | file | status | notes |
|------|------|--------|-------|
| go | `src/cmd/compile/internal/walk/order.go` | verified |  |
| go | `src/cmd/go/help_test.go` | verified |  |
| go | `src/cmd/go/internal/web/http.go` | verified |  |
| go | `src/crypto/x509/constraints.go` | verified |  |
| go | `src/go/doc/comment_test.go` | verified |  |
| go | `src/image/format.go` | verified |  |
| go | `src/internal/routebsd/route_test.go` | verified |  |
| go | `src/log/slog/internal/benchmarks/handlers.go` | verified |  |
| go | `src/net/http/transport.go` | verified |  |
| go | `src/net/smtp/example_test.go` | verified |  |
| go | `src/os/exec/lp_linux_test.go` | verified |  |
| go | `src/path/example_test.go` | verified |  |
| go | `src/runtime/defs3_linux.go` | verified |  |
| go | `src/runtime/defs_linux_amd64.go` | verified |  |
| go | `src/syscall/syscall_solaris.go` | verified |  |
| go | `src/unique/doc.go` | verified |  |
| go | `test/fixedbugs/bug067.go` | verified |  |
| go | `test/fixedbugs/bug231.go` | verified |  |
| go | `test/fixedbugs/bug505.go` | verified |  |
| go | `test/fixedbugs/issue15071.go` | verified |  |
| go | `test/fixedbugs/issue22962.dir/a.go` | verified |  |
| go | `test/fixedbugs/spillreload_arm64_pair.go` | verified |  |
| go | `test/typeparam/aliasimp.dir/main.go` | verified |  |
| grafana | `apps/iam/pkg/apis/iam/v0alpha1/team_getteamgroups_response_body_types_gen.go` | verified |  |
| grafana | `devenv/secrets/secrets.go` | verified |  |
| grafana | `packages/grafana-alerting/src/grafana/api/notifications/v0alpha1/mocks/handlers/ReceiverHandlers/updateReceiverHandler.ts` | verified |  |
| grafana | `packages/grafana-api-clients/src/clients/rtkq/migrate-to-cloud/baseAPI.ts` | verified |  |
| grafana | `packages/grafana-test-utils/src/canvas/index.ts` | verified |  |
| grafana | `packages/grafana-test-utils/src/handlers/apis/provisioning.grafana.app/v0alpha1/handlers.ts` | verified |  |
| grafana | `packages/grafana-ui/src/graveyard/GraphNG/nullInsertThreshold.ts` | verified |  |
| grafana | `packages/grafana-ui/src/utils/storybook/withTimeZone.tsx` | verified |  |
| grafana | `pkg/middleware/provisioning_auth.go` | verified |  |
| grafana | `pkg/modules/listener.go` | verified |  |
| grafana | `pkg/registry/apis/secret/accesscontrol.go` | verified |  |
| grafana | `pkg/services/dashboards/service/search/search_test.go` | verified |  |
| grafana | `pkg/services/sqlstore/migrations/external_alertmanagers.go` | verified |  |
| grafana | `pkg/util/uri_sanitize.go` | verified |  |
| grafana | `public/app/core/components/AppChrome/OrganizationSwitcher/OrganizationSwitcher.tsx` | verified |  |
| grafana | `public/app/features/alerting/unified/api/ruler.ts` | verified |  |
| grafana | `public/app/features/alerting/unified/components/Authorize.tsx` | verified |  |
| grafana | `public/app/features/alerting/unified/components/EditorColumnHeader.tsx` | verified |  |
| grafana | `public/app/features/dashboard-scene/mutation-api/commands/shared.ts` | verified |  |
| grafana | `public/app/features/dashboard/services/ReportRenderReadinessObserver.ts` | verified |  |
| grafana | `public/app/features/explore/RawPrometheus/PrometheusQueryResultsContainer.tsx` | verified |  |
| grafana | `public/app/features/plugins/cdn/utils.ts` | verified |  |
| grafana | `public/app/features/transformers/configFromQuery/ConfigFromQueryTransformerEditor.tsx` | verified |  |
| grafana | `public/app/plugins/datasource/grafana-testdata-datasource/components/PredictablePulseEditor.tsx` | verified |  |
| grafana | `public/app/plugins/panel/canvas/components/connections/ConnectionAnchors2.tsx` | verified |  |
| grafana | `public/app/plugins/panel/canvas/editor/connectionEditor.tsx` | verified |  |
| grafana | `public/app/plugins/panel/canvas/editor/layer/tree.ts` | verified |  |
