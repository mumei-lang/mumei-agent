# Target OSS no-LLM dogfooding audit — continuation 290 (batch 291)

Run: 2026-07-22T17:27:27.615406+00:00

## Summary

- Files audited: 50
- Verified: 50
- Refuted: 0
- Unverifiable: 0

All sampled files passed no-LLM verification; no new tool-side fixes were required.

## Sample details

| repo | file | status | notes |
|------|------|--------|-------|
| go | `src/cmd/compile/internal/ssa/rewrite_test.go` | verified |  |
| go | `src/cmd/compile/internal/test/shift_test.go` | verified |  |
| go | `src/cmd/link/internal/ld/pcln.go` | verified |  |
| go | `src/internal/runtime/cgroup/cgroup_test.go` | verified |  |
| go | `src/internal/trace/traceviewer/format/format.go` | verified |  |
| go | `src/io/io.go` | verified |  |
| go | `src/log/slog/json_handler_test.go` | verified |  |
| go | `src/log/slog/logger.go` | verified |  |
| go | `src/net/rpc/client.go` | verified |  |
| go | `src/runtime/_mkmalloc/constants.go` | verified |  |
| go | `src/runtime/trace/subscribe_test.go` | verified |  |
| go | `test/codegen/mathbits.go` | verified |  |
| go | `test/fixedbugs/bug170.go` | verified |  |
| go | `test/fixedbugs/issue23546.go` | verified |  |
| go | `test/fixedbugs/issue47068.dir/b.go` | verified |  |
| go | `test/fixedbugs/issue79236b.go` | verified |  |
| go | `test/typeparam/factimp.dir/a.go` | verified |  |
| grafana | `apps/secret/consolidate/v1beta1/consolidate_grpc.pb.go` | verified |  |
| grafana | `e2e-playwright/utils/RequestsRecorder.ts` | verified |  |
| grafana | `packages/grafana-ui/src/components/DateTimePickers/TimeRangePicker/CalendarFooter.tsx` | verified |  |
| grafana | `pkg/components/dashdiffs/compare.go` | verified |  |
| grafana | `pkg/middleware/csp_test.go` | verified |  |
| grafana | `pkg/plugins/manager/loader/loader_test.go` | verified |  |
| grafana | `pkg/registry/apis/collections/admission.go` | verified |  |
| grafana | `pkg/registry/apis/provisioning/openapi_version.go` | verified |  |
| grafana | `pkg/services/authz/proto/v1/extention.pb.go` | verified |  |
| grafana | `pkg/services/dashboards/dashboardaccess/dashboard_access_test.go` | verified |  |
| grafana | `pkg/services/grpcserver/interceptors/auth_test.go` | verified |  |
| grafana | `pkg/services/ldap/service/ldap.go` | verified |  |
| grafana | `pkg/services/pluginsintegration/pluginstore/fake.go` | verified |  |
| grafana | `pkg/services/serviceaccounts/tests/common.go` | verified |  |
| grafana | `pkg/services/sqlstore/migrations/usermig/test/user_lowercase_login_and_email_test.go` | verified |  |
| grafana | `public/app/core/components/OptionsUI/strings.tsx` | verified |  |
| grafana | `public/app/core/components/OwnerReferences/ManageOwnerReferences.tsx` | verified |  |
| grafana | `public/app/features/admin/UserOrgs.tsx` | verified |  |
| grafana | `public/app/features/alerting/unified/__mocks__/useRouteGroupsMatcher.ts` | verified |  |
| grafana | `public/app/features/alerting/unified/rule-list/hooks/prometheusGroupsGenerator.ts` | verified |  |
| grafana | `public/app/plugins/datasource/cloudwatch/language/dynamic-labels/language.ts` | verified |  |
| grafana | `public/app/plugins/datasource/cloudwatch/mocks/MetricsQueryRunner.ts` | verified |  |
| prysm | `beacon-chain/blockchain/setup_test.go` | verified |  |
| prysm | `beacon-chain/core/fulu/transition.go` | verified |  |
| prysm | `beacon-chain/db/kv/blocks_test.go` | verified |  |
| prysm | `beacon-chain/p2p/encoder/ssz_test.go` | verified |  |
| prysm | `beacon-chain/rpc/core/validator.go` | verified |  |
| prysm | `beacon-chain/sync/rpc_test.go` | verified |  |
| prysm | `beacon-chain/verification/initializer.go` | verified |  |
| prysm | `proto/prysm/v1alpha1/validator-client/keymanager.pb.go` | verified |  |
| prysm | `testing/spectest/mainnet/phase0__epoch_processing__justification_and_finalization_test.go` | verified |  |
| prysm | `testing/spectest/minimal/gloas__epoch_processing__process_builder_pending_payments_test.go` | verified |  |
| prysm | `validator/client/iface/validator.go` | verified |  |
