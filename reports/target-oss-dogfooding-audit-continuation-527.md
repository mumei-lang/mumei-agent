# Target OSS no-LLM dogfooding audit — continuation 527 (batch 528)

Run: 2026-07-23T08:22:28.299333+00:00

## Summary

- Files audited: 50
- Verified: 50
- Refuted: 0
- Unverifiable: 0

All sampled files passed no-LLM verification; no new tool-side fixes were required.

## Sample details

| repo | file | status | notes |
|------|------|--------|-------|
| go | `src/cmd/cgo/internal/test/buildid_linux.go` | verified |  |
| go | `src/cmd/cgo/internal/test/issue4029.go` | verified |  |
| go | `src/cmd/compile/internal/amd64/galign.go` | verified |  |
| go | `src/internal/abi/abi_riscv64.go` | verified |  |
| go | `src/internal/fmtsort/export_test.go` | verified |  |
| go | `src/internal/runtime/atomic/atomic_arm64.go` | verified |  |
| go | `src/mime/type_freebsd.go` | verified |  |
| go | `src/net/http/transfer.go` | verified |  |
| go | `src/os/dir_windows.go` | verified |  |
| go | `src/os/example_test.go` | verified |  |
| go | `src/runtime/race.go` | verified |  |
| go | `src/runtime/traceback_test.go` | verified |  |
| go | `src/simd/archsimd/_gen/simdgen/pprint.go` | verified |  |
| go | `src/testing/iotest/logger_test.go` | verified |  |
| go | `test/const4.go` | verified |  |
| go | `test/fixedbugs/bug393.go` | verified |  |
| go | `test/fixedbugs/bug453.go` | verified |  |
| go | `test/fixedbugs/bug477.go` | verified |  |
| go | `test/fixedbugs/issue12677.go` | verified |  |
| go | `test/fixedbugs/issue43111.go` | verified |  |
| go | `test/fixedbugs/issue52856.dir/main.go` | verified |  |
| go | `test/fixedbugs/issue78303_2.go` | verified |  |
| go | `test/fixedbugs/issue9691.go` | verified |  |
| go | `test/ken/sliceslice.go` | verified |  |
| go | `test/prove_popcount.go` | verified |  |
| go | `test/typeswitch.go` | verified |  |
| grafana | `apps/advisor/pkg/app/metrics/metrics_test.go` | verified |  |
| grafana | `apps/alerting/rules/pkg/apis/alerting/v0alpha1/rulesequence_ext.go` | verified |  |
| grafana | `apps/annotation/pkg/apis/annotation/v0alpha1/annotation_object_gen.go` | verified |  |
| grafana | `apps/iam/pkg/apis/iam/v0alpha1/serviceaccount_createserviceaccounttoken_request_body_types_gen.go` | verified |  |
| grafana | `apps/provisioning/pkg/quotas/quotas_test.go` | verified |  |
| grafana | `apps/provisioning/pkg/repository/git/repository_error_mapping_test.go` | verified |  |
| grafana | `pkg/apis/appplugin/v0alpha1/doc.go` | verified |  |
| grafana | `pkg/generated/clientset/versioned/typed/service/v0alpha1/fake/fake_externalname.go` | verified |  |
| grafana | `pkg/infra/remotecache/testing.go` | verified |  |
| grafana | `pkg/registry/apis/iam/resourcepermission/validate_test.go` | verified |  |
| grafana | `pkg/services/apiserver/utils/uids.go` | verified |  |
| grafana | `pkg/services/authn/authnimpl/sync/access_claims.go` | verified |  |
| grafana | `pkg/services/authn/authnimpl/sync/namespace.go` | verified |  |
| grafana | `pkg/services/ldap/ldap_login_test.go` | verified |  |
| grafana | `pkg/services/live/pipeline/pipeline.go` | verified |  |
| grafana | `pkg/services/ngalert/backtesting/engine.go` | verified |  |
| grafana | `pkg/services/ngalert/notifier/legacy_storage/imported.go` | verified |  |
| grafana | `pkg/services/notifications/mock.go` | verified |  |
| grafana | `pkg/tsdb/cloudwatch/get_metric_data_executor.go` | verified |  |
| grafana | `pkg/util/xorm/xorm.go` | verified |  |
| grafana | `public/app/features/alerting/unified/components/receivers/editor/language.ts` | verified |  |
| grafana | `public/app/features/browse-dashboards/api/services.ts` | verified |  |
| grafana | `public/app/plugins/datasource/influxdb/components/editor/query/influxql/utils/unwrap.ts` | verified |  |
| grafana | `public/app/plugins/panel/alertlist/AlertInstances.tsx` | verified |  |
