# Target OSS no-LLM dogfooding audit — continuation 453 (batch 454)

Run: 2026-07-23T03:29:50.865043+00:00

## Summary

- Files audited: 50
- Verified: 50
- Refuted: 0
- Unverifiable: 0

All sampled files passed no-LLM verification; no new tool-side fixes were required.

## Sample details

| repo | file | status | notes |
|------|------|--------|-------|
| go | `src/cmd/internal/obj/arm/list5.go` | verified |  |
| go | `src/encoding/gob/enc_helpers.go` | verified |  |
| go | `src/internal/gate/gate_test.go` | verified |  |
| go | `src/internal/goexperiment/exp_simd_on.go` | verified |  |
| go | `src/internal/runtime/atomic/stubs.go` | verified |  |
| go | `src/internal/unsafeheader/unsafeheader.go` | verified |  |
| go | `src/io/multi_test.go` | verified |  |
| go | `src/net/http/internal/http2/flow_test.go` | verified |  |
| go | `src/net/rpc/jsonrpc/server.go` | verified |  |
| go | `src/runtime/runtime_clearenv.go` | verified |  |
| go | `src/syscall/zerrors_openbsd_386.go` | verified |  |
| go | `src/testing/testing_other.go` | verified |  |
| go | `src/time/tick_test.go` | verified |  |
| go | `test/fixedbugs/bug277.go` | verified |  |
| go | `test/fixedbugs/bug483.go` | verified |  |
| go | `test/fixedbugs/issue14591.go` | verified |  |
| go | `test/fixedbugs/issue18089.go` | verified |  |
| go | `test/fixedbugs/issue4510.dir/f1.go` | verified |  |
| go | `test/fixedbugs/issue54911.go` | verified |  |
| go | `test/nilptr5_wasm.go` | verified |  |
| go | `test/typeparam/dedup.dir/b.go` | verified |  |
| grafana | `apps/plugins/pkg/app/plugin_storage.go` | verified |  |
| grafana | `apps/provisioning/pkg/generated/applyconfiguration/provisioning/v0alpha1/historicjob.go` | verified |  |
| grafana | `e2e-playwright/utils/scope-helpers.ts` | verified |  |
| grafana | `packages/grafana-ui/src/components/DataSourceSettings/BasicAuthSettings.tsx` | verified |  |
| grafana | `packages/grafana-ui/src/components/Table/CellActions.tsx` | verified |  |
| grafana | `pkg/apimachinery/utils/tableConverter.go` | verified |  |
| grafana | `pkg/plugins/pluginerrs/errors.go` | verified |  |
| grafana | `pkg/registry/apis/dashboard/legacy/token_test.go` | verified |  |
| grafana | `pkg/registry/apis/iam/teambinding/legacy_search.go` | verified |  |
| grafana | `pkg/services/accesscontrol/migrator/migrator.go` | verified |  |
| grafana | `pkg/services/apiserver/auth/authorizer/impersonation_test.go` | verified |  |
| grafana | `pkg/services/dashboards/dashboard.go` | verified |  |
| grafana | `pkg/services/ngalert/image/cache_mock.go` | verified |  |
| grafana | `pkg/services/queryhistory/queryhistory_create_test.go` | verified |  |
| grafana | `pkg/storage/unified/resource/list_with_field_selectors_test.go` | verified |  |
| grafana | `pkg/storage/unified/resource/notifier_test.go` | verified |  |
| grafana | `pkg/storage/unified/resourcepb/search.pb.go` | verified |  |
| grafana | `pkg/tests/apis/features/features_test.go` | verified |  |
| grafana | `public/app/core/components/PageNotFound/PageNotFound.tsx` | verified |  |
| grafana | `public/app/core/components/QueryOperationRow/OperationRowHelp.tsx` | verified |  |
| grafana | `public/app/features/alerting/unified/group-details/GroupEditPage.tsx` | verified |  |
| grafana | `public/app/features/alerting/unified/types/knownProvenance.ts` | verified |  |
| grafana | `public/app/features/dashboard-scene/panel-edit/PanelEditNext/QueryEditor/hooks/useTransformationInputData.ts` | verified |  |
| grafana | `public/app/features/migrate-to-cloud/fixtures/others.ts` | verified |  |
| grafana | `public/app/features/panel/presets/getPresets.ts` | verified |  |
| grafana | `public/app/features/provisioning/utils/commitMessage.ts` | verified |  |
| grafana | `public/app/plugins/datasource/graphite/utils.ts` | verified |  |
| grafana | `public/app/plugins/datasource/jaeger/helpers/createFetchResponse.ts` | verified |  |
| grafana | `public/test/helpers/alertingRuleEditor.tsx` | verified |  |
