# Target OSS no-LLM dogfooding audit — continuation 538 (batch 539)

Run: 2026-07-23T09:26:40.271331+00:00

## Summary

- Files audited: 50
- Verified: 50
- Refuted: 0
- Unverifiable: 0

All sampled files passed no-LLM verification; no new tool-side fixes were required.

## Sample details

| repo | file | status | notes |
|------|------|--------|-------|
| go | `src/cmd/compile/internal/ir/name.go` | verified |  |
| go | `src/cmd/compile/internal/ssa/_gen/simdAMD64ops.go` | verified |  |
| go | `src/cmd/compile/internal/ssa/rewriteMIPS.go` | verified |  |
| go | `src/cmd/compile/internal/test/zerorange_test.go` | verified |  |
| go | `src/cmd/link/internal/mips64/l.go` | verified |  |
| go | `src/crypto/internal/fips140/pbkdf2/cast.go` | verified |  |
| go | `src/encoding/json/fold_test.go` | verified |  |
| go | `src/html/template/example_test.go` | verified |  |
| go | `src/internal/goexperiment/exp_heapminimum512kib_off.go` | verified |  |
| go | `src/log/slog/internal/benchmarks/benchmarks.go` | verified |  |
| go | `src/math/big/float.go` | verified |  |
| go | `src/math/cmplx/pow.go` | verified |  |
| go | `src/net/http/responsecontroller.go` | verified |  |
| go | `src/os/error_test.go` | verified |  |
| go | `src/os/stat_windows.go` | verified |  |
| go | `src/os/user/user_test.go` | verified |  |
| go | `src/runtime/cgo/setenv.go` | verified |  |
| go | `src/runtime/debug/stubs.go` | verified |  |
| go | `src/simd/archsimd/types_wasm.go` | verified |  |
| go | `src/sync/oncefunc_test.go` | verified |  |
| go | `src/syscall/zsysnum_linux_arm.go` | verified |  |
| go | `src/testing/testing_windows.go` | verified |  |
| go | `test/abi/convF_criteria.go` | verified |  |
| go | `test/fixedbugs/issue4448.go` | verified |  |
| go | `test/fixedbugs/issue45913.go` | verified |  |
| go | `test/fixedbugs/issue50190.go` | verified |  |
| go | `test/fixedbugs/issue52590.dir/a.go` | verified |  |
| go | `test/fixedbugs/issue80188.go` | verified |  |
| grafana | `apps/alerting/notifications/pkg/apis/alertingnotifications/v1beta1/constants.go` | verified |  |
| grafana | `apps/example/plugin/src/generated/example/v1alpha1/types.routes.gen.ts` | verified |  |
| grafana | `apps/iam/pkg/apis/iam/v0alpha1/globalrole_object_gen.go` | verified |  |
| grafana | `apps/provisioning/pkg/generated/applyconfiguration/provisioning/v0alpha1/exportjoboptions.go` | verified |  |
| grafana | `packages/grafana-ui/src/components/InfoTooltip/InfoTooltip.tsx` | verified |  |
| grafana | `packages/grafana-ui/src/graveyard/GraphNG/nullToValue.ts` | verified |  |
| grafana | `pkg/api/routing/route_register_test.go` | verified |  |
| grafana | `pkg/apiserver/auditing/logger.go` | verified |  |
| grafana | `pkg/registry/apis/iam/team/retryable_test.go` | verified |  |
| grafana | `pkg/services/apiserver/aggregatorrunner/noopaggregator.go` | verified |  |
| grafana | `pkg/services/authz/rbac/mapper.go` | verified |  |
| grafana | `pkg/services/cleanup/cleanup_test.go` | verified |  |
| grafana | `pkg/services/featuremgmt/token-exchange.go` | verified |  |
| grafana | `pkg/services/ngalert/api/api_alertmanager.go` | verified |  |
| grafana | `pkg/storage/unified/resourcewatch/subject.go` | verified |  |
| grafana | `pkg/tsdb/cloudwatch/cloudwatch.go` | verified |  |
| grafana | `public/app/core/components/SplitPaneWrapper/SplitPaneWrapper.tsx` | verified |  |
| grafana | `public/app/features/alerting/unified/components/notification-policies/ContactPointSelector.tsx` | verified |  |
| grafana | `public/app/features/alerting/unified/search/rulesSearchParser.ts` | verified |  |
| grafana | `public/app/features/dashboard-scene/panel-edit/QueryEditorBanner.tsx` | verified |  |
| grafana | `public/app/features/dashboard-scene/settings/variables/editors/QueryVariableEditor/getQueryVariableOptions.tsx` | verified |  |
| grafana | `public/app/features/explore/TraceView/components/utils/date.tsx` | verified |  |
