# Target OSS no-LLM dogfooding audit — continuation 528 (batch 529)

Run: 2026-07-23T08:24:11.071311+00:00

## Summary

- Files audited: 50
- Verified: 50
- Refuted: 0
- Unverifiable: 0

All sampled files passed no-LLM verification; no new tool-side fixes were required.

## Sample details

| repo | file | status | notes |
|------|------|--------|-------|
| go | `src/cmd/compile/internal/syntax/tokens.go` | verified |  |
| go | `src/cmd/compile/internal/types/goversion.go` | verified |  |
| go | `src/cmd/compile/internal/types2/errors_test.go` | verified |  |
| go | `src/cmd/go/internal/base/goflags.go` | verified |  |
| go | `src/cmd/go/internal/clean/clean.go` | verified |  |
| go | `src/cmd/link/internal/ld/outbuf_mmap.go` | verified |  |
| go | `src/go/token/position_bench_test.go` | verified |  |
| go | `src/internal/goexperiment/exp_staticlockranking_on.go` | verified |  |
| go | `src/internal/msan/nomsan.go` | verified |  |
| go | `src/internal/poll/error_test.go` | verified |  |
| go | `src/internal/syscall/unix/sysnum_linux_ppc64x.go` | verified |  |
| go | `src/log/slog/attr_test.go` | verified |  |
| go | `src/os/dirent_freebsd.go` | verified |  |
| go | `src/os/types_unix.go` | verified |  |
| go | `src/runtime/race/race_v3_amd64.go` | verified |  |
| go | `src/runtime/tls_stub.go` | verified |  |
| go | `src/testing/synctest/helper_test.go` | verified |  |
| go | `test/escape_struct_param1.go` | verified |  |
| go | `test/fixedbugs/bug037.go` | verified |  |
| go | `test/fixedbugs/issue15071.dir/main.go` | verified |  |
| go | `test/fixedbugs/issue29919.go` | verified |  |
| go | `test/fixedbugs/issue38117.go` | verified |  |
| go | `test/fixedbugs/issue43551.go` | verified |  |
| go | `test/fixedbugs/issue59709.dir/bresource.go` | verified |  |
| go | `test/typeparam/issue49659.dir/b.go` | verified |  |
| go | `test/typeparam/issue54302.dir/a.go` | verified |  |
| grafana | `apps/dashboard/pkg/migration/schemaversion/v4.go` | verified |  |
| grafana | `apps/plugins/pkg/app/plugin_storage_test.go` | verified |  |
| grafana | `apps/provisioning/pkg/connection/github/factory_mock.go` | verified |  |
| grafana | `packages/grafana-data/src/utils/variables.ts` | verified |  |
| grafana | `packages/grafana-runtime/src/services/pluginSettings/test-fixtures/legacy.settings.ts` | verified |  |
| grafana | `packages/grafana-test-utils/src/types/browse-dashboards.ts` | verified |  |
| grafana | `packages/grafana-ui/src/components/DateTimePickers/utils.ts` | verified |  |
| grafana | `packages/grafana-ui/src/components/RadialGauge/RadialScaleLabels.tsx` | verified |  |
| grafana | `pkg/api/dtos/user.go` | verified |  |
| grafana | `pkg/api/plugins_test.go` | verified |  |
| grafana | `pkg/registry/apis/provisioning/resources/cleanup.go` | verified |  |
| grafana | `pkg/registry/apis/secret/encryption/cipher/service/service.go` | verified |  |
| grafana | `pkg/services/frontend/frontend_service_test.go` | verified |  |
| grafana | `pkg/services/ngalert/notifier/templates_test.go` | verified |  |
| grafana | `pkg/services/sqlstore/migrator/dialect_test.go` | verified |  |
| grafana | `public/app/core/components/AppChrome/MegaMenu/MegaMenuItem.tsx` | verified |  |
| grafana | `public/app/core/services/mousetrap/index.ts` | verified |  |
| grafana | `public/app/features/alerting/unified/components/import-to-gma/steps/MethodPanelCard.tsx` | verified |  |
| grafana | `public/app/features/alerting/unified/mocks/server/handlers/k8s/templates.k8s.ts` | verified |  |
| grafana | `public/app/features/dashboard-scene/scene/DashboardControls.tsx` | verified |  |
| grafana | `public/app/features/dashboard/dashgrid/DashboardLibrary/interactions.ts` | verified |  |
| grafana | `public/app/features/explore/TraceView/components/selectors/span.ts` | verified |  |
| grafana | `public/app/plugins/panel/barchart/panelcfg.gen.ts` | verified |  |
| grafana | `public/app/types/accessControl.ts` | verified |  |
