# Target OSS no-LLM dogfooding audit — continuation 535 (batch 536)

Run: 2026-07-23T09:13:00.227417+00:00

## Summary

- Files audited: 50
- Verified: 50
- Refuted: 0
- Unverifiable: 0

All sampled files passed no-LLM verification; no new tool-side fixes were required.

## Sample details

| repo | file | status | notes |
|------|------|--------|-------|
| go | `src/cmd/compile/internal/inline/inlheur/debugflags_test.go` | verified |  |
| go | `src/cmd/compile/internal/ssa/rewriteLOONG64latelower.go` | verified |  |
| go | `src/cmd/compile/internal/syntax/dumper.go` | verified |  |
| go | `src/cmd/go/internal/cache/hash.go` | verified |  |
| go | `src/cmd/internal/archive/archive.go` | verified |  |
| go | `src/cmd/link/internal/ld/xcoff.go` | verified |  |
| go | `src/container/list/example_test.go` | verified |  |
| go | `src/internal/cpu/cpu_ppc64x.go` | verified |  |
| go | `src/io/fs/sub_test.go` | verified |  |
| go | `src/os/exec/lp_test.go` | verified |  |
| go | `src/runtime/asan/asan.go` | verified |  |
| go | `src/runtime/stubs_wasm.go` | verified |  |
| go | `test/codegen/slices.go` | verified |  |
| go | `test/const.go` | verified |  |
| go | `test/fixedbugs/bug504.dir/main.go` | verified |  |
| go | `test/fixedbugs/issue18459.go` | verified |  |
| go | `test/fixedbugs/issue24799.go` | verified |  |
| go | `test/fixedbugs/issue27695c.go` | verified |  |
| go | `test/fixedbugs/issue8158.go` | verified |  |
| go | `test/map1.go` | verified |  |
| go | `test/nilptr4.go` | verified |  |
| go | `test/typeparam/graph.go` | verified |  |
| go | `test/typeparam/issue49497.dir/main.go` | verified |  |
| go | `test/uintptrescapes.go` | verified |  |
| grafana | `apps/provisioning/pkg/repository/lister.go` | verified |  |
| grafana | `e2e-playwright/test-plugins/grafana-test-panel/components/SimplePanel.tsx` | verified |  |
| grafana | `packages/grafana-data/src/dataframe/utils.ts` | verified |  |
| grafana | `packages/grafana-runtime/src/services/backendSrv.ts` | verified |  |
| grafana | `packages/grafana-schema/src/raw/composable/trend/panelcfg/x/types.gen.ts` | verified |  |
| grafana | `pkg/apis/userstorage/v0alpha1/types.go` | verified |  |
| grafana | `pkg/plugins/auth/models.go` | verified |  |
| grafana | `pkg/registry/apis/dashboard/home/reader_test.go` | verified |  |
| grafana | `pkg/registry/apis/secret/service/consolidation_test.go` | verified |  |
| grafana | `pkg/services/accesscontrol/middleware_test.go` | verified |  |
| grafana | `pkg/services/accesscontrol/ossaccesscontrol/testutil/testutil.go` | verified |  |
| grafana | `pkg/services/authn/clients/ldap.go` | verified |  |
| grafana | `pkg/services/authz/zanzana/server/server_contextuals_test.go` | verified |  |
| grafana | `pkg/tsdb/cloudwatch/models/types.go` | verified |  |
| grafana | `pkg/tsdb/influxdb/simplejson/simplejson_go11.go` | verified |  |
| grafana | `public/app/core/components/AccessControl/PermissionListItem.tsx` | verified |  |
| grafana | `public/app/core/services/mousetrap/Mousetrap.ts` | verified |  |
| grafana | `public/app/features/alerting/unified/components/rule-editor/FolderSelector.tsx` | verified |  |
| grafana | `public/app/features/alerting/unified/mocks/server/handlers/k8s/inhibitionRules.k8s.ts` | verified |  |
| grafana | `public/app/features/dashboard-scene/settings/variables/components/AdHocOriginFiltersController.ts` | verified |  |
| grafana | `public/app/features/dashboard-scene/settings/version-history/DiffValues.tsx` | verified |  |
| grafana | `public/app/features/dashboard/components/ShareModal/ShareExport.tsx` | verified |  |
| grafana | `public/app/features/explore/QueriesDrawer/mocks.tsx` | verified |  |
| grafana | `public/app/features/provisioning/components/BulkActions/BulkDeleteProvisionedResource.tsx` | verified |  |
| grafana | `public/app/plugins/datasource/jaeger/CheatSheet.tsx` | verified |  |
| grafana | `scripts/cli/themeTemplates/_variables.dark.scss.tmpl.ts` | verified |  |
