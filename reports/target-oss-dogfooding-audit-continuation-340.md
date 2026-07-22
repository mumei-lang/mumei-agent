# Target OSS no-LLM dogfooding audit — continuation 340 (batch 341)

Run: 2026-07-22T20:45:41.071403+00:00

## Summary

- Files audited: 50
- Verified: 50
- Refuted: 0
- Unverifiable: 0

All sampled files passed no-LLM verification; no new tool-side fixes were required.

## Sample details

| repo | file | status | notes |
|------|------|--------|-------|
| go | `src/cmd/go/internal/workcmd/work.go` | verified |  |
| go | `src/crypto/internal/fips140/mldsa/cast.go` | verified |  |
| go | `src/internal/runtime/wasitest/nonblock_test.go` | verified |  |
| go | `src/log/log_test.go` | verified |  |
| go | `src/os/types.go` | verified |  |
| go | `src/runtime/sys_ppc64x.go` | verified |  |
| go | `src/strings/iter.go` | verified |  |
| go | `src/syscall/zsysnum_netbsd_amd64.go` | verified |  |
| go | `test/escape2n.go` | verified |  |
| go | `test/fixedbugs/bug039.go` | verified |  |
| go | `test/fixedbugs/issue14164.dir/a.go` | verified |  |
| go | `test/fixedbugs/issue8961.go` | verified |  |
| go | `test/import1.go` | verified |  |
| go | `test/interface/fail.go` | verified |  |
| go | `test/typeparam/issue47723.go` | verified |  |
| go | `test/typeparam/issue48030.go` | verified |  |
| grafana | `apps/alerting/notifications/pkg/apis/alertingnotifications/v0alpha1/templategroup_client_gen.go` | verified |  |
| grafana | `apps/iam/pkg/apis/iam/v0alpha1/resourcepermission_codec_gen.go` | verified |  |
| grafana | `packages/grafana-data/src/field/fieldState.ts` | verified |  |
| grafana | `packages/grafana-runtime/src/services/pluginSettings/updateAppPluginSettings.ts` | verified |  |
| grafana | `packages/grafana-runtime/src/utils/publicDashboardQueryHandler.ts` | verified |  |
| grafana | `packages/grafana-ui/.storybook/storybookTheme.ts` | verified |  |
| grafana | `packages/grafana-ui/src/components/Toggletip/types.ts` | verified |  |
| grafana | `pkg/login/social/socialtest/social_connector_mock.go` | verified |  |
| grafana | `pkg/plugins/codegen/pfs/errors.go` | verified |  |
| grafana | `pkg/registry/apis/provisioning/jobs/sync/worker.go` | verified |  |
| grafana | `pkg/services/authz/zanzana/client/client.go` | verified |  |
| grafana | `pkg/services/ngalert/api/api_convert_prometheus_test.go` | verified |  |
| grafana | `pkg/services/ngalert/api/lotex_am.go` | verified |  |
| grafana | `pkg/services/ngalert/notifier/inhibition_rules/service_test.go` | verified |  |
| grafana | `pkg/storage/unified/apistore/store.go` | verified |  |
| grafana | `pkg/tests/apis/provisioning/nats/relist/relist_test.go` | verified |  |
| grafana | `public/app/features/alerting/unified/components/rules/RuleListStateView.tsx` | verified |  |
| grafana | `public/app/features/alerting/unified/types/preview.ts` | verified |  |
| grafana | `public/app/features/correlations/__mocks__/useCorrelations.mocks.ts` | verified |  |
| grafana | `public/app/features/dashboard-scene/panel-edit/PanelEditorRenderer.tsx` | verified |  |
| grafana | `public/app/features/dashboard-scene/scene/new-toolbar/actions/ShareDashboardButton.tsx` | verified |  |
| grafana | `public/app/plugins/datasource/cloudwatch/guards.ts` | verified |  |
| grafana | `public/app/plugins/panel/logstable/fieldSelector/LogsTableFields.tsx` | verified |  |
| grafana | `scripts/webpack/postcss.config.js` | verified |  |
| prysm | `api/constants.go` | verified |  |
| prysm | `beacon-chain/core/epoch/precompute/reward_penalty_test.go` | verified |  |
| prysm | `beacon-chain/operations/attestations/kv/block_test.go` | verified |  |
| prysm | `beacon-chain/p2p/fork_test.go` | verified |  |
| prysm | `beacon-chain/rpc/eth/beacon/handlers_validators_test.go` | verified |  |
| prysm | `beacon-chain/state/state-native/getters_misc.go` | verified |  |
| prysm | `testing/spectest/mainnet/fulu__epoch_processing__proposer_lookahead_test.go` | verified |  |
| prysm | `testing/spectest/minimal/fulu__merkle_proof__merkle_proof_test.go` | verified |  |
| prysm | `testing/spectest/shared/deneb/operations/attestation.go` | verified |  |
| prysm | `validator/slashing-protection-history/export_test.go` | verified |  |
