# Target OSS no-LLM dogfooding audit — continuation 439 (batch 440)

Run: 2026-07-23T02:28:17.607391+00:00

## Summary

- Files audited: 50
- Verified: 50
- Refuted: 0
- Unverifiable: 0

All sampled files passed no-LLM verification; no new tool-side fixes were required.

## Sample details

| repo | file | status | notes |
|------|------|--------|-------|
| go | `src/cmd/compile/internal/riscv64/galign.go` | verified |  |
| go | `src/cmd/compile/internal/test/inst_test.go` | verified |  |
| go | `src/cmd/go/internal/telemetrystats/telemetrystats_bootstrap.go` | verified |  |
| go | `src/crypto/internal/fips140/edwards25519/edwards25519_test.go` | verified |  |
| go | `src/crypto/x509/pkcs1.go` | verified |  |
| go | `src/encoding/base32/base32.go` | verified |  |
| go | `src/internal/syscall/unix/sysnum_linux_arm.go` | verified |  |
| go | `src/math/big/floatmarsh_test.go` | verified |  |
| go | `src/net/conf.go` | verified |  |
| go | `src/runtime/defs_dragonfly_amd64.go` | verified |  |
| go | `src/runtime/symtab.go` | verified |  |
| go | `src/simd/archsimd/_gen/simdgen/gen_simdMachineOps.go` | verified |  |
| go | `test/escape_map.go` | verified |  |
| go | `test/fixedbugs/bug248.go` | verified |  |
| go | `test/fixedbugs/bug358.go` | verified |  |
| go | `test/fixedbugs/bug504.dir/b.go` | verified |  |
| go | `test/fixedbugs/issue11371.go` | verified |  |
| go | `test/fixedbugs/issue4964.dir/b.go` | verified |  |
| go | `test/fixedbugs/issue8280.dir/b.go` | verified |  |
| go | `test/ken/rob1.go` | verified |  |
| grafana | `apps/alerting/rules/pkg/apis/alerting/v0alpha1/recordingrule_ext.go` | verified |  |
| grafana | `apps/playlist/pkg/apis/playlist/v1/playlist_spec_gen.go` | verified |  |
| grafana | `apps/provisioning/pkg/connection/github/client_test.go` | verified |  |
| grafana | `packages/grafana-ui/src/components/DataLinks/DataLinkButton.tsx` | verified |  |
| grafana | `pkg/expr/commands.go` | verified |  |
| grafana | `pkg/registry/apis/dashboard/mutation_test.go` | verified |  |
| grafana | `pkg/registry/apis/datasource/sub_proxy_test.go` | verified |  |
| grafana | `pkg/registry/apis/iam/metrics.go` | verified |  |
| grafana | `pkg/registry/apis/provisioning/jobs/sync/sync.go` | verified |  |
| grafana | `pkg/services/accesscontrol/authorize_in_org_test.go` | verified |  |
| grafana | `pkg/services/ngalert/image/cache.go` | verified |  |
| grafana | `pkg/services/sqlstore/transactions.go` | verified |  |
| grafana | `pkg/setting/setting_secure_socks_proxy.go` | verified |  |
| grafana | `pkg/tests/api/publicdashboards/public_dashboards_api_test.go` | verified |  |
| grafana | `pkg/tests/apis/iam/team/team_service_integration_test.go` | verified |  |
| grafana | `pkg/tsdb/mysql/macros.go` | verified |  |
| grafana | `public/app/core/components/Page/PageContents.tsx` | verified |  |
| grafana | `public/app/core/crash/crash.utils.ts` | verified |  |
| grafana | `public/app/features/alerting/unified/mocks.ts` | verified |  |
| grafana | `public/app/features/dashboard-scene/edit-pane/SectionVariablesList.tsx` | verified |  |
| grafana | `public/app/features/dashboard-scene/panel-edit/PanelEditNext/QueryEditor/Body/useTransformationSearchAndFilter.ts` | verified |  |
| grafana | `public/app/features/dashboard-scene/scene/new-toolbar/actions/DiscardLibraryPanelButton.tsx` | verified |  |
| grafana | `public/app/features/dashboard-scene/sharing/ExportButton/utils.ts` | verified |  |
| grafana | `public/app/features/explore/TraceView/components/TracePageHeader/SpanGraph/ViewingLayer.tsx` | verified |  |
| grafana | `public/app/features/home/HomeSection.tsx` | verified |  |
| grafana | `public/app/features/inspector/utils/utils.ts` | verified |  |
| grafana | `public/app/features/plugins/admin/hooks/usePluginDetailsTabs.tsx` | verified |  |
| grafana | `public/app/plugins/datasource/cloudwatch/language/cloudwatch-logs-sql/completion/statementPosition.ts` | verified |  |
| grafana | `public/app/plugins/panel/barchart/suggestions.ts` | verified |  |
| grafana | `public/app/plugins/panel/canvas/editor/options.ts` | verified |  |
