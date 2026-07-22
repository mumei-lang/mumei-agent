# Target OSS no-LLM dogfooding audit — continuation 300 (batch 301)

Run: 2026-07-22T18:14:42.447432+00:00

## Summary

- Files audited: 50
- Verified: 50
- Refuted: 0
- Unverifiable: 0

All sampled files passed no-LLM verification; no new tool-side fixes were required.

## Sample details

| repo | file | status | notes |
|------|------|--------|-------|
| go | `src/cmd/internal/obj/riscv/inst.go` | verified |  |
| go | `src/crypto/internal/sysrand/rand.go` | verified |  |
| go | `src/crypto/tls/handshake_messages.go` | verified |  |
| go | `src/internal/syscall/unix/siginfo_linux_mipsx.go` | verified |  |
| go | `src/math/big/arith_test.go` | verified |  |
| go | `src/net/http/clientconn.go` | verified |  |
| go | `src/net/http/http1_server_test.go` | verified |  |
| go | `src/syscall/syscall_linux_s390x.go` | verified |  |
| go | `test/fixedbugs/bug260.go` | verified |  |
| go | `test/fixedbugs/bug261.go` | verified |  |
| go | `test/fixedbugs/bug286.go` | verified |  |
| go | `test/fixedbugs/bug324.dir/p.go` | verified |  |
| go | `test/fixedbugs/issue22781.go` | verified |  |
| go | `test/fixedbugs/issue25055.dir/b.go` | verified |  |
| go | `test/fixedbugs/issue27938.go` | verified |  |
| go | `test/fixedbugs/issue9731.go` | verified |  |
| grafana | `apps/dashboard/pkg/apis/dashboard/v2beta1/dashboard_schema_gen.go` | verified |  |
| grafana | `apps/provisioning/pkg/connection/secure.go` | verified |  |
| grafana | `packages/grafana-alerting/src/grafana/notificationPolicies/hooks/useRoutingTrees.ts` | verified |  |
| grafana | `packages/grafana-schema/src/schema/dashboard/v2/types.metadata.gen.ts` | verified |  |
| grafana | `packages/grafana-ui/src/components/RadialGauge/types.ts` | verified |  |
| grafana | `packages/grafana-ui/src/components/VizTooltip/VizTooltipFooter.tsx` | verified |  |
| grafana | `packages/grafana-ui/src/components/uPlot/config.ts` | verified |  |
| grafana | `pkg/api/frontendlogging/grafana_javascript_agent.go` | verified |  |
| grafana | `pkg/apiserver/endpoints/responsewriter/responsewriter.go` | verified |  |
| grafana | `pkg/registry/apis/iam/api_installer.go` | verified |  |
| grafana | `pkg/services/accesscontrol/permreg/permreg_test.go` | verified |  |
| grafana | `pkg/services/authz/wireset.go` | verified |  |
| grafana | `pkg/services/folderreconcile/reconciler.go` | verified |  |
| grafana | `pkg/services/sqlstore/migrations/ualert/test/testing.go` | verified |  |
| grafana | `pkg/storage/unified/sql/db/mocks/DB.go` | verified |  |
| grafana | `pkg/util/encryption_test.go` | verified |  |
| grafana | `public/app/core/components/SharedPreferences/analytics/types.ts` | verified |  |
| grafana | `public/app/features/alerting/unified/hooks/useNotificationAlerts.ts` | verified |  |
| grafana | `public/app/features/alerting/unified/insights/mimir/Notifications.tsx` | verified |  |
| grafana | `public/app/features/dashboard-scene/settings/variables/editors/QueryVariableEditor/VariableOptionsSpreadsheet/PasteButton.tsx` | verified |  |
| grafana | `public/app/features/migrate-to-cloud/onprem/StatusCell.tsx` | verified |  |
| grafana | `public/app/plugins/datasource/azuremonitor/mocks/datasource.ts` | verified |  |
| grafana | `public/app/plugins/datasource/cloudwatch/components/QueryEditor/LogsQueryEditor/LogsAnomaliesQueryEditor.tsx` | verified |  |
| grafana | `public/app/plugins/gen.go` | verified |  |
| prysm | `beacon-chain/cache/sync_committee.go` | verified |  |
| prysm | `beacon-chain/core/epoch/precompute/type.go` | verified |  |
| prysm | `beacon-chain/operations/blstoexec/mock/mock.go` | verified |  |
| prysm | `proto/migration/enums_test.go` | verified |  |
| prysm | `proto/testing/test.pb.go` | verified |  |
| prysm | `testing/spectest/minimal/fulu__forkchoice__forkchoice_test.go` | verified |  |
| prysm | `testing/spectest/minimal/gloas__operations__builder_deposit_request_test.go` | verified |  |
| prysm | `testing/spectest/shared/common/operations/bls_to_execution_changes.go` | verified |  |
| prysm | `tools/analyzers/httpwriter/analyzer.go` | verified |  |
| prysm | `validator/client/aggregate.go` | verified |  |
