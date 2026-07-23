# Target OSS no-LLM dogfooding audit — continuation 481 (batch 482)

Run: 2026-07-23T05:40:37.911435+00:00

## Summary

- Files audited: 50
- Verified: 50
- Refuted: 0
- Unverifiable: 0

All sampled files passed no-LLM verification; no new tool-side fixes were required.

## Sample details

| repo | file | status | notes |
|------|------|--------|-------|
| go | `src/archive/tar/stat_unix.go` | verified |  |
| go | `src/cmd/gofmt/rewrite.go` | verified |  |
| go | `src/encoding/gob/dec_helpers.go` | verified |  |
| go | `src/encoding/json/fuzz_test.go` | verified |  |
| go | `src/internal/goexperiment/exp_randomizedheapbase64_off.go` | verified |  |
| go | `src/net/rawconn.go` | verified |  |
| go | `src/os/wait_waitid.go` | verified |  |
| go | `src/runtime/pprof/pprof_norusage.go` | verified |  |
| go | `src/unique/clone.go` | verified |  |
| go | `test/abi/fibish_closure.go` | verified |  |
| go | `test/fixedbugs/bug090.go` | verified |  |
| go | `test/fixedbugs/bug478.dir/a.go` | verified |  |
| go | `test/fixedbugs/issue12944.go` | verified |  |
| go | `test/fixedbugs/issue49005b.go` | verified |  |
| go | `test/fixedbugs/issue4909b.go` | verified |  |
| go | `test/fixedbugs/issue68227.go` | verified |  |
| go | `test/fixedbugs/issue8336.go` | verified |  |
| go | `test/intrinsic.dir/main.go` | verified |  |
| go | `test/typeparam/absdiffimp2.go` | verified |  |
| go | `test/typeparam/issue50598.dir/a1.go` | verified |  |
| go | `test/typeparam/issue50690b.go` | verified |  |
| grafana | `apps/alerting/rules/pkg/apis/alerting/v0alpha1/recordingrule_schema_gen.go` | verified |  |
| grafana | `apps/dashboard/pkg/apis/dashboard/v0alpha1/register.go` | verified |  |
| grafana | `apps/dashboard/pkg/migration/conversion/v2alpha1_to_v2.go` | verified |  |
| grafana | `apps/provisioning/pkg/generated/clientset/versioned/typed/provisioning/v0alpha1/job.go` | verified |  |
| grafana | `apps/provisioning/pkg/repository/git/validator_test.go` | verified |  |
| grafana | `apps/secret/pkg/apis/secret/v1beta1/securevalue_status_gen.go` | verified |  |
| grafana | `packages/grafana-sql/src/expressions.ts` | verified |  |
| grafana | `packages/grafana-ui/src/components/Slider/Slider.tsx` | verified |  |
| grafana | `pkg/middleware/requestmeta/request_metadata.go` | verified |  |
| grafana | `pkg/plugins/pluginscdn/url_constructor_test.go` | verified |  |
| grafana | `pkg/registry/apis/dashboard/legacy/sql_dashboards.go` | verified |  |
| grafana | `pkg/registry/apis/datasource/middleware.go` | verified |  |
| grafana | `pkg/registry/apis/iam/team/search.go` | verified |  |
| grafana | `pkg/registry/apis/provisioning/resources/tree.go` | verified |  |
| grafana | `pkg/services/anonymous/sortopts/sortopts_test.go` | verified |  |
| grafana | `pkg/services/apiserver/service_test.go` | verified |  |
| grafana | `pkg/services/authz/zanzana/server/noop.go` | verified |  |
| grafana | `pkg/services/libraryelements/conversions.go` | verified |  |
| grafana | `pkg/tests/apis/provisioning/orgs/namespace_isolation_test.go` | verified |  |
| grafana | `pkg/util/xorm/session_stats.go` | verified |  |
| grafana | `public/app/features/actions/ConnectionPicker.tsx` | verified |  |
| grafana | `public/app/features/apiserver/client.ts` | verified |  |
| grafana | `public/app/features/browse-dashboards/api/constants.ts` | verified |  |
| grafana | `public/app/features/explore/TraceView/components/CriticalPath/testCases/test6.ts` | verified |  |
| grafana | `public/app/features/explore/TraceView/components/TraceTimelineViewer/SummaryDurationStatsTooltip.tsx` | verified |  |
| grafana | `public/app/features/plugins/admin/components/ConnectionsTab.tsx` | verified |  |
| grafana | `public/app/features/stars/hooks.ts` | verified |  |
| grafana | `public/app/plugins/panel/geomap/components/DebugOverlay.tsx` | verified |  |
| grafana | `public/app/plugins/panel/piechart/utils.ts` | verified |  |
