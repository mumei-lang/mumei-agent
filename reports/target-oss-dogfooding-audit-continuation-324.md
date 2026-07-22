# Target OSS no-LLM dogfooding audit — continuation 324 (batch 325)

Run: 2026-07-22T19:43:11.715558+00:00

## Summary

- Files audited: 50
- Verified: 50
- Refuted: 0
- Unverifiable: 0

All sampled files passed no-LLM verification; no new tool-side fixes were required.

## Sample details

| repo | file | status | notes |
|------|------|--------|-------|
| go | `src/cmd/cgo/internal/testsanitizers/asan_test.go` | verified |  |
| go | `src/embed/internal/embedtest/embedx_test.go` | verified |  |
| go | `src/html/escape_test.go` | verified |  |
| go | `src/internal/profile/prune.go` | verified |  |
| go | `src/internal/syscall/unix/nonblocking_js.go` | verified |  |
| go | `src/net/interface_solaris.go` | verified |  |
| go | `src/net/interface_stub.go` | verified |  |
| go | `src/os/exec/exec.go` | verified |  |
| go | `src/os/getwd_unix_test.go` | verified |  |
| go | `src/runtime/minmax_test.go` | verified |  |
| go | `src/syscall/tables_wasip1.go` | verified |  |
| go | `test/fixedbugs/bug409.go` | verified |  |
| go | `test/fixedbugs/issue6703n.go` | verified |  |
| go | `test/fixedbugs/issue9110.go` | verified |  |
| go | `test/live.go` | verified |  |
| go | `test/typeparam/orderedmapsimp.dir/main.go` | verified |  |
| grafana | `apps/advisor/pkg/app/checks/instancechecks/pinned_version_step_test.go` | verified |  |
| grafana | `apps/dashboard/pkg/apis/dashboard/v2beta1/dashboard_object_gen.go` | verified |  |
| grafana | `apps/dashboard/pkg/apis/dashboard_manifest.go` | verified |  |
| grafana | `apps/dashboard/pkg/migration/schemaversion/v13.go` | verified |  |
| grafana | `apps/dashvalidator/pkg/validator/prometheus/provider.go` | verified |  |
| grafana | `apps/provisioning/pkg/generated/applyconfiguration/internal/internal.go` | verified |  |
| grafana | `pkg/registry/apis/iam/legacy/scope_resolver.go` | verified |  |
| grafana | `pkg/registry/apis/iam/resourcepermission/models.go` | verified |  |
| grafana | `pkg/services/folder/tree.go` | verified |  |
| grafana | `pkg/services/ngalert/state/testing.go` | verified |  |
| grafana | `pkg/storage/unified/resource/pending_delete_store.go` | verified |  |
| grafana | `pkg/tsdb/cloudwatch/models/resources/log_groups_resource_request.go` | verified |  |
| grafana | `pkg/tsdb/grafana-testdata-datasource/testdata.go` | verified |  |
| grafana | `pkg/tsdb/graphite/healthcheck.go` | verified |  |
| grafana | `pkg/util/encryption.go` | verified |  |
| grafana | `public/app/features/alerting/state/selectors.ts` | verified |  |
| grafana | `public/app/features/alerting/unified/components/rule-viewer/tabs/extensions/RuleViewerExtension.tsx` | verified |  |
| grafana | `public/app/features/alerting/unified/rule-list/hooks/datasourceFilter.ts` | verified |  |
| grafana | `public/app/features/dashboard-scene/scene/layouts-shared/addNew.ts` | verified |  |
| grafana | `public/app/features/explore/FeatureTogglePage.tsx` | verified |  |
| grafana | `public/app/features/provisioning/components/Shared/WebhookDisabledField.tsx` | verified |  |
| grafana | `public/app/plugins/datasource/azuremonitor/utils/useAsyncState.ts` | verified |  |
| grafana | `public/app/plugins/datasource/azuremonitor/variables.ts` | verified |  |
| grafana | `public/app/plugins/panel/timeseries/plugins/annotations/AnnotationAvatar.tsx` | verified |  |
| prysm | `beacon-chain/blockchain/init_test.go` | verified |  |
| prysm | `beacon-chain/core/helpers/deposit_test.go` | verified |  |
| prysm | `beacon-chain/core/helpers/rewards_penalties.go` | verified |  |
| prysm | `beacon-chain/das/blob_cache.go` | verified |  |
| prysm | `beacon-chain/operations/slashings/mock/mock.go` | verified |  |
| prysm | `beacon-chain/rpc/prysm/beacon/ssz_query_test.go` | verified |  |
| prysm | `beacon-chain/state/state-native/state_trie_test.go` | verified |  |
| prysm | `crypto/keystore/key_test.go` | verified |  |
| prysm | `testing/spectest/minimal/altair__operations__attestation_test.go` | verified |  |
| prysm | `tools/analyzers/ineffassign/analyzer.go` | verified |  |
