# Target OSS no-LLM dogfooding audit — continuation 369 (batch 370)

Run: 2026-07-22T22:17:03.039374+00:00

## Summary

- Files audited: 50
- Verified: 50
- Refuted: 0
- Unverifiable: 0

All sampled files passed no-LLM verification; no new tool-side fixes were required.

## Sample details

| repo | file | status | notes |
|------|------|--------|-------|
| go | `src/cmd/compile/internal/ssa/fuse.go` | verified |  |
| go | `src/cmd/compile/internal/test/bench_test.go` | verified |  |
| go | `src/cmd/go/internal/doc/mod.go` | verified |  |
| go | `src/cmd/link/internal/loong64/obj.go` | verified |  |
| go | `src/compress/flate/deflate_test.go` | verified |  |
| go | `src/crypto/tls/handshake_server_tls13.go` | verified |  |
| go | `src/math/sin.go` | verified |  |
| go | `src/net/netip/fuzz_test.go` | verified |  |
| go | `src/os/user/cgo_listgroups_unix.go` | verified |  |
| go | `src/runtime/list.go` | verified |  |
| go | `src/runtime/stubs_mipsx.go` | verified |  |
| go | `src/syscall/types_freebsd.go` | verified |  |
| go | `test/fixedbugs/bug161.go` | verified |  |
| go | `test/fixedbugs/bug382.dir/prog.go` | verified |  |
| go | `test/fixedbugs/issue21120.go` | verified |  |
| go | `test/fixedbugs/issue33724.go` | verified |  |
| go | `test/fixedbugs/issue40252.go` | verified |  |
| go | `test/fixedbugs/issue41239.go` | verified |  |
| go | `test/fixedbugs/issue48088.dir/b.go` | verified |  |
| go | `test/fixedbugs/splitload_pointer_compare.go` | verified |  |
| go | `test/typeparam/fact.go` | verified |  |
| go | `test/typeparam/issue50552.go` | verified |  |
| grafana | `apps/advisor/pkg/app/app.go` | verified |  |
| grafana | `apps/provisioning/pkg/repository/webhook_repository_mock.go` | verified |  |
| grafana | `packages/grafana-api-clients/src/clients/rtkq/folder/v1beta1/endpoints.gen.ts` | verified |  |
| grafana | `packages/grafana-ui/src/components/CodeMirror/types.ts` | verified |  |
| grafana | `packages/grafana-ui/src/components/JSONFormatter/JSONFormatter.tsx` | verified |  |
| grafana | `pkg/plugins/manager/pipeline/validation/validation.go` | verified |  |
| grafana | `pkg/registry/apis/iam/serviceaccount_org_hooks.go` | verified |  |
| grafana | `pkg/registry/apis/iam/user/rest_user_team.go` | verified |  |
| grafana | `pkg/registry/apis/provisioning/informer/helpers_test.go` | verified |  |
| grafana | `pkg/registry/apis/provisioning/jobs/migrate/worker.go` | verified |  |
| grafana | `pkg/registry/apps/dashvalidator/register_test.go` | verified |  |
| grafana | `pkg/services/grpcserver/context/handler.go` | verified |  |
| grafana | `pkg/services/live/convert/convert.go` | verified |  |
| grafana | `pkg/services/loginattempt/login_attempt.go` | verified |  |
| grafana | `pkg/services/preference/prefimpl/xorm_store.go` | verified |  |
| grafana | `pkg/services/publicdashboards/internal/service/logging.go` | verified |  |
| grafana | `pkg/services/serviceaccounts/secretscan/mock.go` | verified |  |
| grafana | `pkg/services/sqlstore/migrations/user_auth_token_mig.go` | verified |  |
| grafana | `pkg/services/tag/tagimpl/store_test.go` | verified |  |
| grafana | `pkg/tests/apis/provisioning/v1beta1/helper_test.go` | verified |  |
| grafana | `public/app/features/alerting/unified/components/rule-editor/labels/LabelsFieldInFormV2.tsx` | verified |  |
| grafana | `public/app/features/alerting/unified/hooks/abilities/alertmanager/useExternalAlertmanagerAbility.ts` | verified |  |
| grafana | `public/app/features/dashboard-scene/settings/JsonModelEditView.tsx` | verified |  |
| grafana | `public/app/features/dashboard-scene/utils/pathId.ts` | verified |  |
| grafana | `public/app/features/logs/components/panel/virtualization.ts` | verified |  |
| grafana | `public/app/features/panel/components/PanelRenderer.tsx` | verified |  |
| grafana | `public/app/plugins/datasource/cloudwatch/query-runner/CloudWatchRequest.ts` | verified |  |
| grafana | `public/app/routes/utils.ts` | verified |  |
