# Target OSS no-LLM dogfooding audit — continuation 353 (batch 354)

Run: 2026-07-22T21:09:50.867470+00:00

## Summary

- Files audited: 50
- Verified: 50
- Refuted: 0
- Unverifiable: 0

All sampled files passed no-LLM verification; no new tool-side fixes were required.

## Sample details

| repo | file | status | notes |
|------|------|--------|-------|
| go | `src/cmd/compile/internal/ssa/fuse_branchredirect.go` | verified |  |
| go | `src/cmd/go/internal/lockedfile/internal/filelock/filelock_test.go` | verified |  |
| go | `src/cmd/go/internal/modcmd/edit.go` | verified |  |
| go | `src/crypto/internal/fips140/nistec/fiat/p224.go` | verified |  |
| go | `src/net/internal/socktest/switch_unix.go` | verified |  |
| go | `src/runtime/dit.go` | verified |  |
| go | `src/runtime/secret/secret_test.go` | verified |  |
| go | `src/time/tzdata/tzdata.go` | verified |  |
| go | `test/fixedbugs/bug367.dir/prog.go` | verified |  |
| go | `test/fixedbugs/issue46749.go` | verified |  |
| go | `test/fixedbugs/issue59638.go` | verified |  |
| go | `test/fixedbugs/issue78313.go` | verified |  |
| go | `test/typeparam/mutualimp.dir/b.go` | verified |  |
| grafana | `apps/alerting/notifications/pkg/apis/alertingnotifications/v0alpha1/receiver_spec_gen.go` | verified |  |
| grafana | `apps/provisioning/pkg/connection/github/token_test.go` | verified |  |
| grafana | `packages/grafana-data/src/dataframe/DataFrameJSON.ts` | verified |  |
| grafana | `packages/grafana-data/src/types/featureToggles.gen.ts` | verified |  |
| grafana | `packages/grafana-sql/src/components/visual-query-builder/GroupByRow.tsx` | verified |  |
| grafana | `packages/grafana-ui/src/themes/GlobalStyles/hacks.ts` | verified |  |
| grafana | `pkg/apiserver/endpoints/responsewriter/responsewriter_test.go` | verified |  |
| grafana | `pkg/expr/mathexp/exp_test.go` | verified |  |
| grafana | `pkg/services/authz/zanzana/server/server_write_test.go` | verified |  |
| grafana | `pkg/services/login/authinfotest/fake.go` | verified |  |
| grafana | `pkg/services/navtree/navtreeimpl/admin.go` | verified |  |
| grafana | `pkg/storage/legacysql/dualwrite/dualwriter_continue_token.go` | verified |  |
| grafana | `pkg/tests/api/prometheus/prometheus_test.go` | verified |  |
| grafana | `pkg/tests/apis/dashboard/dashboards_test.go` | verified |  |
| grafana | `pkg/tsdb/grafana-testdata-datasource/scenarios_test.go` | verified |  |
| grafana | `pkg/tsdb/jaeger/client.go` | verified |  |
| grafana | `public/app/core/components/Breadcrumbs/types.ts` | verified |  |
| grafana | `public/app/core/components/Page/PageHeader.tsx` | verified |  |
| grafana | `public/app/core/config.ts` | verified |  |
| grafana | `public/app/features/alerting/unified/components/notification-policies/PromDurationDocs.tsx` | verified |  |
| grafana | `public/app/features/alerting/unified/triage/hooks/useTriageSavedSearches.ts` | verified |  |
| grafana | `public/app/features/dashboard-scene/edit-pane/DashboardEditPane.tsx` | verified |  |
| grafana | `public/app/features/dashboard-scene/scene/panel-timerange/utils.ts` | verified |  |
| grafana | `public/app/features/logs/components/panel/LogLineDetails.tsx` | verified |  |
| grafana | `public/app/plugins/datasource/cloudwatch/components/shared/LogGroups/Search.tsx` | verified |  |
| grafana | `public/app/plugins/datasource/cloudwatch/mocks/cloudwatch-logs-test-data/multiLineFullQuery.ts` | verified |  |
| grafana | `public/app/store/store.ts` | verified |  |
| prysm | `beacon-chain/rpc/eth/beacon/handlers_gloas_bid_test.go` | verified |  |
| prysm | `beacon-chain/rpc/prysm/v1alpha1/beacon/assignments.go` | verified |  |
| prysm | `beacon-chain/rpc/prysm/v1alpha1/validator/duties_v3.go` | verified |  |
| prysm | `encoding/ssz/detect/configfork.go` | verified |  |
| prysm | `encoding/ssz/htrutils_test.go` | verified |  |
| prysm | `encoding/ssz/query/testutil/runner.go` | verified |  |
| prysm | `proto/prysm/v1alpha1/attestation/aggregation/attestations/attestations_test.go` | verified |  |
| prysm | `testing/spectest/mainnet/deneb__epoch_processing__slashings_test.go` | verified |  |
| prysm | `testing/spectest/shared/deneb/merkle_proof/merkle_proof.go` | verified |  |
| prysm | `tools/analyzers/recursivelock/analyzer.go` | verified |  |
