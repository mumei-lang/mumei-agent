# 外部 OSS ドッグフーディング監査継続レポート（第 14 弾 / batch 15）

- 実施日: 2026-07-24
- 監査ツール: mumei-agent (`develop`, PR #404 マージ後 + batch 15 対応中)
- LLM モデル: 未使用（`LLM_API_KEY=` no-LLM 決定論的スクリーニング）
- 出力ディレクトリ: `/home/ubuntu/repos/mumei-agent/reports/dogfood_continue_15/`

## 結果サマリー

- verified: 50 件
- refuted: 0 件
- unverifiable: 0 件

## 修正対応済みのツール限界

- Solidity `require` / `assert` による非ゼロガード認識:
  - `SafeMath.sol` の `div` / `mod` で `require(b > 0, ...)` を考慮し、0 除算誤検出を抑制。
- Solidity `if (x == 0) return/revert;` による早期リターン非ゼロガード認識:
  - `tryDiv` / `tryMod` 等の `b == 0` 早期リターンを考慮。
- Go コンパイラテスト（`// errorcheck`, `// runoutput`, `// compiledir`）のスクリーニング対象からの除外:
  - `go/test/fixedbugs/` 等のコンパイラドライバテストを safety audit 対象から除外。

## 全ファイル一覧

| リポジトリ | ファイル | 言語 | ステータス |
|---|---|---|---|
| uniswap-contracts | `lib/oz-v4.7.0/contracts/mocks/EnumerableMapMock.sol` | solidity | verified |
| grafana | `public/app/plugins/datasource/prometheus/configuration/ConfigEditor.tsx` | typescript | verified |
| prysm | `consensus-types/hdiff/log.go` | go | verified |
| uniswap-contracts | `src/briefcase/protocols/v4-hooks-public/aggregator-hooks/implementations/Slipstream/interfaces/IQuoterV2.sol` | solidity | verified |
| influxdb | `core/client_util/src/tower.rs` | rust | verified |
| influxdb | `core/parquet_file/src/serialize.rs` | rust | verified |
| go | `src/cmd/go/internal/list/list.go` | go | verified |
| grafana | `apps/dashvalidator/pkg/cache/cache_test.go` | go | verified |
| grafana | `public/app/plugins/panel/bargauge/presets.ts` | typescript | verified |
| go | `src/crypto/internal/fips140test/sshkdf_test.go` | go | verified |
| uniswap-contracts | `script/smoke/native-is-erc20/V2SmokeNativeIsERC20.s.sol` | solidity | verified |
| uniswap-contracts | `src/briefcase/protocols/lib-external/oz-v3.4-solc-0.7/contracts/token/ERC721/IERC721Metadata.sol` | solidity | verified |
| grafana | `public/app/features/dashboard-scene/utils/utils.ts` | typescript | verified |
| grafana | `public/app/features/dashboard-scene/panel-edit/PanelEditNext/QueryEditor/hooks/useQueryEditorUIToggles.ts` | typescript | verified |
| go | `src/math/copysign.go` | go | verified |
| influxdb | `core/metric/src/metric.rs` | rust | verified |
| go | `src/internal/strconv/math_test.go` | go | verified |
| uniswap-contracts | `script/cli/src/screens/home.rs` | rust | verified |
| go | `src/math/dim.go` | go | verified |
| grafana | `public/app/plugins/datasource/loki/language_utils.test.ts` | typescript | verified |
| grafana | `public/app/features/dashboard-scene/settings/variables/DashboardFiltersSet.tsx` | typescript | verified |
| uniswap-contracts | `lib/oz-v4.7.0/contracts/mocks/ERC721PausableMock.sol` | solidity | verified |
| grafana | `pkg/registry/fieldselectors/selectable_fields_utils_test.go` | go | verified |
| prysm | `beacon-chain/core/electra/churn_test.go` | go | verified |
| uniswap-contracts | `lib/oz-v4.7.0/contracts/interfaces/IERC3156FlashBorrower.sol` | solidity | verified |
| influxdb | `core/parquet_file/src/chunk.rs` | rust | verified |
| go | `src/cmd/internal/obj/dwarf.go` | go | verified |
| prysm | `validator/accounts/accounts_delete.go` | go | verified |
| influxdb | `influxdb3_catalog/src/format/feature_level.rs` | rust | verified |
| go | `src/crypto/subtle/constant_time_test.go` | go | verified |
| uniswap-contracts | `lib/oz-v4.7.0/contracts/mocks/MulticallTest.sol` | solidity | verified |
| influxdb | `core/tokio_metrics_bridge/src/lib.rs` | rust | verified |
| uniswap-contracts | `lib/oz-v4.7.0/contracts/token/ERC721/extensions/ERC721Burnable.sol` | solidity | verified |
| grafana | `pkg/operators/provisioning/repo_operator.go` | go | verified |
| prysm | `cmd/password_reader.go` | go | verified |
| prysm | `testing/spectest/minimal/deneb__epoch_processing__participation_flag_updates_test.go` | go | verified |
| grafana | `public/app/plugins/datasource/influxdb/queryUtils.ts` | typescript | verified |
| prysm | `tools/interop/split-keys/main_test.go` | go | verified |
| prysm | `beacon-chain/rpc/prysm/v1alpha1/validator/aggregator.go` | go | verified |
| prysm | `testing/util/electra.go` | go | verified |
| influxdb | `influxdb3/tests/cli/log_filter.rs` | rust | verified |
| influxdb | `core/arrow_util/src/string.rs` | rust | verified |
| go | `src/runtime/symtabinl_test.go` | go | verified |
| prysm | `container/queue/priority_queue_test.go` | go | verified |
| uniswap-contracts | `lib/oz-v3.4-solc-0.7/contracts/math/SafeMath.sol` | solidity | verified |
| influxdb | `core/mutable_batch_pb/src/encode.rs` | rust | verified |
| go | `src/simd/archsimd/internal/simd_test/ternary_test.go` | go | verified |
| influxdb | `core/influxdb2_client/src/models/ast/call_expression.rs` | rust | verified |
| prysm | `cmd/prysmctl/p2p/handshake.go` | go | verified |
| go | `src/encoding/csv/reader_test.go` | go | verified |