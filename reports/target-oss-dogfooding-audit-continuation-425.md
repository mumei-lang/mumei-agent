# Target OSS no-LLM dogfooding audit — continuation 425 (batch 426)

Run: 2026-07-23T01:43:30.287383+00:00

## Summary

- Files audited: 50
- Verified: 50
- Refuted: 0
- Unverifiable: 0

All sampled files passed no-LLM verification; no new tool-side fixes were required.

## Sample details

| repo | file | status | notes |
|------|------|--------|-------|
| go | `src/cmd/compile/internal/test/free_test.go` | verified |  |
| go | `src/cmd/internal/obj/s390x/rotate.go` | verified |  |
| go | `src/cmd/link/internal/ld/decodesym.go` | verified |  |
| go | `src/crypto/subtle/dit_test.go` | verified |  |
| go | `src/encoding/gob/decode.go` | verified |  |
| go | `src/go/internal/gccgoimporter/importer.go` | verified |  |
| go | `src/internal/runtime/gc/scan/scan_generic.go` | verified |  |
| go | `src/internal/runtime/syscall/linux/defs_linux_mipsx.go` | verified |  |
| go | `src/internal/sync/hashtriemap_test.go` | verified |  |
| go | `src/iter/pull_test.go` | verified |  |
| go | `src/path/filepath/symlink.go` | verified |  |
| go | `src/runtime/debuglog.go` | verified |  |
| go | `src/runtime/os3_solaris.go` | verified |  |
| go | `src/runtime/timestub.go` | verified |  |
| go | `src/simd/internal/bridge/decls_wasm.go` | verified |  |
| go | `src/structs/doc.go` | verified |  |
| go | `test/fixedbugs/bug020.go` | verified |  |
| go | `test/fixedbugs/bug224.go` | verified |  |
| go | `test/fixedbugs/bug454.go` | verified |  |
| go | `test/fixedbugs/issue15747b.go` | verified |  |
| go | `test/fixedbugs/issue17645.go` | verified |  |
| go | `test/fixedbugs/issue38905.go` | verified |  |
| go | `test/fixedbugs/issue44732.dir/bar/bar.go` | verified |  |
| go | `test/typeparam/issue50121.go` | verified |  |
| grafana | `apps/logsdrilldown/pkg/apis/logsdrilldown/v1beta1/logsdrilldowndefaultcolumns_client_gen.go` | verified |  |
| grafana | `apps/preferences/pkg/apis/manifestdata/preferences_manifest.go` | verified |  |
| grafana | `packages/grafana-alerting/src/grafana/contactPoints/hooks/v0alpha1/useContactPoints.tsx` | verified |  |
| grafana | `packages/grafana-api-clients/src/clients/rtkq/quotas/v0alpha1/index.ts` | verified |  |
| grafana | `packages/grafana-ui/src/components/Layout/utils/styles.ts` | verified |  |
| grafana | `pkg/apimachinery/identity/requester_test.go` | verified |  |
| grafana | `pkg/expr/mathexp/type_series.go` | verified |  |
| grafana | `pkg/infra/metrics/graphitebridge/graphite_test.go` | verified |  |
| grafana | `pkg/registry/apis/iam/serviceaccount/validate_test.go` | verified |  |
| grafana | `pkg/services/accesscontrol/filter_test.go` | verified |  |
| grafana | `pkg/services/publicdashboards/alias.go` | verified |  |
| grafana | `pkg/services/publicdashboards/internal/service/query_test.go` | verified |  |
| grafana | `pkg/storage/unified/resource/eventstore_test.go` | verified |  |
| grafana | `pkg/tsdb/cloudwatch/dimension_keys_test.go` | verified |  |
| grafana | `public/app/features/alerting/unified/components/rule-viewer/activeTab.ts` | verified |  |
| grafana | `public/app/features/alerting/unified/enterprise-components/AI/AIGenTriageButton/addAITriageButton.ts` | verified |  |
| grafana | `public/app/features/dashboard-scene/edit-pane/EditPaneHeader.tsx` | verified |  |
| grafana | `public/app/features/dashboard-scene/v2schema/test-helpers.ts` | verified |  |
| grafana | `public/app/features/explore/Logs/Logs.tsx` | verified |  |
| grafana | `public/app/features/expressions/components/ThresholdSelect.tsx` | verified |  |
| grafana | `public/app/features/library-panels/utils/usePanelSave.ts` | verified |  |
| grafana | `public/app/features/provisioning/components/Dashboards/MoveProvisionedDashboardDrawer.tsx` | verified |  |
| grafana | `public/app/features/transformers/FilterByValueTransformer/ValueMatchers/NoopMatcherEditor.tsx` | verified |  |
| grafana | `public/app/plugins/datasource/azuremonitor/components/ResourcePicker/ResourcePicker.tsx` | verified |  |
| grafana | `public/app/plugins/datasource/loki/querybuilder/parsing.ts` | verified |  |
| grafana | `public/app/plugins/panel/logstable/options/onSortOrderChange.ts` | verified |  |
