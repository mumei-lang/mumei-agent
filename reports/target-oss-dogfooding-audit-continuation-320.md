# Target OSS no-LLM dogfooding audit — continuation 320 (batch 321)

Run: 2026-07-22T19:25:24.768350+00:00

## Summary

- Files audited: 50
- Verified: 50
- Refuted: 0
- Unverifiable: 0

All sampled files passed no-LLM verification; no new tool-side fixes were required.

## Sample details

| repo | file | status | notes |
|------|------|--------|-------|
| go | `src/crypto/tls/auth_test.go` | verified |  |
| go | `src/encoding/binary/native_endian_big.go` | verified |  |
| go | `src/encoding/json/internal/jsonopts/options_format.go` | verified |  |
| go | `src/internal/fmtsort/sort.go` | verified |  |
| go | `src/internal/goos/goos.go` | verified |  |
| go | `src/runtime/mcleanup.go` | verified |  |
| go | `src/runtime/signal_linux_arm64.go` | verified |  |
| go | `src/simd/ip_test.go` | verified |  |
| go | `test/escape_iface_data.go` | verified |  |
| go | `test/fixedbugs/bug354.go` | verified |  |
| go | `test/fixedbugs/issue22305.go` | verified |  |
| go | `test/fixedbugs/issue24488.go` | verified |  |
| go | `test/fixedbugs/issue35576.go` | verified |  |
| go | `test/fixedbugs/issue80097.go` | verified |  |
| go | `test/typeparam/issue48645a.go` | verified |  |
| grafana | `apps/example/pkg/apis/example/v0alpha1/example_schema_gen.go` | verified |  |
| grafana | `apps/logsdrilldown/pkg/apis/logsdrilldown/v1alpha1/logsdrilldowndefaults_client_gen.go` | verified |  |
| grafana | `apps/provisioning/pkg/repository/github/factory.go` | verified |  |
| grafana | `apps/provisioning/pkg/repository/staged_repository_mock.go` | verified |  |
| grafana | `e2e-playwright/test-plugins/grafana-test-datasource/types.ts` | verified |  |
| grafana | `packages/grafana-alerting/src/unstable.ts` | verified |  |
| grafana | `packages/grafana-sql/i18next.config.ts` | verified |  |
| grafana | `packages/grafana-ui/src/components/Forms/Field.tsx` | verified |  |
| grafana | `packages/grafana-ui/src/components/ThemeDemos/BorderRadius.tsx` | verified |  |
| grafana | `pkg/api/api_test.go` | verified |  |
| grafana | `pkg/infra/metrics/service.go` | verified |  |
| grafana | `pkg/operators/provisioning/jobs_operator.go` | verified |  |
| grafana | `pkg/registry/apis/provisioning/jobs/loki_history.go` | verified |  |
| grafana | `pkg/services/authz/zanzana/server/admission.go` | verified |  |
| grafana | `pkg/services/provisioning/alerting/rules_provisioner.go` | verified |  |
| grafana | `pkg/storage/unified/search/bleve_snapshot.go` | verified |  |
| grafana | `pkg/storage/unified/sql/sqltemplate/mocks/WithResults.go` | verified |  |
| grafana | `pkg/tsdb/cloudwatch/models/resources/metrics_resource_request.go` | verified |  |
| grafana | `public/app/features/alerting/unified/hooks/useInhibitedAlerts.ts` | verified |  |
| grafana | `public/app/features/alerting/unified/rule-editor/RuleEditor.tsx` | verified |  |
| grafana | `public/app/features/dashboard-scene/settings/variables/components/ConstantVariableForm.tsx` | verified |  |
| grafana | `public/app/features/manage-dashboards/import/components/ImportForm.tsx` | verified |  |
| grafana | `public/app/features/provisioning/Migrate/OverviewStatCards.tsx` | verified |  |
| grafana | `public/app/plugins/datasource/influxdb/components/editor/annotation/AnnotationEditor.tsx` | verified |  |
| grafana | `public/app/plugins/panel/news/module.tsx` | verified |  |
| prysm | `async/event/example_subscription_test.go` | verified |  |
| prysm | `beacon-chain/execution/testing/mock_faulty_powchain.go` | verified |  |
| prysm | `beacon-chain/operations/payloadattestation/metrics.go` | verified |  |
| prysm | `beacon-chain/state/error.go` | verified |  |
| prysm | `beacon-chain/sync/subscriber_beacon_aggregate_proof_test.go` | verified |  |
| prysm | `proto/prysm/v1alpha1/payload_attestation_mainnet.go` | verified |  |
| prysm | `testing/spectest/minimal/deneb__fork_transition__transition_test.go` | verified |  |
| prysm | `testing/spectest/minimal/electra__rewards__rewards_test.go` | verified |  |
| prysm | `testing/spectest/shared/electra/fork/upgrade_to_electra.go` | verified |  |
| prysm | `validator/client/key_reload_test.go` | verified |  |
