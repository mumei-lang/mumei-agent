# Target OSS no-LLM dogfooding audit — continuation 524 (batch 525)

Run: 2026-07-23T08:16:24.215329+00:00

## Summary

- Files audited: 50
- Verified: 50
- Refuted: 0
- Unverifiable: 0

All sampled files passed no-LLM verification; no new tool-side fixes were required.

## Sample details

| repo | file | status | notes |
|------|------|--------|-------|
| go | `src/cmd/compile/internal/bitvec/bv.go` | verified |  |
| go | `src/cmd/distpack/pack.go` | verified |  |
| go | `src/crypto/internal/cryptotest/implementations.go` | verified |  |
| go | `src/crypto/internal/fips140/nistec/fiat/p224_fiat64.go` | verified |  |
| go | `src/encoding/xml/example_marshaling_test.go` | verified |  |
| go | `src/internal/bytealg/index_s390x.go` | verified |  |
| go | `src/internal/goexperiment/exp_arenas_on.go` | verified |  |
| go | `src/internal/trace/traceviewer/emitter.go` | verified |  |
| go | `src/runtime/fds_nonunix.go` | verified |  |
| go | `src/runtime/histogram.go` | verified |  |
| go | `src/strings/search_test.go` | verified |  |
| go | `src/syscall/zsyscall_linux_arm64.go` | verified |  |
| go | `src/uuid/uuid_test.go` | verified |  |
| go | `test/fixedbugs/bug103.go` | verified |  |
| go | `test/fixedbugs/bug321.go` | verified |  |
| go | `test/fixedbugs/bug357.go` | verified |  |
| go | `test/fixedbugs/issue11256.go` | verified |  |
| go | `test/fixedbugs/issue45706.go` | verified |  |
| go | `test/fixedbugs/issue5105.dir/b.go` | verified |  |
| go | `test/fixedbugs/issue5614.dir/x.go` | verified |  |
| go | `test/peano.go` | verified |  |
| go | `test/range2.go` | verified |  |
| go | `test/typeparam/append.go` | verified |  |
| go | `test/typeparam/issue49027.dir/a.go` | verified |  |
| grafana | `apps/dashboard/pkg/migration/schemaversion/v20_test.go` | verified |  |
| grafana | `apps/provisioning/pkg/generated/applyconfiguration/provisioning/v0alpha1/migratejoboptions.go` | verified |  |
| grafana | `apps/provisioning/pkg/generated/applyconfiguration/provisioning/v0alpha1/quotastatus.go` | verified |  |
| grafana | `packages/grafana-data/src/field/fieldComparers.ts` | verified |  |
| grafana | `packages/grafana-runtime/src/services/pluginMeta/panels.ts` | verified |  |
| grafana | `pkg/middleware/cookies/cookies_test.go` | verified |  |
| grafana | `pkg/plugins/log/ifaces.go` | verified |  |
| grafana | `pkg/registry/apis/provisioning/jobs/migrate/clean_test.go` | verified |  |
| grafana | `pkg/services/authn/clients/constants.go` | verified |  |
| grafana | `pkg/services/ngalert/notifier/merge/merge.go` | verified |  |
| grafana | `pkg/services/ngalert/store/alert_rule_labels_test.go` | verified |  |
| grafana | `pkg/storage/unified/resource/standard_search_fields.go` | verified |  |
| grafana | `pkg/tests/apis/plugins/discovery_test.go` | verified |  |
| grafana | `public/app/features/apiserver/discovery.ts` | verified |  |
| grafana | `public/app/features/connections/pages/PermissionsFeatureHighlightPage.tsx` | verified |  |
| grafana | `public/app/features/correlations/Forms/ConfigureCorrelationTargetForm.tsx` | verified |  |
| grafana | `public/app/features/dashboard/components/SaveDashboard/SaveDashboardButton.tsx` | verified |  |
| grafana | `public/app/features/dashboard/dashgrid/DashboardEmpty/DashboardEmpty.tsx` | verified |  |
| grafana | `public/app/features/dashboard/services/SnapshotSrv.ts` | verified |  |
| grafana | `public/app/features/explore/TraceView/components/TraceTimelineViewer/SpanDetail/pyroscope-types.ts` | verified |  |
| grafana | `public/app/features/logs/components/panel/LogListSearch.tsx` | verified |  |
| grafana | `public/app/features/plugins/importer/importPluginModule.ts` | verified |  |
| grafana | `public/app/features/scopes/dashboards/types.ts` | verified |  |
| grafana | `public/app/features/transformers/editors/RenameByRegexTransformer.tsx` | verified |  |
| grafana | `public/app/plugins/datasource/cloudwatch/mocks/metric-math-test-data/withinStringQuery.ts` | verified |  |
| grafana | `public/app/plugins/panel/geomap/utils/selection.ts` | verified |  |
