# Target OSS no-LLM dogfooding audit — continuation 545 (batch 546)

Run: 2026-07-23T10:00:21.767315+00:00

## Summary

- Files audited: 50
- Verified: 50
- Refuted: 0
- Unverifiable: 0

All sampled files passed no-LLM verification; no new tool-side fixes were required.

## Sample details

| repo | file | status | notes |
|------|------|--------|-------|
| go | `src/cmd/compile/internal/ssagen/simdWasmintrinsics.go` | verified |  |
| go | `src/cmd/compile/internal/types2/range.go` | verified |  |
| go | `src/cmd/go/internal/cache/prog.go` | verified |  |
| go | `src/cmd/go/internal/fsys/glob.go` | verified |  |
| go | `src/cmd/internal/obj/wasm/anames.go` | verified |  |
| go | `src/cmd/vet/doc.go` | verified |  |
| go | `src/crypto/fips140/enforcement_test.go` | verified |  |
| go | `src/crypto/internal/fips140/ecdsa/ecdsa_noasm.go` | verified |  |
| go | `src/go/token/token_test.go` | verified |  |
| go | `src/internal/pkgbits/support.go` | verified |  |
| go | `src/internal/runtime/gc/internal/gen/regalloc.go` | verified |  |
| go | `src/internal/runtime/gc/scan/scan_amd64_test.go` | verified |  |
| go | `src/maps/example_test.go` | verified |  |
| go | `src/os/exec/exec_other_test.go` | verified |  |
| go | `src/os/executable_procfs.go` | verified |  |
| go | `src/runtime/checkptr_test.go` | verified |  |
| go | `src/runtime/proflabel.go` | verified |  |
| go | `src/runtime/runtime_unix_test.go` | verified |  |
| go | `src/time/export_windows_test.go` | verified |  |
| go | `test/abi/many_intstar_input.go` | verified |  |
| go | `test/escape_goto.go` | verified |  |
| go | `test/fixedbugs/issue37246.go` | verified |  |
| go | `test/fixedbugs/issue42401.dir/a.go` | verified |  |
| go | `test/fixedbugs/issue42727.go` | verified |  |
| go | `test/fixedbugs/issue49143.dir/p.go` | verified |  |
| go | `test/fixedbugs/issue5172.go` | verified |  |
| go | `test/typeparam/issue48337a.dir/main.go` | verified |  |
| go | `test/typeparam/issue50481b.dir/b.go` | verified |  |
| go | `test/typeparam/stringer.go` | verified |  |
| go | `test/typeswitch3.go` | verified |  |
| grafana | `apps/iam/pkg/apis/iam/v0alpha1/direct_permissions_search.go` | verified |  |
| grafana | `apps/provisioning/pkg/connection/github/connection.go` | verified |  |
| grafana | `packages/grafana-data/src/datetime/rangeutil.ts` | verified |  |
| grafana | `packages/grafana-i18n/src/types/dates.d.ts` | verified |  |
| grafana | `packages/grafana-ui/src/components/FormLabel/FormLabel.tsx` | verified |  |
| grafana | `packages/grafana-ui/src/components/LoadingPlaceholder/LoadingPlaceholder.tsx` | verified |  |
| grafana | `packages/grafana-ui/src/components/Menu/Menu.tsx` | verified |  |
| grafana | `pkg/services/ldap/multildap/multildap.go` | verified |  |
| grafana | `pkg/services/live/liveplugin/plugin.go` | verified |  |
| grafana | `pkg/services/live/pushurl/values_test.go` | verified |  |
| grafana | `pkg/services/pluginsintegration/keyretriever/retriever.go` | verified |  |
| grafana | `pkg/setting/date_formats.go` | verified |  |
| grafana | `pkg/tsdb/cloudwatch/services/list_metrics.go` | verified |  |
| grafana | `pkg/tsdb/grafana-testdata-datasource/sims/flight_path.go` | verified |  |
| grafana | `public/app/features/alerting/unified/insights/grafana/MostFiredInstancesTable.tsx` | verified |  |
| grafana | `public/app/features/explore/extensions/getExploreExtensionConfigs.tsx` | verified |  |
| grafana | `public/app/features/explore/hooks/useStateSync/synchronizer/init.ts` | verified |  |
| grafana | `public/app/features/provisioning/Connection/ConnectionFormPage.tsx` | verified |  |
| grafana | `public/app/plugins/datasource/influxdb/components/editor/query/influxql/utils/toSelectableValue.ts` | verified |  |
| grafana | `public/app/plugins/panel/canvas/editor/layer/TreeNavigationEditor.tsx` | verified |  |
