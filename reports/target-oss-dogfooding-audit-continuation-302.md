# Target OSS no-LLM dogfooding audit — continuation 302 (batch 303)

Run: 2026-07-22T18:20:32.987408+00:00

## Summary

- Files audited: 50
- Verified: 50
- Refuted: 0
- Unverifiable: 0

All sampled files passed no-LLM verification; no new tool-side fixes were required.

## Sample details

| repo | file | status | notes |
|------|------|--------|-------|
| go | `src/archive/tar/reader_test.go` | verified |  |
| go | `src/cmd/link/internal/ld/data.go` | verified |  |
| go | `src/crypto/internal/fips140/edwards25519/scalar_test.go` | verified |  |
| go | `src/crypto/tls/common_string.go` | verified |  |
| go | `src/debug/elf/file_test.go` | verified |  |
| go | `src/go/types/typestring_test.go` | verified |  |
| go | `src/net/udpsock_plan9.go` | verified |  |
| go | `src/runtime/example_test.go` | verified |  |
| go | `src/runtime/iface_test.go` | verified |  |
| go | `src/runtime/pprof/proto_darwin.go` | verified |  |
| go | `test/codegen/issue70409.go` | verified |  |
| go | `test/fixedbugs/bug440_64.go` | verified |  |
| go | `test/fixedbugs/issue71184.go` | verified |  |
| go | `test/method6.go` | verified |  |
| grafana | `apps/alerting/notifications/pkg/apis/alertingnotifications/v0alpha1/inhibitionrule_ext.go` | verified |  |
| grafana | `apps/iam/pkg/apis/iam/v0alpha1/user_object_gen.go` | verified |  |
| grafana | `packages/grafana-alerting/src/grafana/contactPoints/utils.ts` | verified |  |
| grafana | `packages/grafana-data/src/field/displayProcessor.ts` | verified |  |
| grafana | `packages/grafana-ui/src/components/Combobox/useOptions.ts` | verified |  |
| grafana | `packages/grafana-ui/src/components/EmptyState/GrotNotFound/GrotNotFound.tsx` | verified |  |
| grafana | `packages/grafana-ui/src/components/Table/TableNG/__mocks__/uwrap.ts` | verified |  |
| grafana | `pkg/api/plugin_dashboards.go` | verified |  |
| grafana | `pkg/registry/apis/secret/secretkeeper/secretkeeper.go` | verified |  |
| grafana | `pkg/registry/apps/alerting/notifications/register.go` | verified |  |
| grafana | `pkg/server/health.go` | verified |  |
| grafana | `pkg/services/authn/authnimpl/sync/rbac_sync_test.go` | verified |  |
| grafana | `pkg/services/authz/rbac/store/folder_store.go` | verified |  |
| grafana | `pkg/services/live/pipeline/frame_output_local_subscribers.go` | verified |  |
| grafana | `pkg/services/ngalert/models/fingerprint.go` | verified |  |
| grafana | `pkg/services/ngalert/provisioning/provisioning_store_mock.go` | verified |  |
| grafana | `pkg/services/queryhistory/queryhistory_delete_stale_test.go` | verified |  |
| grafana | `pkg/services/sqlstore/migrator/mysql_dialect_test.go` | verified |  |
| grafana | `public/app/features/alerting/unified/components/rule-viewer/tabs/version-history/ConfirmVersionRestoreModal.tsx` | verified |  |
| grafana | `public/app/features/dashboard-scene/mutation-api/commands/removePanel.ts` | verified |  |
| grafana | `public/app/features/dashboard/components/ShareModal/SharePublicDashboard/ConfigPublicDashboard/Configuration.tsx` | verified |  |
| grafana | `public/app/features/explore/TraceView/components/TraceTimelineViewer/SpanDetail/jsonMarkup.js` | verified |  |
| grafana | `public/app/features/logs/components/panel/LogTableControls.tsx` | verified |  |
| grafana | `public/app/plugins/datasource/graphite/components/FunctionEditorControls.tsx` | verified |  |
| grafana | `public/app/plugins/datasource/loki/LiveStreams.ts` | verified |  |
| grafana | `public/app/plugins/datasource/loki/webpack.config.ts` | verified |  |
| prysm | `beacon-chain/cache/proposer_preferences_test.go` | verified |  |
| prysm | `beacon-chain/core/epoch/precompute/new_test.go` | verified |  |
| prysm | `beacon-chain/rpc/eth/beacon/metrics.go` | verified |  |
| prysm | `beacon-chain/rpc/prysm/v1alpha1/validator/unblinder.go` | verified |  |
| prysm | `beacon-chain/verification/interface.go` | verified |  |
| prysm | `config/params/config_test.go` | verified |  |
| prysm | `consensus-types/blocks/log.go` | verified |  |
| prysm | `testing/spectest/mainnet/capella__epoch_processing__participation_flag_updates_test.go` | verified |  |
| prysm | `testing/spectest/shared/altair/operations/block_header.go` | verified |  |
| prysm | `testing/spectest/shared/bellatrix/sanity/block_processing.go` | verified |  |
