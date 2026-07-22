# Target OSS no-LLM dogfooding audit — continuation 304 (batch 305)

Run: 2026-07-22T18:26:15.039426+00:00

## Summary

- Files audited: 50
- Verified: 50
- Refuted: 0
- Unverifiable: 0

All sampled files passed no-LLM verification; no new tool-side fixes were required.

## Sample details

| repo | file | status | notes |
|------|------|--------|-------|
| go | `src/context/benchmark_test.go` | verified |  |
| go | `src/crypto/internal/fips140/nistec/p256_table_test.go` | verified |  |
| go | `src/crypto/internal/fips140test/acvp_mldsa_test.go` | verified |  |
| go | `src/encoding/json/v2/doc.go` | verified |  |
| go | `src/internal/runtime/gc/scan/expand_test.go` | verified |  |
| go | `src/internal/syscall/windows/registry/registry_test.go` | verified |  |
| go | `src/runtime/debuglog_on.go` | verified |  |
| go | `src/syscall/zerrors_linux_loong64.go` | verified |  |
| go | `src/unicode/script_test.go` | verified |  |
| go | `test/fixedbugs/bug269.go` | verified |  |
| go | `test/fixedbugs/bug375.go` | verified |  |
| go | `test/fixedbugs/issue16331.go` | verified |  |
| go | `test/fixedbugs/issue24470.go` | verified |  |
| go | `test/strcopy.go` | verified |  |
| go | `test/typeparam/issue47948.go` | verified |  |
| grafana | `apps/alerting/rules/pkg/app/rulesequence/mutator.go` | verified |  |
| grafana | `apps/dashboard/pkg/apis/dashboard/v1/zz_generated.openapi.go` | verified |  |
| grafana | `apps/iam/pkg/apis/iam/v0alpha1/role_schema_gen.go` | verified |  |
| grafana | `apps/preferences/pkg/apis/preferences/v1alpha1/register.go` | verified |  |
| grafana | `packages/grafana-ui/src/components/Table/TableNG/Cells/MarkdownCell.tsx` | verified |  |
| grafana | `packages/grafana-ui/src/components/ThemeDemos/EmotionPerfTest.tsx` | verified |  |
| grafana | `packages/grafana-ui/src/themes/GlobalStyles/extra.ts` | verified |  |
| grafana | `pkg/api/routing/routing.go` | verified |  |
| grafana | `pkg/infra/httpclient/harcapture/harcapture_test.go` | verified |  |
| grafana | `pkg/registry/apis/appplugin/sub_health.go` | verified |  |
| grafana | `pkg/registry/apis/provisioning/jobs/delete/worker_test.go` | verified |  |
| grafana | `pkg/registry/apis/service/register.go` | verified |  |
| grafana | `pkg/services/folder/folderimpl/folder_test.go` | verified |  |
| grafana | `pkg/services/ngalert/api/tooling/definitions/provisioning.go` | verified |  |
| grafana | `pkg/storage/unified/resource/client_test.go` | verified |  |
| grafana | `pkg/storage/unified/resource/notifier_nats_integration_test.go` | verified |  |
| grafana | `pkg/tests/apis/shorturl/shorturl_test.go` | verified |  |
| grafana | `pkg/util/uri_sanitize_test.go` | verified |  |
| grafana | `public/app/features/alerting/unified/components/alert-groups/AlertDetails.tsx` | verified |  |
| grafana | `public/app/features/dashboard-scene/conditional-rendering/group/types.ts` | verified |  |
| grafana | `public/app/features/dashboard/state/__fixtures__/dashboardFixtures.ts` | verified |  |
| grafana | `public/app/features/templating/macroRegistry.ts` | verified |  |
| grafana | `public/app/features/variables/shared/multiOptions.ts` | verified |  |
| grafana | `public/app/plugins/datasource/azuremonitor/components/MetricsQueryEditor/TopField.tsx` | verified |  |
| grafana | `public/app/plugins/panel/table/module.tsx` | verified |  |
| prysm | `crypto/bls/blst/stub.go` | verified |  |
| prysm | `encoding/ssz/query/path.go` | verified |  |
| prysm | `proto/prysm/v1alpha1/attestation/aggregation/sync_contribution/naive.go` | verified |  |
| prysm | `testing/spectest/mainnet/electra__operations__voluntary_exit_test.go` | verified |  |
| prysm | `testing/spectest/minimal/capella__random__random_test.go` | verified |  |
| prysm | `testing/spectest/minimal/fulu__networking__custody_columns_test.go` | verified |  |
| prysm | `testing/spectest/minimal/gloas__operations__attestation_test.go` | verified |  |
| prysm | `testing/util/altair.go` | verified |  |
| prysm | `validator/client/grpc-api/grpc_node_client.go` | verified |  |
| prysm | `validator/helpers/node_connection.go` | verified |  |
