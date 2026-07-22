# Target OSS no-LLM dogfooding audit — continuation 285 (batch 286)

Run: 2026-07-22T17:06:08.027389+00:00

## Summary

- Files audited: 50
- Verified: 50
- Refuted: 0
- Unverifiable: 0

All sampled files passed no-LLM verification; no new tool-side fixes were required.

## Sample details

| repo | file | status | notes |
|------|------|--------|-------|
| go | `src/cmd/compile/internal/ssa/debug.go` | verified |  |
| go | `src/cmd/compile/internal/test/issue50182_test.go` | verified |  |
| go | `src/cmd/internal/obj/arm64/doc.go` | verified |  |
| go | `src/cmd/link/internal/amd64/obj.go` | verified |  |
| go | `src/hash/maphash/hasher.go` | verified |  |
| go | `src/internal/cpu/cpu_ppc64x_linux.go` | verified |  |
| go | `src/internal/poll/errno_unix.go` | verified |  |
| go | `src/internal/trace/raw/textreader.go` | verified |  |
| go | `src/math/big/rat_test.go` | verified |  |
| go | `src/net/url/encoding_table.go` | verified |  |
| go | `src/os/dirent_js.go` | verified |  |
| go | `src/syscall/exec_freebsd_test.go` | verified |  |
| go | `test/fixedbugs/bug404.dir/two.go` | verified |  |
| go | `test/fixedbugs/issue15572.dir/a.go` | verified |  |
| go | `test/reflectmethod2.go` | verified |  |
| go | `test/typeparam/issue48318.go` | verified |  |
| go | `test/typeparam/issue51250a.go` | verified |  |
| grafana | `apps/alerting/rules/pkg/app/validation/builder_test.go` | verified |  |
| grafana | `apps/provisioning/pkg/repository/mock_webhook_config.go` | verified |  |
| grafana | `packages/grafana-ui/src/utils/nodeGraph.ts` | verified |  |
| grafana | `pkg/services/apiserver/client/client_mock.go` | verified |  |
| grafana | `pkg/services/correlations/conversions.go` | verified |  |
| grafana | `pkg/services/ngalert/state/historian/model/rule_test.go` | verified |  |
| grafana | `pkg/services/notifications/testing.go` | verified |  |
| grafana | `pkg/services/ssosettings/strategies/oauth_strategy_test.go` | verified |  |
| grafana | `pkg/storage/unified/resource/notifier_nats_test.go` | verified |  |
| grafana | `pkg/storage/unified/sql/sqltemplate/args_test.go` | verified |  |
| grafana | `pkg/tests/api/folders/api_folder_test.go` | verified |  |
| grafana | `pkg/tests/apis/provisioning/quota/foldermetadata/sync_quota_metadata_test.go` | verified |  |
| grafana | `public/app/core/utils/colors.ts` | verified |  |
| grafana | `public/app/features/alerting/unified/components/export/GrafanaPoliciesExporter.tsx` | verified |  |
| grafana | `public/app/features/alerting/unified/withPageErrorBoundary.tsx` | verified |  |
| grafana | `public/app/features/correlations/Forms/utils.ts` | verified |  |
| grafana | `public/app/features/explore/hooks/useKeyboardShortcuts.ts` | verified |  |
| grafana | `public/app/features/plugins/admin/components/PluginSubtitle.tsx` | verified |  |
| grafana | `public/app/features/plugins/extensions/types.ts` | verified |  |
| grafana | `public/app/features/plugins/extensions/validateExtensionPoint.ts` | verified |  |
| grafana | `public/app/features/query/components/QueryEditorRows.tsx` | verified |  |
| grafana | `public/app/plugins/datasource/cloudwatch/language/cloudwatch-sql/language.ts` | verified |  |
| grafana | `public/app/plugins/datasource/dashboard/module.ts` | verified |  |
| prysm | `beacon-chain/db/kv/state_diff_cache.go` | verified |  |
| prysm | `beacon-chain/p2p/pubsub_test.go` | verified |  |
| prysm | `beacon-chain/p2p/testing/log.go` | verified |  |
| prysm | `beacon-chain/rpc/core/log.go` | verified |  |
| prysm | `beacon-chain/rpc/eth/helpers/sync_test.go` | verified |  |
| prysm | `cmd/validator/accounts/import.go` | verified |  |
| prysm | `testing/spectest/mainnet/gloas__epoch_processing__effective_balance_updates_test.go` | verified |  |
| prysm | `testing/spectest/shared/deneb/operations/sync_committee.go` | verified |  |
| prysm | `validator/client/beacon-api/payload_attestation.go` | verified |  |
| prysm | `validator/db/kv/deprecated_attester_protection.go` | verified |  |
