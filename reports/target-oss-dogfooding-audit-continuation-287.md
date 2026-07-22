# Target OSS no-LLM dogfooding audit — continuation 287 (batch 288)

Run: 2026-07-22T17:11:34.927408+00:00

## Summary

- Files audited: 50
- Verified: 50
- Refuted: 0
- Unverifiable: 0

All sampled files passed no-LLM verification; no new tool-side fixes were required.

## Sample details

| repo | file | status | notes |
|------|------|--------|-------|
| go | `src/cmd/compile/internal/ir/reassignment.go` | verified |  |
| go | `src/cmd/compile/internal/types2/compilersupport.go` | verified |  |
| go | `src/cmd/go/internal/lockedfile/lockedfile.go` | verified |  |
| go | `src/internal/syscall/unix/kernel_version_solaris_test.go` | verified |  |
| go | `src/runtime/cpuprof.go` | verified |  |
| go | `src/syscall/zerrors_freebsd_amd64.go` | verified |  |
| go | `test/fixedbugs/bug372.go` | verified |  |
| go | `test/fixedbugs/bug448.dir/pkg1.go` | verified |  |
| go | `test/fixedbugs/bug510.dir/a.go` | verified |  |
| go | `test/fixedbugs/issue19548.dir/a.go` | verified |  |
| go | `test/fixedbugs/issue22458.go` | verified |  |
| go | `test/fixedbugs/issue31010.go` | verified |  |
| grafana | `apps/annotation/pkg/apis/annotation/v0alpha1/annotation_schema_gen.go` | verified |  |
| grafana | `apps/iam/pkg/apis/iam/v0alpha1/team_createteammember_request_body_types_gen.go` | verified |  |
| grafana | `apps/provisioning/pkg/generated/clientset/versioned/scheme/doc.go` | verified |  |
| grafana | `apps/secret/decrypt/v1beta1/decrypt_grpc.pb.go` | verified |  |
| grafana | `apps/shorturl/pkg/apis/shorturl/v1beta1/shorturl_status_gen.go` | verified |  |
| grafana | `packages/grafana-data/src/utils/numbers.ts` | verified |  |
| grafana | `packages/grafana-runtime/src/analytics/plugins/eventProperties.ts` | verified |  |
| grafana | `packages/grafana-ui/src/themes/GlobalStyles/forms.ts` | verified |  |
| grafana | `pkg/api/user_test.go` | verified |  |
| grafana | `pkg/middleware/gziper.go` | verified |  |
| grafana | `pkg/registry/apis/secret/mutator/secure_value_test.go` | verified |  |
| grafana | `pkg/services/authn/clients/session_test.go` | verified |  |
| grafana | `pkg/services/authz/zanzana/server/metrics.go` | verified |  |
| grafana | `pkg/services/ngalert/schedule/metrics_test.go` | verified |  |
| grafana | `pkg/services/plugindashboards/service/service.go` | verified |  |
| grafana | `pkg/setting/settings_zanzana_test.go` | verified |  |
| grafana | `pkg/tests/api/alerting/api_provisioning_access_control_test.go` | verified |  |
| grafana | `pkg/tsdb/grafana-testdata-datasource/csv_data_test.go` | verified |  |
| grafana | `public/app/api/clients/annotation/v0alpha1/index.ts` | verified |  |
| grafana | `public/app/features/admin/UserListAdminPage.tsx` | verified |  |
| grafana | `public/app/features/alerting/unified/components/rules/central-state-history/CentralAlertHistoryPage.tsx` | verified |  |
| grafana | `public/app/features/alerting/unified/triage/rows/utils.ts` | verified |  |
| grafana | `public/app/features/alerting/unified/triage/scene/BadgeCounts.tsx` | verified |  |
| grafana | `public/app/features/connections/components/AdvisorRedirectNotice/AdvisorRedirectNotice.tsx` | verified |  |
| grafana | `public/app/features/playlist/StartModal.tsx` | verified |  |
| grafana | `public/app/plugins/datasource/cloudwatch/mocks/cloudwatch-logs-test-data/filterQuery.ts` | verified |  |
| grafana | `public/app/plugins/datasource/cloudwatch/utils/logGroupsConstants.ts` | verified |  |
| grafana | `public/app/plugins/datasource/jaeger/datasource.ts` | verified |  |
| prysm | `beacon-chain/core/blocks/block_operations_fuzz_test.go` | verified |  |
| prysm | `beacon-chain/operations/attestations/prune_expired.go` | verified |  |
| prysm | `beacon-chain/state/state-native/custom-types/randao_mixes_test.go` | verified |  |
| prysm | `proto/eth/v1/gateway.ssz.go` | verified |  |
| prysm | `testing/spectest/mainnet/altair__operations__attestation_test.go` | verified |  |
| prysm | `testing/spectest/mainnet/fulu__epoch_processing__justification_and_finalization_test.go` | verified |  |
| prysm | `testing/spectest/minimal/capella__sanity__slots_test.go` | verified |  |
| prysm | `testing/spectest/shared/capella/epoch_processing/eth1_data_reset.go` | verified |  |
| prysm | `validator/client/beacon-api/domain_data_test.go` | verified |  |
| prysm | `validator/db/kv/eip_blacklisted_keys.go` | verified |  |
