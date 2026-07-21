# Target OSS no-LLM dogfooding audit — continuation 30 (batch 31)

Run: 2026-07-21T05:21:46.005154Z

## Summary

- Files audited: 50
- Verified: 50
- Refuted: 0
- Unverifiable: 0

All 50 sampled files passed no-LLM verification after the tool-side fixes.

## Tool-side fixes (batch 31)

- **Go string concatenation**
  - `_go_string_variables` collects top-level `var`/`const` identifiers declared with `string` or string literals.
  - Per-function `known_strings` also includes parameters whose type is `string`.
  - `+` pairs where either operand is a known string are skipped in `_issues_for_expression`, because Go `+` on strings is concatenation, not integer overflow.
  - Rep: `grafana/pkg/setting/setting.go` `ToAbsUrl`.

- **Go caller-contract bounds assumption from doc comments**
  - `_go_doc_comment_suppresses_bounds` reads the comment immediately preceding a function.
  - If it contains `assumes`/`assumed`, `valid`, and `bounds`, all index bounds issues for that function are suppressed.
  - `_detect_safety_issues` passes the original (non-stripped) source to `_detect_go_safety_issues` so comments are available.
  - Rep: `go/src/cmd/compile/internal/syntax/scanner.go` `tokStrFast`.

## Sample details

| repo | file | status | notes |
|------|------|--------|-------|
| grafana | `public/app/features/alerting/unified/components/rules/state-history/LokiStateHistory.tsx` | verified |  |
| grafana | `pkg/modules/util.go` | verified |  |
| grafana | `public/app/features/panel/components/VizTypePicker/VisualizationSuggestionCard.test.tsx` | verified |  |
| go | `test/fixedbugs/issue47712.go` | verified |  |
| grafana | `public/app/features/alerting/unified/components/rule-editor/query-and-alert-condition/useAdvancedMode.ts` | verified |  |
| grafana | `pkg/setting/setting.go` | verified |  |
| prysm | `beacon-chain/rpc/prysm/v1alpha1/validator/sync_committee_test.go` | verified | No Mumei atoms |
| grafana | `packages/grafana-ui/src/components/Dropdown/ButtonSelect.tsx` | verified |  |
| go | `src/runtime/unsafepoint_test.go` | verified |  |
| prysm | `testing/spectest/shared/gloas/operations/helpers.go` | verified |  |
| grafana | `pkg/services/ngalert/eval/extract_md.go` | verified |  |
| influxdb | `influxdb3_catalog/src/catalog/versions/v2/field/tests.rs` | verified | No Mumei atoms |
| go | `test/fixedbugs/issue21221.go` | verified |  |
| grafana | `packages/grafana-flamegraph/src/FlameGraph/FlameGraph.test.tsx` | verified | No Mumei atoms |
| grafana | `apps/iam/pkg/apis/iam/v0alpha1/createsearchexternalgroupmappings_request_params_object_gen.go` | verified |  |
| grafana | `public/app/features/teams/state/navModel.ts` | verified |  |
| prysm | `testing/spectest/mainnet/phase0__rewards__rewards_test.go` | verified | No Mumei atoms |
| grafana | `public/app/features/explore/utils/decorators.ts` | verified |  |
| go | `src/cmd/compile/internal/syntax/scanner.go` | verified |  |
| grafana | `packages/grafana-ui/src/components/UnitPicker/UnitPicker.tsx` | verified |  |
| go | `src/cmd/go/internal/imports/tags.go` | verified |  |
| grafana | `pkg/registry/apis/provisioning/test.go` | verified |  |
| grafana | `public/app/features/alerting/unified/components/rule-editor/EvaluationGroupQuickPick.test.tsx` | verified |  |
| grafana | `public/app/features/dashboard-scene/scene/PanelNotices.tsx` | verified |  |
| grafana | `pkg/services/authz/zanzana/client.go` | verified |  |
| go | `test/fixedbugs/issue33158.go` | verified |  |
| grafana | `packages/grafana-data/src/transformations/transformers/filterByName.ts` | verified |  |
| go | `src/cmd/compile/internal/ir/op_string.go` | verified |  |
| go | `src/cmd/internal/metadata/main.go` | verified |  |
| grafana | `public/app/features/explore/TraceView/components/types/TTraceTimeline.tsx` | verified |  |
| prysm | `beacon-chain/operations/synccommittee/contribution.go` | verified |  |
| go | `src/cmd/compile/internal/types/sym_test.go` | verified | No Mumei atoms |
| grafana | `pkg/middleware/validate_action_url.go` | verified |  |
| go | `test/fixedbugs/issue23586.go` | verified |  |
| grafana | `apps/provisioning/pkg/repository/github/mock_client.go` | verified |  |
| go | `src/cmd/compile/internal/importer/testdata/issue15920.go` | verified |  |
| grafana | `apps/provisioning/pkg/repository/reader_writer_mock.go` | verified |  |
| go | `test/fixedbugs/issue31252.dir/b.go` | verified |  |
| go | `src/os/error_errno.go` | verified |  |
| influxdb | `core/iox_http_util/src/uri.rs` | verified |  |
| prysm | `testing/spectest/mainnet/altair__light_client__single_merkle_proof_test.go` | verified | No Mumei atoms |
| prysm | `cmd/validator/wallet/recover_test.go` | verified |  |
| go | `test/typeparam/issue50419.go` | verified |  |
| go | `test/fixedbugs/issue24173.go` | verified |  |
| grafana | `public/app/features/alerting/unified/insights/mimir/InvalidConfig.tsx` | verified |  |
| go | `src/cmd/internal/objabi/path_test.go` | verified | No Mumei atoms |
| prysm | `beacon-chain/core/transition/transition.go` | verified |  |
| go | `src/cmd/compile/internal/ssagen/simdAMD64intrinsics.go` | verified |  |
| go | `src/net/mail/example_test.go` | verified | No Mumei atoms |
| grafana | `public/app/core/services/__mocks__/backend_srv.ts` | verified |  |
