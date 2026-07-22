# Target OSS no-LLM dogfooding audit — continuation 274 (batch 275)

Run: 2026-07-22T16:22:43.968007+00:00

## Summary

- Files audited: 50
- Verified: 50
- Refuted: 0
- Unverifiable: 0

All sampled files passed no-LLM verification; no new tool-side fixes were required.

## Sample details

| repo | file | status | notes |
|------|------|--------|-------|
| go | `src/cmd/go/go_boring_test.go` | verified |  |
| go | `src/cmd/go/internal/lockedfile/internal/filelock/filelock_fcntl.go` | verified |  |
| go | `src/cmd/internal/obj/loong64/cnames.go` | verified |  |
| go | `src/compress/flate/writer_test.go` | verified |  |
| go | `src/crypto/x509/verify.go` | verified |  |
| go | `src/net/file.go` | verified |  |
| go | `src/net/sockoptip_stub.go` | verified |  |
| go | `src/reflect/visiblefields.go` | verified |  |
| go | `src/runtime/linkname.go` | verified |  |
| go | `src/sync/cond_test.go` | verified |  |
| go | `test/fixedbugs/bug174.go` | verified |  |
| go | `test/fixedbugs/issue5358.go` | verified |  |
| go | `test/typeparam/issue47892.go` | verified |  |
| grafana | `apps/correlations/pkg/apis/correlation/v0alpha1/correlation_object_gen.go` | verified |  |
| grafana | `apps/correlations/plugin/src/generated/correlation/v0alpha1/types.metadata.gen.ts` | verified |  |
| grafana | `packages/grafana-ui/src/components/ColorPicker/NamedColorsPalette.tsx` | verified |  |
| grafana | `pkg/api/common_test.go` | verified |  |
| grafana | `pkg/infra/tracing/tracing.go` | verified |  |
| grafana | `pkg/plugins/log/logger.go` | verified |  |
| grafana | `pkg/registry/apis/appplugin/authorizer_test.go` | verified |  |
| grafana | `pkg/registry/apis/preferences/legacy/preferences.go` | verified |  |
| grafana | `pkg/services/accesscontrol/evaluator_test.go` | verified |  |
| grafana | `pkg/services/ngalert/api/api_prometheus_test.go` | verified |  |
| grafana | `pkg/services/ngalert/state/persister_sync_rule_test.go` | verified |  |
| grafana | `pkg/services/screenshot/screenshot.go` | verified |  |
| grafana | `pkg/services/sqlstore/migrations/accesscontrol/test/action_migrator_test.go` | verified |  |
| grafana | `pkg/services/sqlstore/migrations/accesscontrol/test/dashbord_permission_migrator_test.go` | verified |  |
| grafana | `pkg/services/tag/model_test.go` | verified |  |
| grafana | `pkg/storage/secret/metadata/secure_value_test.go` | verified |  |
| grafana | `pkg/storage/unified/resource/watch_publisher.go` | verified |  |
| grafana | `pkg/storage/unified/search/vector/queries_test.go` | verified |  |
| grafana | `pkg/web/binding.go` | verified |  |
| grafana | `public/app/features/alerting/unified/mocks/server/handlers/plugins.ts` | verified |  |
| grafana | `public/app/features/alerting/unified/rule-list/hooks/useLazyLoadPrometheusGroups.tsx` | verified |  |
| grafana | `public/app/features/dashboard-scene/settings/variables/components/VariableDisplaySelect.tsx` | verified |  |
| grafana | `public/app/features/dashboard-scene/settings/variables/editors/CustomVariableEditor/CustomVariableEditor.tsx` | verified |  |
| grafana | `public/app/features/expressions/utils/expressionTypes.ts` | verified |  |
| grafana | `public/app/features/provisioning/types.ts` | verified |  |
| prysm | `api/client/beacon/client.go` | verified |  |
| prysm | `api/client/beacon/log.go` | verified |  |
| prysm | `api/server/structs/conversions_block_gloas.go` | verified |  |
| prysm | `beacon-chain/p2p/addr_factory_test.go` | verified |  |
| prysm | `beacon-chain/p2p/custody.go` | verified |  |
| prysm | `beacon-chain/state/stategen/setter_test.go` | verified |  |
| prysm | `testing/spectest/minimal/altair__epoch_processing__participation_flag_updates_test.go` | verified |  |
| prysm | `testing/spectest/shared/capella/fork/transition.go` | verified |  |
| prysm | `time/slots/slotticker_test.go` | verified |  |
| prysm | `tools/beacon-fuzz/main.go` | verified |  |
| prysm | `tools/interop/split-keys/main.go` | verified |  |
| prysm | `validator/keymanager/local/backup.go` | verified |  |
