# Target OSS no-LLM dogfooding audit — continuation 333 (batch 334)

Run: 2026-07-22T20:13:55.891492+00:00

## Summary

- Files audited: 50
- Verified: 50
- Refuted: 0
- Unverifiable: 0

All sampled files passed no-LLM verification; no new tool-side fixes were required.

## Sample details

| repo | file | status | notes |
|------|------|--------|-------|
| go | `src/cmd/distpack/test.go` | verified |  |
| go | `src/cmd/internal/quoted/quoted.go` | verified |  |
| go | `src/cmd/internal/robustio/robustio_flaky.go` | verified |  |
| go | `src/crypto/internal/boring/notboring.go` | verified |  |
| go | `src/encoding/json/v2_tagkey_test.go` | verified |  |
| go | `src/internal/abi/abi_loong64.go` | verified |  |
| go | `src/internal/cpu/cpu_mips.go` | verified |  |
| go | `src/internal/trace/tracev2/events.go` | verified |  |
| go | `test/alias2.go` | verified |  |
| go | `test/fixedbugs/bug413.go` | verified |  |
| go | `test/fixedbugs/issue29312.go` | verified |  |
| go | `test/shift2.go` | verified |  |
| go | `test/typeparam/issue47272.go` | verified |  |
| grafana | `apps/advisor/pkg/apis/advisor/v0alpha1/checktype_codec_gen.go` | verified |  |
| grafana | `apps/dashboard/pkg/migration/conversion/v1_to_v2alpha1_test.go` | verified |  |
| grafana | `apps/plugins/pkg/app/install/registrar.go` | verified |  |
| grafana | `packages/grafana-data/src/utils/series.ts` | verified |  |
| grafana | `pkg/api/dtos/annotations.go` | verified |  |
| grafana | `pkg/apimachinery/errutil/errors_test.go` | verified |  |
| grafana | `pkg/codegen/generators/ts_generator.go` | verified |  |
| grafana | `pkg/infra/log/handlers.go` | verified |  |
| grafana | `pkg/registry/apis/iam/team/rest_remove_member.go` | verified |  |
| grafana | `pkg/services/datasources/accesscontrol.go` | verified |  |
| grafana | `pkg/services/live/managedstream/cache.go` | verified |  |
| grafana | `pkg/services/ngalert/schedule/recording_rule.go` | verified |  |
| grafana | `pkg/storage/legacysql/dualwrite/dualwriter_list_pagination_test.go` | verified |  |
| grafana | `pkg/storage/unified/resource/server_test.go` | verified |  |
| grafana | `pkg/tests/apis/alerting/rules/compat/recordingrule_test.go` | verified |  |
| grafana | `pkg/tsdb/cloudwatch/models/resources/resource_request.go` | verified |  |
| grafana | `public/app/core/components/AppChrome/ExtensionSidebar/ExtensionSidebar.tsx` | verified |  |
| grafana | `public/app/features/alerting/unified/api/incidentsApi.ts` | verified |  |
| grafana | `public/app/features/alerting/unified/triage/scene/TriageScene.tsx` | verified |  |
| grafana | `public/app/features/auth-config/components/ServerDiscoveryModal.tsx` | verified |  |
| grafana | `public/app/features/dashboard/utils/getRefreshFromUrl.ts` | verified |  |
| grafana | `public/app/features/explore/ContentOutline/ContentOutlineContext.tsx` | verified |  |
| grafana | `public/app/features/migrate-to-cloud/onprem/MigrationSummary.tsx` | verified |  |
| grafana | `public/app/features/provisioning/Connection/ConnectionListItem.tsx` | verified |  |
| grafana | `public/app/plugins/datasource/azuremonitor/mocks/errors.ts` | verified |  |
| grafana | `public/app/plugins/datasource/cloudwatch/language/monarch/types.ts` | verified |  |
| grafana | `public/test/mocks/react-inlinesvg.tsx` | verified |  |
| prysm | `api/client/builder/client.go` | verified |  |
| prysm | `beacon-chain/cache/checkpoint_state.go` | verified |  |
| prysm | `beacon-chain/forkchoice/doubly-linked-tree/store_test.go` | verified |  |
| prysm | `beacon-chain/state/state-native/setters_randao.go` | verified |  |
| prysm | `beacon-chain/sync/late_payload_request.go` | verified |  |
| prysm | `config/proposer/loader/log.go` | verified |  |
| prysm | `testing/spectest/mainnet/fulu__operations__block_header_test.go` | verified |  |
| prysm | `testing/spectest/mainnet/gloas__fork_transition__transition_test.go` | verified |  |
| prysm | `time/mclock/mclock.go` | verified |  |
| prysm | `validator/db/kv/migration_optimal_attester_protection.go` | verified |  |
