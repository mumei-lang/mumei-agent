# Target OSS no-LLM dogfooding audit — continuation 379 (batch 380)

Run: 2026-07-22T23:25:41.639467+00:00

## Summary

- Files audited: 50
- Verified: 50
- Refuted: 0
- Unverifiable: 0

All sampled files passed no-LLM verification; no new tool-side fixes were required.

## Sample details

| repo | file | status | notes |
|------|------|--------|-------|
| go | `src/cmd/cgo/internal/testplugin/plugin_test.go` | verified |  |
| go | `src/cmd/compile/internal/base/base.go` | verified |  |
| go | `src/cmd/compile/internal/ssa/_gen/PPC64Ops.go` | verified |  |
| go | `src/cmd/compile/internal/ssa/stmtlines_test.go` | verified |  |
| go | `src/cmd/compile/internal/types2/basic.go` | verified |  |
| go | `src/cmd/internal/obj/data.go` | verified |  |
| go | `src/crypto/internal/fips140/bigmod/nat_noasm.go` | verified |  |
| go | `src/crypto/x509/pem_decrypt.go` | verified |  |
| go | `src/go/internal/gccgoimporter/gccgoinstallation_test.go` | verified |  |
| go | `src/internal/fuzz/encoding.go` | verified |  |
| go | `src/internal/goarch/goarch_wasm.go` | verified |  |
| go | `src/runtime/goroutineleakprofile_test.go` | verified |  |
| go | `src/runtime/mheap.go` | verified |  |
| go | `src/runtime/sys_x86.go` | verified |  |
| go | `test/abi/method_wrapper.go` | verified |  |
| go | `test/fixedbugs/bug289.go` | verified |  |
| go | `test/fixedbugs/issue20250.go` | verified |  |
| go | `test/fixedbugs/issue24491a.go` | verified |  |
| go | `test/fixedbugs/issue29218.go` | verified |  |
| grafana | `apps/alerting/notifications/pkg/apis/alertingnotifications/v1beta1/receiver_createreceiverintegrationtest_request_body_types_gen.go` | verified |  |
| grafana | `apps/dashboard/pkg/apis/dashboard/v1/constants.go` | verified |  |
| grafana | `apps/logsdrilldown/pkg/apis/logsdrilldown/v1alpha1/logsdrilldowndefaults_spec_gen.go` | verified |  |
| grafana | `apps/provisioning/pkg/connection/validator_test.go` | verified |  |
| grafana | `packages/grafana-api-clients/src/clients/rtkq/dashboard/v0alpha1/index.ts` | verified |  |
| grafana | `packages/grafana-plugin-configs/jest/mocks/images.ts` | verified |  |
| grafana | `packages/grafana-ui/src/graveyard/TimeSeries/TimeSeries.tsx` | verified |  |
| grafana | `packages/grafana-ui/src/utils/useForceUpdate.ts` | verified |  |
| grafana | `pkg/generated/clientset/versioned/typed/service/v0alpha1/fake/doc.go` | verified |  |
| grafana | `pkg/registry/apis/provisioning/resources/id.go` | verified |  |
| grafana | `pkg/registry/apis/secret/encryption/secrets.go` | verified |  |
| grafana | `pkg/services/featuremgmt/manager.go` | verified |  |
| grafana | `pkg/services/live/runstream/mock.go` | verified |  |
| grafana | `pkg/services/ngalert/metrics/sender.go` | verified |  |
| grafana | `pkg/services/quota/quotaimpl/quota.go` | verified |  |
| grafana | `pkg/services/tag/model.go` | verified |  |
| grafana | `pkg/storage/unified/migrations/service_test.go` | verified |  |
| grafana | `pkg/tests/apis/alerting/rules/recordingrule/history_trash_test.go` | verified |  |
| grafana | `pkg/tests/apis/provisioning/jobs/pending_delete_test.go` | verified |  |
| grafana | `public/app/features/alerting/unified/api/onCallApi.ts` | verified |  |
| grafana | `public/app/features/alerting/unified/components/rule-editor/QueryOptions.tsx` | verified |  |
| grafana | `public/app/features/alerting/unified/components/rules/CloneRule.tsx` | verified |  |
| grafana | `public/app/features/alerting/unified/extensions/tabExtensionRegistry.ts` | verified |  |
| grafana | `public/app/features/alerting/unified/utils/routeTree.ts` | verified |  |
| grafana | `public/app/features/dashboard-scene/scene/layouts-shared/utils.ts` | verified |  |
| grafana | `public/app/features/explore/Logs/constants.ts` | verified |  |
| grafana | `public/app/features/explore/Table/TableContainer.tsx` | verified |  |
| grafana | `public/app/features/inspector/utils/transformToOTLP.ts` | verified |  |
| grafana | `public/app/features/provisioning/utils/data.ts` | verified |  |
| grafana | `public/app/plugins/datasource/cloudwatch/migrations/useMigratedQuery.ts` | verified |  |
| grafana | `public/app/plugins/datasource/loki/components/monaco-query-field/monaco-completion-provider/CompletionDataProvider.ts` | verified |  |
