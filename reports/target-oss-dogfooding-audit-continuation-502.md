# Target OSS no-LLM dogfooding audit — continuation 502 (batch 503)

Run: 2026-07-23T07:08:44.575322+00:00

## Summary

- Files audited: 50
- Verified: 50
- Refuted: 0
- Unverifiable: 0

All sampled files passed no-LLM verification; no new tool-side fixes were required.

## Sample details

| repo | file | status | notes |
|------|------|--------|-------|
| go | `src/cmd/compile/internal/ssa/_gen/rulegen.go` | verified |  |
| go | `src/cmd/compile/internal/types2/interface.go` | verified |  |
| go | `src/cmd/go/internal/web/url_other_test.go` | verified |  |
| go | `src/crypto/internal/fips140/compile_test.go` | verified |  |
| go | `src/go/parser/resolver.go` | verified |  |
| go | `src/hash/crc32/crc32_ppc64le.go` | verified |  |
| go | `src/internal/goarch/goarch_mips64le.go` | verified |  |
| go | `src/internal/nettest/conn_test.go` | verified |  |
| go | `src/internal/runtime/atomic/bench_test.go` | verified |  |
| go | `src/log/slog/example_log_level_test.go` | verified |  |
| go | `src/math/bits/bits_tables.go` | verified |  |
| go | `src/os/executable_wasm.go` | verified |  |
| go | `src/os/root_unix.go` | verified |  |
| go | `src/os/signal/signal_linux_test.go` | verified |  |
| go | `src/runtime/crash_test.go` | verified |  |
| go | `test/codegen/memops.go` | verified |  |
| go | `test/fixedbugs/gcc80226.go` | verified |  |
| go | `test/fixedbugs/issue19610.go` | verified |  |
| go | `test/fixedbugs/issue33219.dir/a.go` | verified |  |
| go | `test/fixedbugs/issue41575.go` | verified |  |
| go | `test/fixedbugs/issue4590.dir/prog.go` | verified |  |
| go | `test/fixedbugs/issue6399.go` | verified |  |
| go | `test/int_lit.go` | verified |  |
| go | `test/reorder.go` | verified |  |
| go | `test/retjmp.go` | verified |  |
| go | `test/typeparam/issue48276b.go` | verified |  |
| go | `test/typeparam/issue50121b.go` | verified |  |
| grafana | `apps/dashboard/pkg/apis/dashboard/v0alpha1/constants.go` | verified |  |
| grafana | `apps/provisioning/pkg/repository/verify_test.go` | verified |  |
| grafana | `packages/grafana-data/src/unstable.ts` | verified |  |
| grafana | `packages/grafana-flamegraph/src/FlameGraph/FlameGraphMetadata.tsx` | verified |  |
| grafana | `packages/grafana-test-utils/src/handlers/api/access-control/handlers.ts` | verified |  |
| grafana | `pkg/api/preferences_test.go` | verified |  |
| grafana | `pkg/api/short_url_k8s_test.go` | verified |  |
| grafana | `pkg/registry/apps/logsdrilldown/strategy.go` | verified |  |
| grafana | `pkg/services/frontend/index.go` | verified |  |
| grafana | `pkg/services/frontend/request_config_middleware_test.go` | verified |  |
| grafana | `pkg/services/ngalert/cluster/evaluation_coordinator.go` | verified |  |
| grafana | `pkg/services/ngalert/notifier/alertmanager_config.go` | verified |  |
| grafana | `pkg/services/store/entity/models.go` | verified |  |
| grafana | `pkg/services/user/userimpl/legacy_user.go` | verified |  |
| grafana | `public/app/core/history/remoteStorageConverter.ts` | verified |  |
| grafana | `public/app/features/actions/ActionsInlineEditor.tsx` | verified |  |
| grafana | `public/app/features/alerting/unified/components/rule-viewer/tabs/version-history/ComparisonDrawer.tsx` | verified |  |
| grafana | `public/app/features/commandPalette/CommandPalette.tsx` | verified |  |
| grafana | `public/app/features/dashboard-scene/mutation-api/commands/removeRow.ts` | verified |  |
| grafana | `public/app/features/dashboard-scene/scene/panel-actions/PanelGroupByAction/PanelGroupByActionPopover.tsx` | verified |  |
| grafana | `public/app/features/plugins/loader/constants.ts` | verified |  |
| grafana | `public/app/plugins/datasource/influxdb/influx_query_model.ts` | verified |  |
| grafana | `public/app/plugins/datasource/loki/sortDataFrame.ts` | verified |  |
