# Target OSS no-LLM dogfooding audit — continuation 529 (batch 530)

Run: 2026-07-23T08:35:16.771390+00:00

## Summary

- Files audited: 50
- Verified: 50
- Refuted: 0
- Unverifiable: 0

All sampled files passed no-LLM verification; no new tool-side fixes were required.

## Sample details

| repo | file | status | notes |
|------|------|--------|-------|
| go | `src/cmd/cgo/internal/test/issue27340/a.go` | verified |  |
| go | `src/cmd/internal/obj/ppc64/asm9.go` | verified |  |
| go | `src/crypto/hmac/hmac_wycheproof_test.go` | verified |  |
| go | `src/crypto/internal/fips140/nistec/fiat/p256.go` | verified |  |
| go | `src/crypto/internal/fips140test/acvp_test.go` | verified |  |
| go | `src/crypto/mlkem/example_test.go` | verified |  |
| go | `src/go/doc/headscan.go` | verified |  |
| go | `src/go/types/api_predicates.go` | verified |  |
| go | `src/internal/cpu/export_test.go` | verified |  |
| go | `src/internal/poll/fd_windows.go` | verified |  |
| go | `src/math/dim_noasm.go` | verified |  |
| go | `src/net/http/routing_index.go` | verified |  |
| go | `src/reflect/stubs_ppc64x.go` | verified |  |
| go | `src/regexp/regexp.go` | verified |  |
| go | `src/runtime/debug.go` | verified |  |
| go | `src/runtime/signal_linux_amd64.go` | verified |  |
| go | `src/strconv/doc.go` | verified |  |
| go | `src/testing/testing.go` | verified |  |
| go | `test/closure3.dir/main.go` | verified |  |
| go | `test/fixedbugs/bug324.dir/prog.go` | verified |  |
| go | `test/fixedbugs/bug515.go` | verified |  |
| go | `test/fixedbugs/issue14520a.go` | verified |  |
| go | `test/fixedbugs/issue17640.go` | verified |  |
| go | `test/fixedbugs/issue35157.go` | verified |  |
| go | `test/fixedbugs/issue53600.go` | verified |  |
| go | `test/fixedbugs/issue54159.go` | verified |  |
| go | `test/syntax/semi6.go` | verified |  |
| grafana | `e2e-playwright/dashboard-new-layouts/page-objects/PageObject.ts` | verified |  |
| grafana | `packages/grafana-ui/src/components/EmptyState/EmptyState.tsx` | verified |  |
| grafana | `pkg/api/org_invite_test.go` | verified |  |
| grafana | `pkg/plugins/repo/version.go` | verified |  |
| grafana | `pkg/registry/apis/iam/user/mutate_test.go` | verified |  |
| grafana | `pkg/registry/apis/iam/user/validate_test.go` | verified |  |
| grafana | `pkg/registry/apps/alerting/notifications/timeinterval/conversions.go` | verified |  |
| grafana | `pkg/registry/apps/annotation/storepb/v1/store.pb.go` | verified |  |
| grafana | `pkg/server/server_test.go` | verified |  |
| grafana | `pkg/services/anonymous/anonimpl/impl_test.go` | verified |  |
| grafana | `pkg/services/ngalert/api/api_configuration.go` | verified |  |
| grafana | `pkg/services/ngalert/state/cache.go` | verified |  |
| grafana | `pkg/services/pluginsintegration/dashboards/ifaces.go` | verified |  |
| grafana | `pkg/services/serviceaccounts/api/api.go` | verified |  |
| grafana | `pkg/services/team/teamapi/team.go` | verified |  |
| grafana | `pkg/tests/apis/annotations/annotations_test.go` | verified |  |
| grafana | `public/app/core/components/Select/UserPicker.tsx` | verified |  |
| grafana | `public/app/features/alerting/unified/rule-list/hooks/useDataSourceLoadingReporter.ts` | verified |  |
| grafana | `public/app/features/dashboard-scene/panel-edit/PanelEditNext/QueryEditor/Sidebar/DraggableList/DraggableList.tsx` | verified |  |
| grafana | `public/app/features/dashboard-scene/utils/panelStyleConfigs.ts` | verified |  |
| grafana | `public/app/features/dashboard/api/dashboard_api.ts` | verified |  |
| grafana | `public/app/plugins/datasource/grafana/components/RandomWalkEditor.tsx` | verified |  |
| grafana | `public/test/test-utils.tsx` | verified |  |
