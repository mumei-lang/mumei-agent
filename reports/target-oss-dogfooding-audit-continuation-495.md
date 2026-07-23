# Target OSS no-LLM dogfooding audit — continuation 495 (batch 496)

Run: 2026-07-23T06:34:42.963334+00:00

## Summary

- Files audited: 50
- Verified: 50
- Refuted: 0
- Unverifiable: 0

All sampled files passed no-LLM verification; no new tool-side fixes were required.

## Sample details

| repo | file | status | notes |
|------|------|--------|-------|
| go | `src/cmd/link/internal/ld/issue33808_test.go` | verified |  |
| go | `src/cmd/link/internal/ld/ld.go` | verified |  |
| go | `src/crypto/internal/fips140/check/checktest/test.go` | verified |  |
| go | `src/crypto/internal/sysrand/rand_arc4random.go` | verified |  |
| go | `src/crypto/tls/tls_test.go` | verified |  |
| go | `src/html/fuzz_test.go` | verified |  |
| go | `src/internal/goexperiment/exp_regabiargs_on.go` | verified |  |
| go | `src/internal/poll/fd_wasip1.go` | verified |  |
| go | `src/math/big/doc.go` | verified |  |
| go | `src/os/root_windows.go` | verified |  |
| go | `src/runtime/panicnil_test.go` | verified |  |
| go | `src/syscall/zsyscall_freebsd_amd64.go` | verified |  |
| go | `src/syscall/zsysnum_openbsd_386.go` | verified |  |
| go | `src/testing/benchmark.go` | verified |  |
| go | `src/testing/fstest/testfs.go` | verified |  |
| go | `src/testing/iotest/writer.go` | verified |  |
| go | `test/codegen/issue48054.go` | verified |  |
| go | `test/fixedbugs/bug272.go` | verified |  |
| go | `test/fixedbugs/issue15329.go` | verified |  |
| go | `test/fixedbugs/issue31636.go` | verified |  |
| go | `test/fixedbugs/issue45242.go` | verified |  |
| go | `test/fixedbugs/issue7648.go` | verified |  |
| go | `test/fixedbugs/issue7746.go` | verified |  |
| go | `test/fixedbugs/issue8311.go` | verified |  |
| go | `test/fixedbugs/issue9355.dir/a.go` | verified |  |
| go | `test/method3.go` | verified |  |
| go | `test/typeparam/issue48711.go` | verified |  |
| grafana | `apps/dashboard/pkg/apis/dashboard/v2/dashboard_object_gen.go` | verified |  |
| grafana | `apps/iam/pkg/apis/iam/v0alpha1/serviceaccount_listserviceaccounttokens_response_body_types_gen.go` | verified |  |
| grafana | `apps/provisioning/pkg/connection/factory_test.go` | verified |  |
| grafana | `packages/grafana-runtime/src/internal/openFeature/openfeature.gen.ts` | verified |  |
| grafana | `pkg/api/plugin_dashboards_test.go` | verified |  |
| grafana | `pkg/apiserver/registry/generic/key.go` | verified |  |
| grafana | `pkg/infra/nats/connection_test.go` | verified |  |
| grafana | `pkg/plugins/openapi/augment_test.go` | verified |  |
| grafana | `pkg/services/grpcserver/interceptors/tracing.go` | verified |  |
| grafana | `pkg/services/ngalert/metrics/multi_org_alertmanager.go` | verified |  |
| grafana | `pkg/services/provisioning/utils/utils.go` | verified |  |
| grafana | `pkg/storage/unified/migrations/resource_migration_test.go` | verified |  |
| grafana | `pkg/tsdb/loki/framing_test.go` | verified |  |
| grafana | `public/app/core/components/ForgottenPassword/ChangePasswordPage.tsx` | verified |  |
| grafana | `public/app/features/alerting/unified/api/preview.ts` | verified |  |
| grafana | `public/app/features/alerting/unified/components/extensions/QuerylessAppExtensions.tsx` | verified |  |
| grafana | `public/app/features/alerting/unified/components/rule-editor/alert-rule-form/simplifiedRouting/route-settings/MuteTimingFields.tsx` | verified |  |
| grafana | `public/app/features/connections/hooks/useDataSourceTabNav.ts` | verified |  |
| grafana | `public/app/features/provisioning/Wizard/BootstrapStepResourceCounting.tsx` | verified |  |
| grafana | `public/app/features/provisioning/components/Shared/MoveActionAvailableTargetWarning.tsx` | verified |  |
| grafana | `public/app/plugins/panel/canvas/migrations.ts` | verified |  |
| grafana | `public/app/plugins/panel/gauge/migrations.ts` | verified |  |
| grafana | `public/app/plugins/panel/heatmap/fields.ts` | verified |  |
