# Target OSS no-LLM dogfooding audit — continuation 299 (batch 300)

Run: 2026-07-22T18:07:07.359430+00:00

## Summary

- Files audited: 50
- Verified: 50
- Refuted: 0
- Unverifiable: 0

All sampled files passed no-LLM verification; no new tool-side fixes were required.

## Sample details

| repo | file | status | notes |
|------|------|--------|-------|
| go | `src/cmd/compile/doc.go` | verified |  |
| go | `src/cmd/compile/internal/ssa/_gen/LOONG64Ops.go` | verified |  |
| go | `src/cmd/link/internal/ld/dwarf_test.go` | verified |  |
| go | `src/crypto/internal/fips140/nistec/p384.go` | verified |  |
| go | `src/go/types/tuple.go` | verified |  |
| go | `src/runtime/export_debuglog_test.go` | verified |  |
| go | `src/time/export_android_test.go` | verified |  |
| go | `test/fixedbugs/bug369.dir/pkg.go` | verified |  |
| go | `test/fixedbugs/bug425.go` | verified |  |
| go | `test/fixedbugs/issue54348.go` | verified |  |
| go | `test/fixedbugs/issue57309.go` | verified |  |
| go | `test/fixedbugs/issue62469.go` | verified |  |
| go | `test/fixedbugs/issue64826.go` | verified |  |
| go | `test/typeparam/issue50121b.dir/a.go` | verified |  |
| go | `test/typeparam/mdempsky/20.go` | verified |  |
| grafana | `apps/example/pkg/apis/example/v0alpha1/constants.go` | verified |  |
| grafana | `apps/provisioning/pkg/jobs/mutator.go` | verified |  |
| grafana | `apps/provisioning/pkg/repository/git/mutator.go` | verified |  |
| grafana | `apps/provisioning/pkg/repository/github/impl_test.go` | verified |  |
| grafana | `jest.config.codeowner.js` | verified |  |
| grafana | `packages/grafana-alerting/src/grafana/api/util.ts` | verified |  |
| grafana | `packages/grafana-i18n/src/internal/index.ts` | verified |  |
| grafana | `packages/grafana-sql/src/index.ts` | verified |  |
| grafana | `pkg/components/dashdiffs/formatter_json.go` | verified |  |
| grafana | `pkg/plugins/backendplugin/chunked/accumulator.go` | verified |  |
| grafana | `pkg/services/accesscontrol/resourcepermissions/store_test.go` | verified |  |
| grafana | `pkg/services/auth/authimpl/external_session_store.go` | verified |  |
| grafana | `pkg/services/authn/authnimpl/sync/user_sync.go` | verified |  |
| grafana | `pkg/services/org/orgimpl/org.go` | verified |  |
| grafana | `pkg/tsdb/azuremonitor/time/azuremonitor-time.go` | verified |  |
| grafana | `public/app/core/components/FormPrompt/Prompt.tsx` | verified |  |
| grafana | `public/app/core/components/OptionsUI/fieldColor.tsx` | verified |  |
| grafana | `public/app/features/alerting/unified/components/contact-points/TemplatesPage.tsx` | verified |  |
| grafana | `public/app/features/alerting/unified/components/rules/RuleDetailsExpression.tsx` | verified |  |
| grafana | `public/app/features/alerting/unified/rule-list/RuleList.v1.tsx` | verified |  |
| grafana | `public/app/features/dashboard-scene/scene/DashboardSceneUrlSync.ts` | verified |  |
| grafana | `public/app/features/dashboard-scene/sharing/ShareButton/share-externally/ShareConfiguration.tsx` | verified |  |
| grafana | `public/app/features/variables/query/QueryVariableRefreshSelect.tsx` | verified |  |
| grafana | `public/app/features/variables/state/transactionReducer.ts` | verified |  |
| grafana | `public/app/plugins/datasource/dashboard/types.ts` | verified |  |
| prysm | `async/every.go` | verified |  |
| prysm | `beacon-chain/db/restore.go` | verified |  |
| prysm | `beacon-chain/light-client/helpers.go` | verified |  |
| prysm | `cmd/client-stats/main.go` | verified |  |
| prysm | `container/doubly-linked-list/list_test.go` | verified |  |
| prysm | `testing/spectest/mainnet/altair__sanity__blocks_test.go` | verified |  |
| prysm | `testing/spectest/minimal/deneb__operations__attestation_test.go` | verified |  |
| prysm | `validator/db/filesystem/graffiti.go` | verified |  |
| prysm | `validator/db/kv/attester_protection_test.go` | verified |  |
| prysm | `validator/db/kv/prune_attester_protection_test.go` | verified |  |
