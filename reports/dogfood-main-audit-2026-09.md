# Mumei ドッグフーディング — 知見・改善提案メモ

対象: 12リポジトリ(zERC20, helios, tfhe-rs, leanVM, eris-agent-simulator, dioxus, uniswap-contracts, lighthouse, grin, tidb, bsc-genesis-contract, world-chain)/ 全4331ファイルを `mumei-agent audit` + ローカルLLM(Ollama qwen2.5-coder:1.5b-2k)で走査。

最終集計: verified 515 / unverifiable 237 / refuted 6 / timeout 3576 (約82%)。

## 修正済み(マージ済みPR)

- **#573**: encoding-gap(spec_not_boolean等、節がZ3にエンコードされずスキップ)を抱えたまま `verified` と報告される誤判定 → unverifiable 扱いに修正。
- **#574**: Solidity — relative import 先の constant 未解決 + 固定長配列の長さ未モデル化で `zeroHash[TREE_HEIGHT]` が偽陽性 refuted。レビューで推移的import・alias・オーバーロード・`../../`パストラバーサル等9件も堅牢化。
- **#580**: Rust — `&mut [u32; 16]` 等の固定長配列パラメータ長と usize 非負制約が未モデル化で不可能な反例 `b=-1` を生成。len 束縛 + パラメータ型を index チェックに反映。
- **#582**: Go — interface がパッケージスコープなのに同一ファイル内宣言しか見ず nil レシーバ誤検知。`fmt.Stringer`(`String() string`)を既知 interface に追加し、シグネチャ一致(名前のみ→引数型+戻り値まで)で抑制判定を厳密化。

## 残る改善点・洞察

1. **タイムアウトが支配的(82%)**: ボトルネックはZ3/tree-sitterではなく Ollama の spec 抽出推論(2vCPU + 1.5b モデル)。改善案:
   - spec 抽出結果のキャッシュ(ファイルハッシュ鍵)— 再実行・部分再開で効く
   - 大きいファイルは関数分割して並列抽出→合成
   - より強いローカルモデル(qwen2.5-coder:7b 等)を GPU 環境で選べるよう profile 化
2. **小モデル由来の trivial spec → missing_requirement → unverifiable**: 健全(保守的)だが、requires/ensures が「非nil」等の自明文しか出ないケースが多い。atom ごとの minimum spec 品質ガイドをプロンプトに埋め込む、または trivial spec を検出して再プロンプトする retry が有効そう。
3. **「呼び出し側契約」クラスの refuted の扱い**: `ops[o]`(Op enum で常に範囲内)、nil param 等、呼び出し側が契約を満たす前提の指摘が残る。現状は内部関数でも同じ規則で flag するためノイズ源。改善案:
   - 公開API/未公開関数の区別(unexported Go 関数・crate 内 private fn は抑制度を上げる)
   - 呼び出し点での実引数レンジを軽く解析して「到達可能な反例」のみ報告
4. **兄弟メソッド間の一貫性ギャップ検出**: tidb `optional.go` で `Get` は `key < 0 || >= OptPropsCnt` をチェックするのに `Contains` は未チェック — 実害なし(全呼び出しが登録キーを渡す)だが防御的ギャップとして検出できた。同型の「兄弟メソッドの guard 非対称」を専用ヒューリスティクスとして育てる価値あり。
5. **定数・import 解決の汎化**: Solidity/Rust で「別ファイル/別モジュールの定数が配列長や境界を決める」パターンが多発。Go の `const` / パッケージ横断 const も同様に辿れると Go 側の refuted がさらに減る見込み。
6. **運用面**: 1ファイルあたり timeout 300s が重いファイル連続区間で律速。ジョブ分割(子セッション並列)は有効だったが、audit 自体に「重いファイルの推定+スキップ/延長オプション」があると完走時間を制御しやすい。

## 対象リポジトリ側の所見

確定的な不具合・脆弱性はゼロ。唯一の候補は tidb `pkg/expression/expropt/optional.go` の `Contains` 境界チェック欠落(潜伏防御的ギャップ、悪用不可)。zERC20 `LiquidityManager.sol::wrap` の access-control 指摘は意図的設計と判断。
