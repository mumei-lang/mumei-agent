# Target OSS no-LLM dogfooding audit — continuation 452 (batch 453)

Run: 2026-07-23T03:27:58.007336+00:00

## Summary

- Files audited: 50
- Verified: 50
- Refuted: 0
- Unverifiable: 0

All sampled files passed no-LLM verification; no new tool-side fixes were required.

## Sample details

| repo | file | status | notes |
|------|------|--------|-------|
| go | `src/cmd/cgo/internal/test/issue24161e1/main.go` | verified |  |
| go | `src/cmd/compile/internal/typecheck/iexport.go` | verified |  |
| go | `src/cmd/internal/bio/buf.go` | verified |  |
| go | `src/encoding/gob/debug.go` | verified |  |
| go | `src/internal/cpu/datacache_x86.go` | verified |  |
| go | `src/internal/goexperiment/mkconsts.go` | verified |  |
| go | `src/runtime/defs_darwin.go` | verified |  |
| go | `src/runtime/metrics/histogram.go` | verified |  |
| go | `src/syscall/exec_solaris_test.go` | verified |  |
| go | `src/unicode/graphic_test.go` | verified |  |
| go | `test/fixedbugs/bug145.go` | verified |  |
| go | `test/fixedbugs/bug437.dir/two.go` | verified |  |
| go | `test/fixedbugs/issue15585.go` | verified |  |
| go | `test/fixedbugs/issue24801.go` | verified |  |
| go | `test/fixedbugs/issue34723.go` | verified |  |
| go | `test/fixedbugs/issue49143.go` | verified |  |
| go | `test/fixedbugs/issue53702.go` | verified |  |
| go | `test/fixedbugs/issue7419.go` | verified |  |
| go | `test/func5.go` | verified |  |
| go | `test/initialize.go` | verified |  |
| go | `test/syntax/semi5.go` | verified |  |
| grafana | `apps/dashboard/pkg/apis/dashboard/v2beta1/register.go` | verified |  |
| grafana | `apps/dashboard/pkg/migration/schemaversion/datasource_utils_test.go` | verified |  |
| grafana | `apps/provisioning/pkg/generated/applyconfiguration/utils.go` | verified |  |
| grafana | `packages/grafana-runtime/src/utils/logging.ts` | verified |  |
| grafana | `packages/grafana-schema/src/schema/dashboard/v2/types.status.gen.ts` | verified |  |
| grafana | `pkg/cmd/grafana-server/commands/buildinfo.go` | verified |  |
| grafana | `pkg/infra/nats/metrics.go` | verified |  |
| grafana | `pkg/registry/apis/iam/externalgroupmapping/team_groups_noop.go` | verified |  |
| grafana | `pkg/registry/apis/iam/legacysort/sort.go` | verified |  |
| grafana | `pkg/registry/apis/iam/resourcepermission/mapper_test.go` | verified |  |
| grafana | `pkg/registry/apis/ofrep/noop.go` | verified |  |
| grafana | `pkg/registry/apis/provisioning/resources/folders.go` | verified |  |
| grafana | `pkg/services/accesscontrol/acimpl/service.go` | verified |  |
| grafana | `pkg/services/apiserver/builder/version.go` | verified |  |
| grafana | `pkg/services/ngalert/remote/client/mimir_auth_round_tripper.go` | verified |  |
| grafana | `pkg/services/sqlstore/session/session.go` | verified |  |
| grafana | `pkg/setting/setting_search.go` | verified |  |
| grafana | `pkg/storage/unified/apistore/prepare_test.go` | verified |  |
| grafana | `pkg/tsdb/azuremonitor/resourcegraph/azure-resource-graph-datasource_test.go` | verified |  |
| grafana | `pkg/tsdb/influxdb/influxql/buffered/response_parser_test.go` | verified |  |
| grafana | `pkg/tsdb/mysql/sqleng/handler_checkhealth_test.go` | verified |  |
| grafana | `public/app/features/provisioning/utils/repository.ts` | verified |  |
| grafana | `public/app/features/transformers/smoothing/smoothing.ts` | verified |  |
| grafana | `public/app/plugins/datasource/cloudwatch/components/shared/LogGroups/AccountsSelector.tsx` | verified |  |
| grafana | `public/app/plugins/datasource/grafana/randomWalk.ts` | verified |  |
| grafana | `public/app/plugins/datasource/loki/configuration/QuerySettings.tsx` | verified |  |
| grafana | `public/app/plugins/panel/timeseries/panelcfg.gen.ts` | verified |  |
| grafana | `public/test/mocks/query.ts` | verified |  |
| uniswap-contracts | `script/smoke/V3SmokeTest.s.sol` | verified |  |
