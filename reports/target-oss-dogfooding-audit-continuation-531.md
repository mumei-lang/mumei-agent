# Target OSS no-LLM dogfooding audit — continuation 531 (batch 532)

Run: 2026-07-23T08:56:54.811297+00:00

## Summary

- Files audited: 50
- Verified: 50
- Refuted: 0
- Unverifiable: 0

All sampled files passed no-LLM verification; no new tool-side fixes were required.

## Sample details

| repo | file | status | notes |
|------|------|--------|-------|
| go | `src/cmd/cgo/internal/testerrors/ptr_test.go` | verified |  |
| go | `src/cmd/compile/internal/ssa/sparsetree.go` | verified |  |
| go | `src/cmd/cover/cover_test.go` | verified |  |
| go | `src/cmd/go/internal/cache/hash_test.go` | verified |  |
| go | `src/cmd/go/internal/gover/local.go` | verified |  |
| go | `src/cmd/link/internal/riscv64/l.go` | verified |  |
| go | `src/crypto/des/block.go` | verified |  |
| go | `src/crypto/internal/fips140/indicator.go` | verified |  |
| go | `src/crypto/tls/cache.go` | verified |  |
| go | `src/internal/goarch/goarch_riscv64.go` | verified |  |
| go | `src/internal/sync/runtime.go` | verified |  |
| go | `src/net/http/clientconn_test.go` | verified |  |
| go | `src/net/tcpsockopt_solaris.go` | verified |  |
| go | `src/reflect/abi.go` | verified |  |
| go | `src/runtime/stubs_arm.go` | verified |  |
| go | `src/runtime/vdso_freebsd_arm.go` | verified |  |
| go | `src/syscall/zsysnum_linux_mips64le.go` | verified |  |
| go | `test/codegen/compare_and_branch.go` | verified |  |
| go | `test/copy.go` | verified |  |
| go | `test/fixedbugs/bug388.go` | verified |  |
| go | `test/fixedbugs/issue14321.go` | verified |  |
| go | `test/fixedbugs/issue15609.dir/call_decl.go` | verified |  |
| go | `test/fixedbugs/issue73748b.go` | verified |  |
| go | `test/fixedbugs/issue8047.go` | verified |  |
| go | `test/recover3.go` | verified |  |
| go | `test/typeparam/issue50561.go` | verified |  |
| grafana | `apps/iam/pkg/apis/iam/v0alpha1/externalgroupmapping_object_gen.go` | verified |  |
| grafana | `apps/iam/pkg/apis/iam/v0alpha1/serviceaccount_deleteserviceaccounttoken_response_object_types_gen.go` | verified |  |
| grafana | `apps/provisioning/pkg/controller/status.go` | verified |  |
| grafana | `packages/grafana-data/src/transformations/transformers/noop.ts` | verified |  |
| grafana | `pkg/expr/mathexp/union_test.go` | verified |  |
| grafana | `pkg/registry/apis/provisioning/resources/parser_factory_mock.go` | verified |  |
| grafana | `pkg/registry/apps/annotation/register_test.go` | verified |  |
| grafana | `pkg/services/authz/zanzana/errors.go` | verified |  |
| grafana | `pkg/services/authz/zanzana/server/server_mutate_roles.go` | verified |  |
| grafana | `pkg/services/ngalert/store/transactions.go` | verified |  |
| grafana | `pkg/services/notifications/smtp_test.go` | verified |  |
| grafana | `pkg/tests/apis/provisioning/foldermetadata/full/helper_test.go` | verified |  |
| grafana | `pkg/tsdb/influxdb/models/query_test.go` | verified |  |
| grafana | `pkg/util/debouncer/debouncer.go` | verified |  |
| grafana | `pkg/util/tls.go` | verified |  |
| grafana | `public/app/core/history/RichHistoryIndexedDBStorage.ts` | verified |  |
| grafana | `public/app/core/internationalization/dates.ts` | verified |  |
| grafana | `public/app/features/alerting/unified/components/notification-policies/useNotificationPolicyRoute.ts` | verified |  |
| grafana | `public/app/features/dashboard-scene/conditional-rendering/conditions/ConditionalRenderingTimeRangeSize.tsx` | verified |  |
| grafana | `public/app/features/dashboard-scene/scene/layout-tabs/TabItem.tsx` | verified |  |
| grafana | `public/app/features/dimensions/types.ts` | verified |  |
| grafana | `public/app/features/gops/configuration-tracker/components/Essentials.tsx` | verified |  |
| grafana | `public/app/plugins/datasource/influxdb/components/editor/variable/VariableQueryEditor.tsx` | verified |  |
| grafana | `public/app/plugins/panel/xychart/module.tsx` | verified |  |
