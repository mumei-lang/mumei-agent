# Target OSS no-LLM dogfooding audit — continuation 376 (batch 377)

Run: 2026-07-22T22:34:17.615521+00:00

## Summary

- Files audited: 50
- Verified: 50
- Refuted: 0
- Unverifiable: 0

All sampled files passed no-LLM verification; no new tool-side fixes were required.

## Sample details

| repo | file | status | notes |
|------|------|--------|-------|
| go | `src/cmd/cgo/internal/test/issue26743/a.go` | verified |  |
| go | `src/cmd/compile/internal/ssa/fmahash_test.go` | verified |  |
| go | `src/cmd/compile/internal/ssa/lower.go` | verified |  |
| go | `src/cmd/go/internal/modfetch/cache_readonly_test.go` | verified |  |
| go | `src/crypto/internal/fips140/mlkem/field_test.go` | verified |  |
| go | `src/crypto/internal/fips140/sha512/sha512block_s390x.go` | verified |  |
| go | `src/crypto/internal/fips140test/nistec_ordinv_fips140v1.0_test.go` | verified |  |
| go | `src/crypto/x509/root_bsd.go` | verified |  |
| go | `src/internal/syscall/unix/nonblocking_unix.go` | verified |  |
| go | `src/math/big/arith_amd64_test.go` | verified |  |
| go | `src/math/big/calibrate_test.go` | verified |  |
| go | `src/net/conn_test.go` | verified |  |
| go | `src/net/textproto/reader_test.go` | verified |  |
| go | `src/runtime/race/internal/amd64v3/doc.go` | verified |  |
| go | `src/syscall/syscall_netbsd_arm64.go` | verified |  |
| go | `src/unicode/graphic.go` | verified |  |
| go | `test/fixedbugs/issue22076.go` | verified |  |
| go | `test/fixedbugs/issue27732a.go` | verified |  |
| go | `test/fixedbugs/issue6703c.go` | verified |  |
| go | `test/fixedbugs/issue79197.go` | verified |  |
| go | `test/typeparam/issue50121b.dir/b.go` | verified |  |
| grafana | `apps/alerting/rules/plugin/src/generated/alertrule/v0alpha1/alertrule_object_gen.ts` | verified |  |
| grafana | `apps/dashboard/pkg/apis/dashboard/v2/zz_generated.openapi.go` | verified |  |
| grafana | `apps/iam/pkg/apis/iam/v0alpha1/team_deleteteammember_response_body_types_gen.go` | verified |  |
| grafana | `apps/iam/pkg/apis/iam/v0alpha1/teamlbacrule_codec_gen.go` | verified |  |
| grafana | `e2e-playwright/test-plugins/grafana-test-panel/webpack.config.ts` | verified |  |
| grafana | `packages/grafana-api-clients/src/clients/rtkq/playlist/v1/endpoints.gen.ts` | verified |  |
| grafana | `packages/grafana-data/src/utils/nodeGraph.ts` | verified |  |
| grafana | `packages/grafana-ui/src/components/Branding/BrandingContext.tsx` | verified |  |
| grafana | `packages/grafana-ui/src/utils/dom.ts` | verified |  |
| grafana | `pkg/api/basic_auth_test.go` | verified |  |
| grafana | `pkg/expr/ml/node_test.go` | verified |  |
| grafana | `pkg/plugins/manager/process/process.go` | verified |  |
| grafana | `pkg/services/libraryelements/k8s_conversion_test.go` | verified |  |
| grafana | `pkg/services/ngalert/state/persister_noop.go` | verified |  |
| grafana | `pkg/services/searchusers/filters/filters.go` | verified |  |
| grafana | `pkg/services/sqlstore/session.go` | verified |  |
| grafana | `pkg/storage/unified/apistore/stream_test.go` | verified |  |
| grafana | `pkg/storage/unified/testing/benchmark.go` | verified |  |
| grafana | `public/app/core/components/AppChrome/TopBar/TopBarExtensionPoint.tsx` | verified |  |
| grafana | `public/app/features/alerting/unified/components/receivers/form/GenerateAlertDataModal.tsx` | verified |  |
| grafana | `public/app/features/browse-dashboards/components/BrowseActions/BrowseActions.tsx` | verified |  |
| grafana | `public/app/features/dashboard-scene/inspect/InspectJsonTab.tsx` | verified |  |
| grafana | `public/app/features/dashboard-scene/scene/layout-tabs/TabItemEditor.tsx` | verified |  |
| grafana | `public/app/features/dashboard/dashgrid/DashboardLibrary/SuggestedDashboardsList/ListHeader.tsx` | verified |  |
| grafana | `public/app/features/explore/TraceView/components/TraceTimelineViewer/SpanDetail/icons/ServiceHexagonIcon.tsx` | verified |  |
| grafana | `public/app/features/plugins/admin/components/UpdateAllModal.tsx` | verified |  |
| grafana | `public/app/features/scopes/selector/RecentScopes.tsx` | verified |  |
| grafana | `public/app/features/transformers/docs/content.ts` | verified |  |
| grafana | `scripts/webpack/plugins/FilterStatsPlugin.ts` | verified |  |
