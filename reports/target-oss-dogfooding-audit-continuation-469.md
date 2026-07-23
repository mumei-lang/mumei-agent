# Target OSS no-LLM dogfooding audit — continuation 469 (batch 470)

Run: 2026-07-23T04:41:16.315373+00:00

## Summary

- Files audited: 50
- Verified: 50
- Refuted: 0
- Unverifiable: 0

All sampled files passed no-LLM verification; no new tool-side fixes were required.

## Sample details

| repo | file | status | notes |
|------|------|--------|-------|
| go | `src/cmd/compile/internal/gc/export.go` | verified |  |
| go | `src/cmd/compile/internal/inline/inlheur/funcpropbits_string.go` | verified |  |
| go | `src/cmd/compile/internal/test/issue57434_test.go` | verified |  |
| go | `src/cmd/compile/internal/test/test.go` | verified |  |
| go | `src/cmd/link/internal/loong64/l.go` | verified |  |
| go | `src/crypto/internal/fips140/subtle/xor_generic.go` | verified |  |
| go | `src/crypto/x509/pkcs8.go` | verified |  |
| go | `src/net/http/internal/http2/transport_internal_test.go` | verified |  |
| go | `src/os/path_windows.go` | verified |  |
| go | `src/simd/archsimd/doc.go` | verified |  |
| go | `src/simd/archsimd/maskmerge_gen_amd64.go` | verified |  |
| go | `src/simd/internal/bridge/simd_types_emulated.go` | verified |  |
| go | `src/time/zoneinfo_ios.go` | verified |  |
| go | `test/codegen/shortcircuit.go` | verified |  |
| go | `test/escape3.go` | verified |  |
| go | `test/fixedbugs/issue18911.go` | verified |  |
| go | `test/fixedbugs/issue24449.go` | verified |  |
| go | `test/fixedbugs/issue35739.dir/a.go` | verified |  |
| go | `test/fixedbugs/issue49143.dir/c.go` | verified |  |
| go | `test/fixedbugs/issue61908.go` | verified |  |
| go | `test/typeparam/absdiff2.go` | verified |  |
| go | `test/typeparam/issue48337b.go` | verified |  |
| grafana | `apps/alerting/alertenrichment/pkg/apis/alertenrichment/v1beta1/zz_generated.deepcopy.go` | verified |  |
| grafana | `apps/annotation/pkg/apis/annotation/v0alpha1/annotation_status_gen.go` | verified |  |
| grafana | `apps/provisioning/pkg/repository/webhook.go` | verified |  |
| grafana | `packages/grafana-flamegraph/src/FlameGraph/treeTransforms.ts` | verified |  |
| grafana | `packages/grafana-sql/src/components/visual-query-builder/VisualEditor.tsx` | verified |  |
| grafana | `packages/grafana-ui/.storybook/manager.ts` | verified |  |
| grafana | `pkg/api/frontend_metrics.go` | verified |  |
| grafana | `pkg/cmd/grafana-cli/commands/upgrade_command_test.go` | verified |  |
| grafana | `pkg/codegen/generators.go` | verified |  |
| grafana | `pkg/registry/apis/secret/encryption/kmsproviders/grafana_provider.go` | verified |  |
| grafana | `pkg/services/annotations/testutil/testutil.go` | verified |  |
| grafana | `pkg/services/libraryelements/writers.go` | verified |  |
| grafana | `pkg/services/live/features/plugin.go` | verified |  |
| grafana | `pkg/services/ngalert/accesscontrol/roles_test.go` | verified |  |
| grafana | `pkg/services/ngalert/schedule/recording_rule_test.go` | verified |  |
| grafana | `pkg/storage/secret/metadata/decrypt_store.go` | verified |  |
| grafana | `pkg/storage/unified/resource/lease/lease_test.go` | verified |  |
| grafana | `public/app/features/actions/ActionEditor.tsx` | verified |  |
| grafana | `public/app/features/alerting/unified/triage/triagePredefinedSearches.ts` | verified |  |
| grafana | `public/app/features/dashboard-scene/settings/variables/components/AdHocVariableForm.tsx` | verified |  |
| grafana | `public/app/features/explore/ExplorePage.tsx` | verified |  |
| grafana | `public/app/features/geo/format/geojson.ts` | verified |  |
| grafana | `public/app/features/manage-dashboards/components/SnapshotListTableRow.tsx` | verified |  |
| grafana | `public/app/features/plugins/admin/components/PluginInsights.tsx` | verified |  |
| grafana | `public/app/features/variables/adhoc/adapter.ts` | verified |  |
| grafana | `public/app/plugins/datasource/azuremonitor/dataquery.gen.ts` | verified |  |
| grafana | `public/app/plugins/panel/canvas/editor/element/utils.ts` | verified |  |
| grafana | `public/app/plugins/panel/gettingstarted/GettingStarted.tsx` | verified |  |
