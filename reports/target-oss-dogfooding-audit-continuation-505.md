# Target OSS no-LLM dogfooding audit — continuation 505 (batch 506)

Run: 2026-07-23T07:14:06.291379+00:00

## Summary

- Files audited: 50
- Verified: 50
- Refuted: 0
- Unverifiable: 0

All sampled files passed no-LLM verification; no new tool-side fixes were required.

## Sample details

| repo | file | status | notes |
|------|------|--------|-------|
| go | `src/cmd/cgo/internal/testcshared/cshared_test.go` | verified |  |
| go | `src/cmd/compile/internal/base/hashdebug.go` | verified |  |
| go | `src/cmd/compile/internal/types2/main_test.go` | verified |  |
| go | `src/cmd/compile/internal/wasm/simdssa.go` | verified |  |
| go | `src/cmd/go/internal/lockedfile/internal/filelock/filelock_unix.go` | verified |  |
| go | `src/cmd/internal/obj/mips/obj0.go` | verified |  |
| go | `src/crypto/pbkdf2/pbkdf2.go` | verified |  |
| go | `src/go/types/version.go` | verified |  |
| go | `src/internal/goos/gengoos.go` | verified |  |
| go | `src/runtime/defs1_solaris_amd64.go` | verified |  |
| go | `src/runtime/hexdump_test.go` | verified |  |
| go | `src/syscall/ztypes_dragonfly_amd64.go` | verified |  |
| go | `test/fixedbugs/bug089.go` | verified |  |
| go | `test/fixedbugs/bug323.go` | verified |  |
| go | `test/fixedbugs/issue27557.go` | verified |  |
| go | `test/fixedbugs/issue28430.go` | verified |  |
| go | `test/fixedbugs/issue56220.go` | verified |  |
| go | `test/fixedbugs/issue6703x.go` | verified |  |
| go | `test/fixedbugs/issue7525e.go` | verified |  |
| go | `test/typeparam/ifaceconv.go` | verified |  |
| go | `test/typeparam/issue47925.go` | verified |  |
| go | `test/typeparam/mdempsky/15.go` | verified |  |
| go | `test/unsafe_slice_data.go` | verified |  |
| grafana | `apps/dashboard/pkg/migration/conversion/v2beta1_to_v2alpha1_test.go` | verified |  |
| grafana | `apps/dashboard/pkg/migration/frontend_defaults_test.go` | verified |  |
| grafana | `apps/plugins/pkg/app/install/registrar_test.go` | verified |  |
| grafana | `apps/provisioning/pkg/controller/historyjob.go` | verified |  |
| grafana | `packages/grafana-runtime/src/services/LocationSrv.ts` | verified |  |
| grafana | `packages/grafana-test-utils/src/matchers/utils.ts` | verified |  |
| grafana | `pkg/infra/usagestats/statscollector/service.go` | verified |  |
| grafana | `pkg/services/cloudmigration/cloudmigrationimpl/snapshot_mgmt_alerts.go` | verified |  |
| grafana | `pkg/services/sqlstore/migrations/usermig/test/service_account_test.go` | verified |  |
| grafana | `pkg/services/sqlstore/sqlstore.go` | verified |  |
| grafana | `pkg/services/star/starimpl/store.go` | verified |  |
| grafana | `pkg/services/user/userimpl/verifier_test.go` | verified |  |
| grafana | `pkg/services/user/userk8s/user_test.go` | verified |  |
| grafana | `pkg/web/binding_test.go` | verified |  |
| grafana | `public/app/core/components/AppChrome/AppChromeExtensionPoint.tsx` | verified |  |
| grafana | `public/app/core/utils/version.ts` | verified |  |
| grafana | `public/app/features/commandPalette/scopes/ScopesRow.tsx` | verified |  |
| grafana | `public/app/features/dashboard-scene/settings/variables/components/QueryEditor.tsx` | verified |  |
| grafana | `public/app/features/datasources/components/DashboardsTable.tsx` | verified |  |
| grafana | `public/app/features/explore/Graph/useStructureRev.ts` | verified |  |
| grafana | `public/app/features/plugins/admin/components/PluginDetailsHeaderDependencies.tsx` | verified |  |
| grafana | `public/app/features/search/page/selection.ts` | verified |  |
| grafana | `public/app/plugins/datasource/grafana-postgresql-datasource/types.ts` | verified |  |
| grafana | `public/app/plugins/panel/canvas/panelcfg.gen.ts` | verified |  |
| grafana | `public/app/plugins/panel/news/rss.ts` | verified |  |
| grafana | `public/app/plugins/panel/nodeGraph/module.tsx` | verified |  |
| grafana | `public/app/plugins/panel/timeseries/plugins/ExemplarsPlugin.tsx` | verified |  |
