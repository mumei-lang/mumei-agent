# Target OSS no-LLM dogfooding audit — continuation 540 (batch 541)

Run: 2026-07-23T09:43:26.767321+00:00

## Summary

- Files audited: 50
- Verified: 50
- Refuted: 0
- Unverifiable: 0

All sampled files passed no-LLM verification; no new tool-side fixes were required.

## Sample details

| repo | file | status | notes |
|------|------|--------|-------|
| go | `src/cmd/compile/internal/noder/posmap.go` | verified |  |
| go | `src/cmd/compile/internal/ssa/tighten.go` | verified |  |
| go | `src/cmd/gofmt/doc.go` | verified |  |
| go | `src/crypto/tls/quic.go` | verified |  |
| go | `src/encoding/json/internal/jsonwire/encode_test.go` | verified |  |
| go | `src/go/types/expr.go` | verified |  |
| go | `src/internal/fuzz/queue_test.go` | verified |  |
| go | `src/internal/goexperiment/exp_mapsplitgroup_on.go` | verified |  |
| go | `src/internal/strconv/atob_test.go` | verified |  |
| go | `src/internal/syscall/unix/net_js.go` | verified |  |
| go | `src/internal/syscall/windows/net_windows.go` | verified |  |
| go | `src/math/rand/rng.go` | verified |  |
| go | `src/runtime/malloc_stubs_test.go` | verified |  |
| go | `src/runtime/signal_freebsd.go` | verified |  |
| go | `src/runtime/symtab_test.go` | verified |  |
| go | `src/runtime/trace/flightrecorder_test.go` | verified |  |
| go | `src/simd/archsimd/_gen/wasmgen/main.go` | verified |  |
| go | `test/fixedbugs/bug428.go` | verified |  |
| go | `test/fixedbugs/bug449.go` | verified |  |
| go | `test/fixedbugs/issue10066.go` | verified |  |
| go | `test/fixedbugs/issue21256.go` | verified |  |
| go | `test/fixedbugs/issue6703m.go` | verified |  |
| go | `test/fixedbugs/issue6977.go` | verified |  |
| go | `test/fixedbugs/issue72860.go` | verified |  |
| go | `test/fixedbugs/issue7590.go` | verified |  |
| go | `test/inline_endian.go` | verified |  |
| go | `test/interface/noeq.go` | verified |  |
| go | `test/ken/divmod.go` | verified |  |
| go | `test/typeparam/issue49027.dir/main.go` | verified |  |
| grafana | `e2e-playwright/dashboard-new-layouts/page-objects/sidebar/ContentOutline.ts` | verified |  |
| grafana | `packages/grafana-data/src/dataframe/frameComparisons.ts` | verified |  |
| grafana | `packages/grafana-test-utils/src/matchers/index.ts` | verified |  |
| grafana | `pkg/apimachinery/errutil/errors.go` | verified |  |
| grafana | `pkg/components/loki/lokigrpc/client.go` | verified |  |
| grafana | `pkg/infra/httpclient/httpclientprovider/testing.go` | verified |  |
| grafana | `pkg/services/pluginsintegration/clientmiddleware/user_header_middleware_test.go` | verified |  |
| grafana | `pkg/storage/unified/resource/grpc_interceptor.go` | verified |  |
| grafana | `pkg/tests/apis/provisioning/secrets_test.go` | verified |  |
| grafana | `pkg/tsdb/jaeger/utils/client_utils.go` | verified |  |
| grafana | `public/app/features/alerting/unified/components/receivers/form/fields/SubformArrayField.tsx` | verified |  |
| grafana | `public/app/features/alerting/unified/components/rule-editor/DashboardAnnotationField.tsx` | verified |  |
| grafana | `public/app/features/annotations/api.ts` | verified |  |
| grafana | `public/app/features/commandPalette/api/deepSearch.ts` | verified |  |
| grafana | `public/app/features/dashboard-scene/panel-edit/PanelEditNext/QueryEditor/hooks/useSelectedQueryDatasource.ts` | verified |  |
| grafana | `public/app/features/dashboard-scene/settings/variables/VariableTypeSelectionPane.tsx` | verified |  |
| grafana | `public/app/features/dashboard-scene/settings/variables/components/VariableTextAreaField.tsx` | verified |  |
| grafana | `public/app/features/dashboard-scene/solo/ViewPanelSidePane.tsx` | verified |  |
| grafana | `public/app/features/provisioning/components/utils/timestamp.ts` | verified |  |
| grafana | `public/app/plugins/datasource/influxdb/components/editor/query/influxql/visual/InputSection.tsx` | verified |  |
| grafana | `public/app/plugins/panel/nodeGraph/utils.ts` | verified |  |
