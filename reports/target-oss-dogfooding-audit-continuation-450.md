# Target OSS no-LLM dogfooding audit — continuation 450 (batch 451)

Run: 2026-07-23T03:18:06.235450+00:00

## Summary

- Files audited: 50
- Verified: 50
- Refuted: 0
- Unverifiable: 0

All sampled files passed no-LLM verification; no new tool-side fixes were required.

## Sample details

| repo | file | status | notes |
|------|------|--------|-------|
| go | `src/cmd/compile/internal/inline/inlheur/funcprops_test.go` | verified |  |
| go | `src/cmd/compile/internal/ssa/rewriteS390X.go` | verified |  |
| go | `src/cmd/compile/internal/types2/operand.go` | verified |  |
| go | `src/crypto/cipher/io.go` | verified |  |
| go | `src/crypto/ed25519/ed25519vectors_test.go` | verified |  |
| go | `src/encoding/json/v2_example_test.go` | verified |  |
| go | `src/go/types/eval.go` | verified |  |
| go | `src/go/types/iter.go` | verified |  |
| go | `src/go/types/object_test.go` | verified |  |
| go | `src/internal/obscuretestdata/obscuretestdata.go` | verified |  |
| go | `src/internal/poll/fd_unixjs.go` | verified |  |
| go | `src/internal/strconv/fp_test.go` | verified |  |
| go | `src/net/http/mapping_test.go` | verified |  |
| go | `src/os/statat_unix.go` | verified |  |
| go | `src/unique/handle.go` | verified |  |
| go | `test/abi/part_live.go` | verified |  |
| go | `test/fixedbugs/bug313.go` | verified |  |
| go | `test/fixedbugs/bug507.dir/c.go` | verified |  |
| go | `test/fixedbugs/issue38359.go` | verified |  |
| go | `test/fixedbugs/issue42058a.go` | verified |  |
| go | `test/fixedbugs/issue43479.dir/b.go` | verified |  |
| go | `test/typeparam/issue48716.dir/a.go` | verified |  |
| go | `test/typeparam/mdempsky/12.dir/a.go` | verified |  |
| grafana | `apps/playlist/pkg/apis/playlist/v0alpha1/playlist_object_gen.go` | verified |  |
| grafana | `pkg/apiserver/endpoints/filters/upstream_trace_link.go` | verified |  |
| grafana | `pkg/expr/classic/classic_test.go` | verified |  |
| grafana | `pkg/registry/apis/secret/register_test.go` | verified |  |
| grafana | `pkg/services/authn/clients/oauth.go` | verified |  |
| grafana | `pkg/services/frontend/csp_middleware.go` | verified |  |
| grafana | `pkg/services/licensing/oss.go` | verified |  |
| grafana | `pkg/services/login/authinfotest/auth_info_store_mock.go` | verified |  |
| grafana | `pkg/services/ngalert/writer/prom_test.go` | verified |  |
| grafana | `pkg/services/secrets/kvstore/sql.go` | verified |  |
| grafana | `pkg/services/sqlstore/migrations/accesscontrol/test/seed_assign_mig_test.go` | verified |  |
| grafana | `pkg/storage/unified/sql/rvmanager/rv_manager.go` | verified |  |
| grafana | `pkg/tests/apis/provisioning/jobs/instanceauth/exportjob_auth_test.go` | verified |  |
| grafana | `pkg/tests/apis/provisioning/orgs/helper_test.go` | verified |  |
| grafana | `public/app/features/alerting/unified/insights/mimir/rules/EvalSuccessVsFailuresScene.tsx` | verified |  |
| grafana | `public/app/features/alerting/unified/rule-list/components/ListSection.tsx` | verified |  |
| grafana | `public/app/features/dashboard-scene/edit-pane/dashboard/DashboardBasicOptions.tsx` | verified |  |
| grafana | `public/app/features/dashboard/utils/dashboard.ts` | verified |  |
| grafana | `public/app/features/explore/TraceView/components/TraceTimelineViewer/SpanBarRow.tsx` | verified |  |
| grafana | `public/app/features/explore/extensions/AddToDashboard/ExploreToDashboardPanel.tsx` | verified |  |
| grafana | `public/app/features/expressions/types.ts` | verified |  |
| grafana | `public/app/features/geo/utils/location.ts` | verified |  |
| grafana | `public/app/plugins/datasource/azuremonitor/components/TracesQueryEditor/Filter.tsx` | verified |  |
| grafana | `public/app/plugins/datasource/loki/components/LokiQueryEditorForAlerting.tsx` | verified |  |
| grafana | `public/app/plugins/panel/canvas/editor/element/DataLinksEditor.tsx` | verified |  |
| grafana | `public/app/plugins/panel/debug/panelcfg.gen.ts` | verified |  |
| grafana | `public/app/plugins/panel/heatmap/tooltip/utils.ts` | verified |  |
