# Target OSS no-LLM dogfooding audit — continuation 428 (batch 429)

Run: 2026-07-23T01:53:15.427356+00:00

## Summary

- Files audited: 50
- Verified: 50
- Refuted: 0
- Unverifiable: 0

All sampled files passed no-LLM verification; no new tool-side fixes were required.

## Sample details

| repo | file | status | notes |
|------|------|--------|-------|
| go | `src/cmd/compile/internal/types2/object_test.go` | verified |  |
| go | `src/go/types/conversions.go` | verified |  |
| go | `src/internal/fmtsort/sort_test.go` | verified |  |
| go | `src/internal/runtime/syscall/linux/defs_linux_s390x.go` | verified |  |
| go | `src/internal/trace/mud.go` | verified |  |
| go | `src/net/cgo_unix_cgo_res.go` | verified |  |
| go | `src/net/main_conf_test.go` | verified |  |
| go | `src/path/filepath/export_test.go` | verified |  |
| go | `src/runtime/cgo/dragonfly.go` | verified |  |
| go | `src/runtime/os_netbsd_amd64.go` | verified |  |
| go | `src/runtime/pprof/label.go` | verified |  |
| go | `src/simd/archsimd/internal/simd_test/simd_amd64_test.go` | verified |  |
| go | `src/strings/compare.go` | verified |  |
| go | `src/testing/match.go` | verified |  |
| go | `test/devirt.go` | verified |  |
| go | `test/fixedbugs/bug059.go` | verified |  |
| go | `test/fixedbugs/bug141.go` | verified |  |
| go | `test/fixedbugs/bug325.go` | verified |  |
| go | `test/fixedbugs/issue16428.go` | verified |  |
| go | `test/fixedbugs/issue41500.go` | verified |  |
| go | `test/fixedbugs/issue4879.dir/b.go` | verified |  |
| go | `test/fixedbugs/issue5056.go` | verified |  |
| go | `test/fixedbugs/issue6055.go` | verified |  |
| go | `test/typeparam/absdiffimp.dir/main.go` | verified |  |
| go | `test/typeparam/issue51219b.dir/b.go` | verified |  |
| grafana | `apps/iam/pkg/apis/iam/v0alpha1/team_deleteteammember_request_body_types_gen.go` | verified |  |
| grafana | `apps/provisioning/pkg/connection/factory_mock.go` | verified |  |
| grafana | `apps/provisioning/pkg/generated/listers/provisioning/v0alpha1/historicjob.go` | verified |  |
| grafana | `apps/provisioning/pkg/safepath/trie.go` | verified |  |
| grafana | `packages/grafana-test-utils/src/handlers/apis/dashboard.grafana.app/v1beta1/handlers.ts` | verified |  |
| grafana | `pkg/registry/apis/provisioning/informer/repository_test.go` | verified |  |
| grafana | `pkg/server/module_server_test.go` | verified |  |
| grafana | `pkg/services/authn/clients/provisioning_test.go` | verified |  |
| grafana | `pkg/services/live/pipeline/tree/params.go` | verified |  |
| grafana | `pkg/services/login/authinfoimpl/store_test.go` | verified |  |
| grafana | `pkg/services/ngalert/store/compat_test.go` | verified |  |
| grafana | `pkg/services/pluginsintegration/clientmiddleware/http_capture_middleware.go` | verified |  |
| grafana | `pkg/storage/secret/database/database.go` | verified |  |
| grafana | `pkg/tsdb/jaeger/standalone/datasource.go` | verified |  |
| grafana | `public/app/core/reducers/appNotification.ts` | verified |  |
| grafana | `public/app/features/alerting/unified/components/receivers/form/CollapsibleSection.tsx` | verified |  |
| grafana | `public/app/features/alerting/unified/components/rules/state-history/LogRecordViewer.tsx` | verified |  |
| grafana | `public/app/features/alerting/unified/reducers/alertmanager/receivers.ts` | verified |  |
| grafana | `public/app/features/inspector/InspectStatsTraceIdsTable.tsx` | verified |  |
| grafana | `public/app/features/panel/table/addTableCustomPanelOptions.ts` | verified |  |
| grafana | `public/app/features/provisioning/components/utils/newBranchName.ts` | verified |  |
| grafana | `public/app/plugins/datasource/cloudwatch/mocks/cloudwatch-sql-test-data/singleLineTwoQueries.ts` | verified |  |
| grafana | `public/app/plugins/datasource/graphite/components/GraphiteTextEditor.tsx` | verified |  |
| grafana | `public/app/plugins/datasource/loki/dataquery.gen.ts` | verified |  |
| grafana | `public/app/plugins/panel/news/component/News.tsx` | verified |  |
