# Target OSS no-LLM dogfooding audit — continuation 519 (batch 520)

Run: 2026-07-23T07:51:10.381770+00:00

## Summary

- Files audited: 50
- Verified: 50
- Refuted: 0
- Unverifiable: 0

All sampled files passed no-LLM verification; no new tool-side fixes were required.

## Sample details

| repo | file | status | notes |
|------|------|--------|-------|
| go | `src/bytes/bytes_js_wasm_test.go` | verified |  |
| go | `src/cmd/cgo/internal/testshared/shared_test.go` | verified |  |
| go | `src/cmd/compile/internal/arm64/galign.go` | verified |  |
| go | `src/cmd/compile/internal/slice/slice.go` | verified |  |
| go | `src/cmd/compile/internal/types/algkind_string.go` | verified |  |
| go | `src/cmd/go/proxy_test.go` | verified |  |
| go | `src/cmd/internal/robustio/robustio.go` | verified |  |
| go | `src/cmd/trace/pprof_test.go` | verified |  |
| go | `src/crypto/internal/boring/bcache/cache_test.go` | verified |  |
| go | `src/crypto/mldsa/mldsa.go` | verified |  |
| go | `src/crypto/x509/platform_test.go` | verified |  |
| go | `src/encoding/binary/varint_test.go` | verified |  |
| go | `src/encoding/json/v2/arshal_embedded.go` | verified |  |
| go | `src/internal/testenv/testenv.go` | verified |  |
| go | `src/math/big/example_rat_test.go` | verified |  |
| go | `src/net/error_windows.go` | verified |  |
| go | `src/runtime/cpuflags_arm64.go` | verified |  |
| go | `src/strings/compare_test.go` | verified |  |
| go | `src/testing/sub_test.go` | verified |  |
| go | `src/testing/testing_test.go` | verified |  |
| go | `test/fixedbugs/bug248.dir/bug3.go` | verified |  |
| go | `test/fixedbugs/issue31782.go` | verified |  |
| go | `test/fixedbugs/issue58339.dir/b.go` | verified |  |
| go | `test/fixedbugs/issue79960.go` | verified |  |
| go | `test/indirect1.go` | verified |  |
| go | `test/syntax/chan.go` | verified |  |
| go | `test/typeparam/issue51423.dir/a.go` | verified |  |
| grafana | `apps/collections/pkg/apis/collections/v1alpha1/stars_schema_gen.go` | verified |  |
| grafana | `apps/dashboard/pkg/apis/dashboard/v2/dashboard_schema_gen.go` | verified |  |
| grafana | `apps/dashboard/pkg/apis/dashboard/v2beta1/notebook_spec_gen.go` | verified |  |
| grafana | `apps/provisioning/pkg/repository/github/webhook_builder_mock.go` | verified |  |
| grafana | `apps/provisioning/pkg/repository/secure_test.go` | verified |  |
| grafana | `packages/grafana-ui/src/components/ElementSelectionContext/ElementSelectionContext.tsx` | verified |  |
| grafana | `packages/grafana-ui/src/components/Forms/InlineFieldRow.tsx` | verified |  |
| grafana | `pkg/registry/apis/folders/sub_parents.go` | verified |  |
| grafana | `pkg/registry/apis/provisioning/dependencies.go` | verified |  |
| grafana | `pkg/services/pluginsintegration/clientmiddleware/oauthtoken_middleware.go` | verified |  |
| grafana | `pkg/tests/apis/provisioning/health_test.go` | verified |  |
| grafana | `pkg/tsdb/cloudwatch/cloudwatch_integration_test.go` | verified |  |
| grafana | `pkg/tsdb/graphite/null_float_test.go` | verified |  |
| grafana | `pkg/tsdb/loki/frame.go` | verified |  |
| grafana | `public/app/features/admin/ldap/LdapUserGroups.tsx` | verified |  |
| grafana | `public/app/features/alerting/unified/components/DynamicTable.tsx` | verified |  |
| grafana | `public/app/features/alerting/unified/components/notification-policies/PolicyUpdateErrorAlert.tsx` | verified |  |
| grafana | `public/app/features/alerting/unified/hooks/abilities/rules/promRuleAbilities.ts` | verified |  |
| grafana | `public/app/features/alerting/unified/triage/constants.ts` | verified |  |
| grafana | `public/app/features/alerting/unified/triage/scene/filters/LabelsContent.tsx` | verified |  |
| grafana | `public/app/features/dashboard-scene/settings/variables/editors/IntervalVariableEditor.tsx` | verified |  |
| grafana | `public/app/features/provisioning/components/utils/orphanedResource.ts` | verified |  |
| grafana | `public/app/features/transformers/calculateHeatmap/editor/helper.ts` | verified |  |
