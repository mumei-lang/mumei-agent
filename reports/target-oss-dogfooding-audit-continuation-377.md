# Target OSS no-LLM dogfooding audit — continuation 377 (batch 378)

Run: 2026-07-22T22:47:54.591379+00:00

## Summary

- Files audited: 50
- Verified: 50
- Refuted: 0
- Unverifiable: 0

All sampled files passed no-LLM verification; no new tool-side fixes were required.

## Sample details

| repo | file | status | notes |
|------|------|--------|-------|
| go | `src/cmd/cgo/internal/test/issue41761.go` | verified |  |
| go | `src/cmd/compile/internal/inline/inlheur/cspropbits_string.go` | verified |  |
| go | `src/cmd/compile/internal/inline/inlheur/resultpropbits_string.go` | verified |  |
| go | `src/cmd/compile/internal/ssa/writebarrier_test.go` | verified |  |
| go | `src/cmd/covdata/covdata.go` | verified |  |
| go | `src/cmd/go/internal/work/security.go` | verified |  |
| go | `src/crypto/internal/fips140/edwards25519/scalarmult.go` | verified |  |
| go | `src/crypto/internal/fips140/sha3/keccakf.go` | verified |  |
| go | `src/internal/goexperiment/exp_cgocheck2_on.go` | verified |  |
| go | `src/internal/synctest/synctest.go` | verified |  |
| go | `src/net/url/url.go` | verified |  |
| go | `src/os/path_test.go` | verified |  |
| go | `src/runtime/cgo/freebsd.go` | verified |  |
| go | `src/runtime/os_wasm.go` | verified |  |
| go | `src/runtime/tracebuf.go` | verified |  |
| go | `test/fixedbugs/bug253.go` | verified |  |
| go | `test/fixedbugs/bug450.go` | verified |  |
| go | `test/fixedbugs/bug472.dir/p2.go` | verified |  |
| go | `test/fixedbugs/issue19743.go` | verified |  |
| go | `test/fixedbugs/issue62515.go` | verified |  |
| go | `test/fixedbugs/issue73916.go` | verified |  |
| go | `test/fixedbugs/issue7863.go` | verified |  |
| go | `test/typeparam/mdempsky/16.go` | verified |  |
| grafana | `apps/dashboard/pkg/migration/conversion/v0alpha1_to_v2.go` | verified |  |
| grafana | `apps/dashvalidator/pkg/validator/dashboard_extraction_test.go` | verified |  |
| grafana | `apps/folder/pkg/apis/folder/v1beta1/defaults.go` | verified |  |
| grafana | `apps/provisioning/pkg/generated/clientset/versioned/typed/provisioning/v0alpha1/fake/fake_connection.go` | verified |  |
| grafana | `packages/grafana-sql/src/components/visual-query-builder/SQLWhereRow.tsx` | verified |  |
| grafana | `packages/grafana-ui/src/components/Select/ValueContainer.tsx` | verified |  |
| grafana | `packages/grafana-ui/src/slate-plugins/runner.ts` | verified |  |
| grafana | `packages/grafana-ui/src/utils/validate.ts` | verified |  |
| grafana | `pkg/components/loki/logproto/logproto.pb.go` | verified |  |
| grafana | `pkg/services/notifications/email.go` | verified |  |
| grafana | `pkg/services/pluginsintegration/keystore/keystore.go` | verified |  |
| grafana | `pkg/services/pluginsintegration/plugincontext/plugincontext.go` | verified |  |
| grafana | `pkg/services/ssosettings/ssosettingsimpl/usage_stats_test.go` | verified |  |
| grafana | `pkg/tests/apis/iam/teambinding/teambinding_test.go` | verified |  |
| grafana | `pkg/tests/apis/provisioning/jobs/job_validation_configured_resources_test.go` | verified |  |
| grafana | `pkg/tsdb/azuremonitor/loganalytics/utils_test.go` | verified |  |
| grafana | `public/app/core/components/RolePicker/hooks.ts` | verified |  |
| grafana | `public/app/features/alerting/unified/insights/mimir/rules/InstancesByState.tsx` | verified |  |
| grafana | `public/app/features/dashboard-scene/mutation-api/commands/listVariables.ts` | verified |  |
| grafana | `public/app/features/datasources/constants.ts` | verified |  |
| grafana | `public/app/features/logs/components/fieldSelector/fieldSelectorUtils.ts` | verified |  |
| grafana | `public/app/features/logs/components/panel/LogLineDetailsFields.tsx` | verified |  |
| grafana | `public/app/features/panel/state/actions.ts` | verified |  |
| grafana | `public/app/features/provisioning/components/defaults.ts` | verified |  |
| grafana | `public/app/features/variables/inspect/VariablesUnknownButton.tsx` | verified |  |
| grafana | `public/app/plugins/datasource/influxdb/influx_series.ts` | verified |  |
| grafana | `public/app/plugins/panel/canvas/editor/inline/InlineEditBody.tsx` | verified |  |
