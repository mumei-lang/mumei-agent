# Target OSS no-LLM dogfooding audit — continuation 468 (batch 469)

Run: 2026-07-23T04:39:28.027387+00:00

## Summary

- Files audited: 50
- Verified: 50
- Refuted: 0
- Unverifiable: 0

All sampled files passed no-LLM verification; no new tool-side fixes were required.

## Sample details

| repo | file | status | notes |
|------|------|--------|-------|
| go | `src/cmd/compile/internal/ssa/opt.go` | verified |  |
| go | `src/cmd/go/internal/work/shell.go` | verified |  |
| go | `src/cmd/internal/obj/ppc64/a.out.go` | verified |  |
| go | `src/cmd/trace/pprof.go` | verified |  |
| go | `src/crypto/internal/fips140/rsa/pkcs1v22_test.go` | verified |  |
| go | `src/encoding/asn1/marshal_test.go` | verified |  |
| go | `src/encoding/json/v2/arshal_funcs.go` | verified |  |
| go | `src/html/template/escape.go` | verified |  |
| go | `src/math/big/link_test.go` | verified |  |
| go | `src/net/lookup_test.go` | verified |  |
| go | `src/reflect/deepequal.go` | verified |  |
| go | `src/runtime/defs_linux_ppc64le.go` | verified |  |
| go | `src/simd/archsimd/_gen/tmplgen/main.go` | verified |  |
| go | `src/syscall/syscall_freebsd.go` | verified |  |
| go | `test/codegen/issue33580.go` | verified |  |
| go | `test/codegen/issue72832.go` | verified |  |
| go | `test/dwarf/dwarf.dir/z17.go` | verified |  |
| go | `test/escape.go` | verified |  |
| go | `test/fixedbugs/issue22881.go` | verified |  |
| go | `test/fixedbugs/issue26616.go` | verified |  |
| go | `test/fixedbugs/issue37753.go` | verified |  |
| go | `test/fixedbugs/issue63657.go` | verified |  |
| go | `test/typeparam/structinit.dir/a.go` | verified |  |
| grafana | `apps/dashboard/pkg/apis/dashboard/v2/dashboard_client_gen.go` | verified |  |
| grafana | `e2e-playwright/dashboard-cujs/dashboardUidsState.ts` | verified |  |
| grafana | `e2e-playwright/test-plugins/grafana-test-panel/module.ts` | verified |  |
| grafana | `packages/grafana-api-clients/src/clients/rtkq/preferences/team/index.ts` | verified |  |
| grafana | `packages/grafana-data/src/themes/createShape.ts` | verified |  |
| grafana | `packages/grafana-data/src/types/valueFormats.ts` | verified |  |
| grafana | `packages/grafana-flamegraph/src/FlameGraph/FlameGraphTooltip.tsx` | verified |  |
| grafana | `packages/grafana-ui/src/graveyard/uPlot/plugins/TooltipPlugin.tsx` | verified |  |
| grafana | `pkg/api/health.go` | verified |  |
| grafana | `pkg/apiserver/rest/storage.go` | verified |  |
| grafana | `pkg/cmd/grafana-cli/commands/flush_rbac.go` | verified |  |
| grafana | `pkg/middleware/org_redirect.go` | verified |  |
| grafana | `pkg/services/login/authinfoimpl/service.go` | verified |  |
| grafana | `pkg/services/ngalert/store/alertmanager_test.go` | verified |  |
| grafana | `pkg/services/shorturls/shorturl.go` | verified |  |
| grafana | `pkg/storage/legacysql/dualwrite/dualwriter_mode1_test.go` | verified |  |
| grafana | `pkg/storage/unified/search/vector/query_cache_test.go` | verified |  |
| grafana | `pkg/tests/apis/provisioning/jobs/instanceauth/helpers_test.go` | verified |  |
| grafana | `pkg/tsdb/cloudwatch/response_parser_test.go` | verified |  |
| grafana | `public/app/features/alerting/unified/triage/scene/filters/SeverityBars.tsx` | verified |  |
| grafana | `public/app/features/dashboard-scene/edit-pane/outline/DashboardOutlineRenderer.tsx` | verified |  |
| grafana | `public/app/features/dashboard-scene/scene/DashboardMacro.ts` | verified |  |
| grafana | `public/app/features/explore/TraceView/components/TraceTimelineViewer/SpanDetail/SpanDetailLinkButtons.tsx` | verified |  |
| grafana | `public/app/features/expressions/components/Reduce.tsx` | verified |  |
| grafana | `public/app/features/plugins/loader/pluginLoader.mock.ts` | verified |  |
| grafana | `public/app/plugins/datasource/cloudwatch/language/cloudwatch-sql/consts.ts` | verified |  |
| grafana | `public/app/plugins/datasource/grafana-testdata-datasource/components/CSVWaveEditor.tsx` | verified |  |
