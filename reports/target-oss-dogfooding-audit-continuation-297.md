# Target OSS no-LLM dogfooding audit — continuation 297 (batch 298)

Run: 2026-07-22T18:01:16.123520+00:00

## Summary

- Files audited: 50
- Verified: 50
- Refuted: 0
- Unverifiable: 0

All sampled files passed no-LLM verification; no new tool-side fixes were required.

## Sample details

| repo | file | status | notes |
|------|------|--------|-------|
| go | `src/cmd/cgo/internal/test/issue29563.go` | verified |  |
| go | `src/cmd/compile/internal/liveness/arg.go` | verified |  |
| go | `src/cmd/compile/internal/ssa/copyelim.go` | verified |  |
| go | `src/cmd/compile/internal/ssagen/simdARM64intrinsics.go` | verified |  |
| go | `src/crypto/elliptic/elliptic_test.go` | verified |  |
| go | `src/crypto/internal/fips140/mldsa/field.go` | verified |  |
| go | `src/encoding/json/tagkey_test.go` | verified |  |
| go | `src/math/gamma.go` | verified |  |
| go | `src/mime/type_unix_test.go` | verified |  |
| go | `src/net/http/internal/httpsfv/httpsfv.go` | verified |  |
| go | `src/net/nss.go` | verified |  |
| go | `src/simd/archsimd/internal/simd_test/unary_128_test.go` | verified |  |
| go | `test/fixedbugs/bug348.go` | verified |  |
| go | `test/fixedbugs/issue29264.go` | verified |  |
| grafana | `packages/grafana-api-clients/src/clients/rtkq/correlations/v0alpha1/baseAPI.ts` | verified |  |
| grafana | `packages/grafana-flamegraph/.storybook/main.ts` | verified |  |
| grafana | `packages/grafana-ui/src/components/DateTimePickers/TimeRangePicker/TimePickerTitle.tsx` | verified |  |
| grafana | `packages/grafana-ui/src/components/Forms/commonStyles.ts` | verified |  |
| grafana | `packages/grafana-ui/src/themes/GlobalStyles/card.ts` | verified |  |
| grafana | `pkg/generated/clientset/versioned/typed/service/v0alpha1/externalname.go` | verified |  |
| grafana | `pkg/registry/apis/iam/datasourcek8s/legacy_test.go` | verified |  |
| grafana | `pkg/registry/apis/provisioning/resources/authorizer.go` | verified |  |
| grafana | `pkg/server/test_env.go` | verified |  |
| grafana | `pkg/services/apiserver/builder/common.go` | verified |  |
| grafana | `pkg/services/ngalert/state/persister_async_rule.go` | verified |  |
| grafana | `pkg/services/publicdashboards/internal/models/errors.go` | verified |  |
| grafana | `pkg/storage/secret/encryption/data_key_model.go` | verified |  |
| grafana | `pkg/storage/unified/search/builders/document_test.go` | verified |  |
| grafana | `pkg/storage/unified/search/lock_cdk_backend_test.go` | verified |  |
| grafana | `public/app/core/components/NestedFolderPicker/LazyFolderPicker.tsx` | verified |  |
| grafana | `public/app/core/components/ThemeSelector/ThemeSelectorDrawer.tsx` | verified |  |
| grafana | `public/app/features/alerting/unified/RuleViewer.tsx` | verified |  |
| grafana | `public/app/features/alerting/unified/components/common/DetailText.tsx` | verified |  |
| grafana | `public/app/features/alerting/unified/components/rule-editor/GroupAndNamespaceFields.tsx` | verified |  |
| grafana | `public/app/features/alerting/unified/components/rule-viewer/ContactPointLink.tsx` | verified |  |
| grafana | `public/app/features/alerting/unified/enterprise-components/AI/AIGenTemplateButton/addAITemplateButton.ts` | verified |  |
| grafana | `public/app/features/canvas/elements/button.tsx` | verified |  |
| grafana | `public/app/features/live/centrifuge/channel.ts` | verified |  |
| grafana | `public/app/plugins/datasource/loki/querybuilder/state.ts` | verified |  |
| prysm | `beacon-chain/monitor/process_exit_test.go` | verified |  |
| prysm | `beacon-chain/p2p/broadcaster_test.go` | verified |  |
| prysm | `beacon-chain/p2p/watch_peers.go` | verified |  |
| prysm | `beacon-chain/state/state-native/custom-types/block_roots.go` | verified |  |
| prysm | `beacon-chain/sync/initial-sync/blocks_fetcher_sidecar.go` | verified |  |
| prysm | `beacon-chain/sync/validate_payload_attestation.go` | verified |  |
| prysm | `cmd/beacon-chain/das/options.go` | verified |  |
| prysm | `consensus-types/blocks/rodatacolumn.go` | verified |  |
| prysm | `crypto/bls/error.go` | verified |  |
| prysm | `testing/spectest/minimal/electra__operations__withdrawals_test.go` | verified |  |
| prysm | `testing/spectest/minimal/gloas__epoch_processing__historical_summaries_update_test.go` | verified |  |
