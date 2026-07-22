# Target OSS no-LLM dogfooding audit — continuation 314 (batch 315)

Run: 2026-07-22T18:56:51.655377+00:00

## Summary

- Files audited: 50
- Verified: 50
- Refuted: 0
- Unverifiable: 0

All sampled files passed no-LLM verification; no new tool-side fixes were required.

## Sample details

| repo | file | status | notes |
|------|------|--------|-------|
| go | `src/cmd/asm/internal/asm/line_test.go` | verified |  |
| go | `src/cmd/internal/osinfo/os_js.go` | verified |  |
| go | `src/cmd/internal/sys/arch.go` | verified |  |
| go | `src/crypto/internal/cryptotest/methods.go` | verified |  |
| go | `src/crypto/rand/example_test.go` | verified |  |
| go | `src/encoding/json/jsontext/value_test.go` | verified |  |
| go | `src/internal/poll/sockopt_linux.go` | verified |  |
| go | `src/internal/runtime/math/math.go` | verified |  |
| go | `src/math/big/ratmarsh_test.go` | verified |  |
| go | `src/net/sockoptip4_windows.go` | verified |  |
| go | `src/runtime/runtime.go` | verified |  |
| go | `test/abi/idata.go` | verified |  |
| go | `test/fixedbugs/bug188.go` | verified |  |
| go | `test/fixedbugs/issue73888.go` | verified |  |
| go | `test/fixedbugs/issue79236.go` | verified |  |
| go | `test/typeparam/index.go` | verified |  |
| go | `test/typeparam/mdempsky/13.go` | verified |  |
| grafana | `apps/example/pkg/apis/example/v1alpha1/client_gen.go` | verified |  |
| grafana | `apps/iam/pkg/apis/iam/v0alpha1/rolebinding_codec_gen.go` | verified |  |
| grafana | `apps/provisioning/pkg/generated/applyconfiguration/provisioning/v0alpha1/fixfoldermetadatajoboptions.go` | verified |  |
| grafana | `packages/grafana-ui/src/components/DateTimePickers/WeekStartPicker.tsx` | verified |  |
| grafana | `packages/grafana-ui/src/components/Table/TableNG/Cells/renderers.tsx` | verified |  |
| grafana | `packages/grafana-ui/src/components/Table/TableNG/refactored/render-hooks.tsx` | verified |  |
| grafana | `packages/grafana-ui/src/components/Typeahead/TypeaheadInfo.tsx` | verified |  |
| grafana | `pkg/api/user_token.go` | verified |  |
| grafana | `pkg/extensions/enterprise_imports.go` | verified |  |
| grafana | `pkg/modules/tracing/listener.go` | verified |  |
| grafana | `pkg/registry/apis/iam/legacy/service_account_token.go` | verified |  |
| grafana | `pkg/registry/apis/secret/service/metrics/metrics.go` | verified |  |
| grafana | `pkg/services/ldap/ldap_private_test.go` | verified |  |
| grafana | `pkg/services/ngalert/notifier/legacy_storage/v1/common.go` | verified |  |
| grafana | `pkg/services/provisioning/datasources/types_test.go` | verified |  |
| grafana | `pkg/storage/legacysql/db.go` | verified |  |
| grafana | `pkg/storage/unified/resource/search_field.go` | verified |  |
| grafana | `pkg/storage/unified/search/embed/embedder/bedrock/embed_dense.go` | verified |  |
| grafana | `public/app/core/components/AppChrome/NavToolbar/NavToolbarSeparator.tsx` | verified |  |
| grafana | `public/app/features/alerting/unified/home/Insights.tsx` | verified |  |
| grafana | `public/app/features/plugins/admin/components/GetStartedWithPlugin/GetStartedWithPlugin.tsx` | verified |  |
| grafana | `public/app/features/transformers/FilterByValueTransformer/FilterByValueFilterEditor.tsx` | verified |  |
| grafana | `public/test/mocks/assistant.ts` | verified |  |
| prysm | `beacon-chain/blockchain/process_attestation.go` | verified |  |
| prysm | `beacon-chain/sync/rpc_status_test.go` | verified |  |
| prysm | `beacon-chain/sync/validate_beacon_blocks_test.go` | verified |  |
| prysm | `testing/spectest/mainnet/bellatrix__fork_helper__upgrade_to_altair_test.go` | verified |  |
| prysm | `testing/spectest/mainnet/bellatrix__operations__proposer_slashing_test.go` | verified |  |
| prysm | `testing/spectest/mainnet/gloas__operations__payload_attestation_test.go` | verified |  |
| prysm | `testing/spectest/minimal/bellatrix__operations__block_header_test.go` | verified |  |
| prysm | `testing/spectest/shared/bellatrix/epoch_processing/effective_balance_updates.go` | verified |  |
| prysm | `validator/client/sync_committee.go` | verified |  |
| prysm | `validator/keymanager/derived/eip_test.go` | verified |  |
