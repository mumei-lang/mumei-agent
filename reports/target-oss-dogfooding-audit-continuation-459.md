# Target OSS no-LLM dogfooding audit — continuation 459 (batch 460)

Run: 2026-07-23T04:00:25.263428+00:00

## Summary

- Files audited: 50
- Verified: 50
- Refuted: 0
- Unverifiable: 0

All sampled files passed no-LLM verification; no new tool-side fixes were required.

## Sample details

| repo | file | status | notes |
|------|------|--------|-------|
| go | `src/cmd/compile/internal/ssa/_gen/RISCV64Ops.go` | verified |  |
| go | `src/cmd/compile/internal/ssa/_gen/divisibleOps.go` | verified |  |
| go | `src/cmd/compile/internal/types/size.go` | verified |  |
| go | `src/cmd/go/internal/load/test.go` | verified |  |
| go | `src/cmd/internal/objabi/line_test.go` | verified |  |
| go | `src/cmd/link/internal/ld/fallocate_test.go` | verified |  |
| go | `src/go/scanner/scanner.go` | verified |  |
| go | `src/internal/cfg/cfg.go` | verified |  |
| go | `src/internal/cpu/cpu_arm64_freebsd.go` | verified |  |
| go | `src/internal/goarch/goarch.go` | verified |  |
| go | `src/internal/profile/encode.go` | verified |  |
| go | `src/math/all_test.go` | verified |  |
| go | `src/os/error_windows_test.go` | verified |  |
| go | `src/runtime/defs_openbsd_arm64.go` | verified |  |
| go | `test/fixedbugs/bug301.go` | verified |  |
| go | `test/fixedbugs/bug462.go` | verified |  |
| go | `test/fixedbugs/bug507.go` | verified |  |
| go | `test/fixedbugs/issue17328.go` | verified |  |
| go | `test/fixedbugs/issue28079a.go` | verified |  |
| go | `test/fixedbugs/issue49240.go` | verified |  |
| go | `test/fixedbugs/issue6703e.go` | verified |  |
| go | `test/typeparam/recoverimp.go` | verified |  |
| grafana | `apps/live/pkg/apis/live/v1alpha1/constants.go` | verified |  |
| grafana | `apps/plugins/pkg/apis/plugins/v0alpha1/plugin_client_gen.go` | verified |  |
| grafana | `e2e-playwright/test-plugins/grafana-extensionstest-app/plugins/grafana-extensionexample1-app/module.tsx` | verified |  |
| grafana | `packages/grafana-data/src/transformations/matchers.ts` | verified |  |
| grafana | `packages/grafana-data/src/types/icon.ts` | verified |  |
| grafana | `packages/grafana-ui/src/components/Modal/Modal.tsx` | verified |  |
| grafana | `pkg/registry/apis/datasource/legacy_store.go` | verified |  |
| grafana | `pkg/registry/apis/folders/continue.go` | verified |  |
| grafana | `pkg/registry/apis/query/noop.go` | verified |  |
| grafana | `pkg/registry/apps/alerting/rules/alertrule/compat_test.go` | verified |  |
| grafana | `pkg/services/live/livecontext/context.go` | verified |  |
| grafana | `pkg/services/ngalert/notifier/autogen_alertmanager.go` | verified |  |
| grafana | `pkg/services/ngalert/notifier/external_am_syncer_test.go` | verified |  |
| grafana | `pkg/storage/unified/resource/search_field_manifest.go` | verified |  |
| grafana | `pkg/tests/apis/provisioning/quota/foldermetadata/helpers_test.go` | verified |  |
| grafana | `pkg/tests/apis/provisioning/quota/limits_test.go` | verified |  |
| grafana | `pkg/tsdb/azuremonitor/loganalytics/traces_test.go` | verified |  |
| grafana | `public/app/core/components/TimelineChart/TimelineChart.tsx` | verified |  |
| grafana | `public/app/features/alerting/unified/components/TimeRangeLabel.tsx` | verified |  |
| grafana | `public/app/features/alerting/unified/components/notification-policies/Filters.tsx` | verified |  |
| grafana | `public/app/features/alerting/unified/components/rule-editor/query-and-alert-condition/SimpleCondition.tsx` | verified |  |
| grafana | `public/app/features/alerting/unified/components/rules/RuleListErrors.tsx` | verified |  |
| grafana | `public/app/features/auth-config/state/reducers.ts` | verified |  |
| grafana | `public/app/features/dashboard-scene/scene/new-toolbar/actions/PublicDashboardBadge.tsx` | verified |  |
| grafana | `public/app/features/plugins/components/AssistantNavOnboarding.tsx` | verified |  |
| grafana | `public/app/index.ts` | verified |  |
| grafana | `public/app/plugins/datasource/azuremonitor/components/ConfigEditor/AppRegistrationCredentials.tsx` | verified |  |
| grafana | `public/app/plugins/panel/histogram/Histogram.tsx` | verified |  |
