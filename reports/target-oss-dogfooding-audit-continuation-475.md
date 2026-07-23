# Target OSS no-LLM dogfooding audit — continuation 475 (batch 476)

Run: 2026-07-23T04:52:43.571428+00:00

## Summary

- Files audited: 50
- Verified: 50
- Refuted: 0
- Unverifiable: 0

All sampled files passed no-LLM verification; no new tool-side fixes were required.

## Sample details

| repo | file | status | notes |
|------|------|--------|-------|
| go | `src/cmd/link/internal/ld/outbuf_bsd.go` | verified |  |
| go | `src/crypto/ed25519/ed25519_test.go` | verified |  |
| go | `src/crypto/sha512/sha512.go` | verified |  |
| go | `src/encoding/gob/example_interface_test.go` | verified |  |
| go | `src/internal/lazyregexp/lazyre.go` | verified |  |
| go | `src/internal/trace/raw/event.go` | verified |  |
| go | `src/internal/trace/tracev1_test.go` | verified |  |
| go | `src/mime/multipart/example_test.go` | verified |  |
| go | `src/net/http/httptrace/trace.go` | verified |  |
| go | `src/net/lookup_windows_test.go` | verified |  |
| go | `src/runtime/signal_linux_arm.go` | verified |  |
| go | `src/simd/archsimd/_gen/unify/yaml_test.go` | verified |  |
| go | `src/syscall/dll_windows.go` | verified |  |
| go | `src/syscall/syscall_linux_mips64x.go` | verified |  |
| go | `src/testing/flag_test.go` | verified |  |
| go | `src/testing/quick/quick_test.go` | verified |  |
| go | `test/cmplx.go` | verified |  |
| go | `test/fixedbugs/bug479.go` | verified |  |
| go | `test/fixedbugs/issue35652.go` | verified |  |
| go | `test/fixedbugs/issue68526.dir/main.go` | verified |  |
| go | `test/printbig.go` | verified |  |
| go | `test/typeparam/genembed2.go` | verified |  |
| grafana | `apps/annotation/plugin/src/generated/annotation/v0alpha1/types.metadata.gen.ts` | verified |  |
| grafana | `packages/grafana-data/src/types/displayValue.ts` | verified |  |
| grafana | `packages/grafana-ui/src/components/ConfirmButton/ConfirmButton.tsx` | verified |  |
| grafana | `pkg/infra/httpclient/httpclientprovider/grafana_request_id_header_middleware.go` | verified |  |
| grafana | `pkg/infra/network/address_test.go` | verified |  |
| grafana | `pkg/plugins/manager/loader/angular/angularinspector/fakes_test.go` | verified |  |
| grafana | `pkg/plugins/manager/pipeline/validation/steps.go` | verified |  |
| grafana | `pkg/services/authz/zanzana/server/server_query_folder_test.go` | verified |  |
| grafana | `pkg/services/authz/zanzana/tuple_helpers_test.go` | verified |  |
| grafana | `pkg/services/libraryelements/libraryelements_permissions_test.go` | verified |  |
| grafana | `pkg/services/sqlstore/migrations/ualert/state_last_result_mig.go` | verified |  |
| grafana | `pkg/services/ssosettings/strategies/mtsettings_strategy.go` | verified |  |
| grafana | `pkg/setting/setting_annotations.go` | verified |  |
| grafana | `pkg/storage/unified/resource/kv/datastoretypes_test.go` | verified |  |
| grafana | `pkg/tests/apis/provisioning/folder_authorization_test.go` | verified |  |
| grafana | `pkg/tsdb/cloudwatch/clients/metrics_test.go` | verified |  |
| grafana | `pkg/tsdb/cloudwatch/models/gmd_errors.go` | verified |  |
| grafana | `public/app/core/copy/appNotification.ts` | verified |  |
| grafana | `public/app/features/admin/AdminOrgsTable.tsx` | verified |  |
| grafana | `public/app/features/dashboard-scene/scene/new-toolbar/BreadcrumbActions.tsx` | verified |  |
| grafana | `public/app/features/explore/TraceView/components/TracePageHeader/SearchBar/NextPrevResult.tsx` | verified |  |
| grafana | `public/app/features/provisioning/GettingStarted/SetupStep.tsx` | verified |  |
| grafana | `public/app/features/serviceaccounts/ServiceAccountTable.tsx` | verified |  |
| grafana | `public/app/features/transformers/partitionByValues/partitionByValues.ts` | verified |  |
| grafana | `public/app/plugins/datasource/azuremonitor/components/LogsQueryBuilder/AggregateItem.tsx` | verified |  |
| grafana | `public/app/plugins/datasource/azuremonitor/utils/useLastError.ts` | verified |  |
| grafana | `public/app/plugins/datasource/cloudwatch/mocks/cloudwatch-logs-test-data/sortQuery.ts` | verified |  |
| grafana | `public/app/plugins/panel/stat/presets.ts` | verified |  |
