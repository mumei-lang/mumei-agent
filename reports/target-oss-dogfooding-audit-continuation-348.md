# Target OSS no-LLM dogfooding audit — continuation 348 (batch 349)

Run: 2026-07-22T21:00:38.171422+00:00

## Summary

- Files audited: 50
- Verified: 50
- Refuted: 0
- Unverifiable: 0

All sampled files passed no-LLM verification; no new tool-side fixes were required.

## Sample details

| repo | file | status | notes |
|------|------|--------|-------|
| go | `src/internal/runtime/maps/runtime_faststr.go` | verified |  |
| go | `src/net/http/pprof/pprof.go` | verified |  |
| go | `src/os/file.go` | verified |  |
| go | `src/regexp/syntax/doc.go` | verified |  |
| go | `src/testing/iotest/example_test.go` | verified |  |
| go | `test/fixedbugs/bug101.go` | verified |  |
| go | `test/fixedbugs/bug160.dir/x.go` | verified |  |
| go | `test/fixedbugs/issue11987.go` | verified |  |
| go | `test/fixedbugs/issue29190.go` | verified |  |
| go | `test/fixedbugs/issue34577.go` | verified |  |
| go | `test/fixedbugs/issue38125.go` | verified |  |
| go | `test/fixedbugs/issue6703r.go` | verified |  |
| go | `test/stress/runstress.go` | verified |  |
| grafana | `apps/iam/pkg/apis/iam/v0alpha1/globalrole_schema_gen.go` | verified |  |
| grafana | `apps/plugins/pkg/apis/plugins/v0alpha1/meta_status_gen.go` | verified |  |
| grafana | `packages/grafana-flamegraph/src/CallTree/CallTreeTable.tsx` | verified |  |
| grafana | `packages/grafana-ui/src/components/BrowserLabel/Label.tsx` | verified |  |
| grafana | `packages/grafana-ui/src/components/Table/TableNG/components/TableCellActions.tsx` | verified |  |
| grafana | `packages/grafana-ui/src/types/select.ts` | verified |  |
| grafana | `pkg/apis/datasource/v0alpha1/datasource.go` | verified |  |
| grafana | `pkg/cmd/grafana-cli/commands/upgrade_all_command.go` | verified |  |
| grafana | `pkg/registry/apis/provisioning/jobs/sync/managed_resource_index_test.go` | verified |  |
| grafana | `pkg/registry/apis/provisioning/webhooks/pullrequest/mock_evaluator.go` | verified |  |
| grafana | `pkg/registry/apps/annotation/authz_test.go` | verified |  |
| grafana | `pkg/registry/apps/plugins/register.go` | verified |  |
| grafana | `pkg/services/cloudmigration/cloudmigration.go` | verified |  |
| grafana | `pkg/services/publicdashboards/internal/metric/metric.go` | verified |  |
| grafana | `pkg/tests/apis/provisioning/nats/relist/connection_test.go` | verified |  |
| grafana | `pkg/util/xorm/tag.go` | verified |  |
| grafana | `public/app/core/components/OptionsUI/string.tsx` | verified |  |
| grafana | `public/app/features/alerting/unified/components/contact-points/components/GlobalConfigAlert.tsx` | verified |  |
| grafana | `public/app/features/alerting/unified/utils/k8s/errors.ts` | verified |  |
| grafana | `public/app/features/canvas/elements/server/types/terminal.tsx` | verified |  |
| grafana | `public/app/features/commandPalette/useMatches.ts` | verified |  |
| grafana | `public/app/features/templating/formatVariableValue.ts` | verified |  |
| grafana | `public/app/plugins/datasource/grafana-testdata-datasource/ConfigEditor.tsx` | verified |  |
| grafana | `public/app/plugins/datasource/influxdb/query_part_core.ts` | verified |  |
| grafana | `public/app/plugins/panel/dashlist/DashList.tsx` | verified |  |
| grafana | `public/app/plugins/panel/debug/RenderInfoViewer.tsx` | verified |  |
| grafana | `public/app/plugins/panel/text/TextPanelEditor.tsx` | verified |  |
| prysm | `beacon-chain/blockchain/goroutine_count_test.go` | verified |  |
| prysm | `beacon-chain/cache/interfaces.go` | verified |  |
| prysm | `beacon-chain/sync/initial-sync/blocks_queue_test.go` | verified |  |
| prysm | `beacon-chain/sync/validate_blob.go` | verified |  |
| prysm | `config/fieldparams/mainnet.go` | verified |  |
| prysm | `testing/spectest/mainnet/altair__operations__block_header_test.go` | verified |  |
| prysm | `testing/spectest/minimal/capella__fork_transition__transition_test.go` | verified |  |
| prysm | `testing/spectest/minimal/capella__operations__deposit_test.go` | verified |  |
| prysm | `validator/client/beacon-api/genesis.go` | verified |  |
| prysm | `validator/client/beacon-api/test-helpers/electra_beacon_block_test_helpers.go` | verified |  |
