# Target OSS no-LLM dogfooding audit — continuations 71-75 (batches 72-76)

Run: 2026-07-21T14:55:54.585482+00:00

## Summary

- Batch 72: 50/50 verified
- Batch 73: 50/50 verified
- Batch 74: 50/50 verified
- Batch 75: 50/50 verified
- Batch 76: 50/50 verified
- Total: 250/250 verified
- Refuted: 0
- Unverifiable: 0

All sampled files passed no-LLM verification. No new mumei-agent code changes were required in these batches.

## Sample details by batch

### Batch 72

| repo | file | status | notes |
|------|------|--------|-------|
| prysm | `testing/spectest/mainnet/capella__epoch_processing__effective_balance_updates_test.go` | verified |  |
| go | `test/fixedbugs/issue72844.go` | verified |  |
| go | `src/internal/syscall/unix/net.go` | verified |  |
| influxdb | `core/arrow_util/src/parquet_meta.rs` | verified |  |
| influxdb | `core/iox_query/src/statistics/partition_statistics/mod.rs` | verified |  |
| grafana | `public/app/core/utils/factors.ts` | verified |  |
| grafana | `public/app/features/dashboard-scene/sharing/SaveBeforeShareModal.tsx` | verified |  |
| grafana | `pkg/services/folder/cleaner/provider.go` | verified |  |
| prysm | `testing/spectest/shared/gloas/epoch_processing/randao_mixes_reset.go` | verified |  |
| uniswap-contracts | `lib/oz-v4.7.0/contracts/metatx/ERC2771Context.sol` | verified |  |
| influxdb | `core/iox_http/src/write/v1.rs` | verified |  |
| prysm | `validator/db/kv/import_test.go` | verified |  |
| grafana | `pkg/services/publicdashboards/internal/database/database.go` | verified |  |
| go | `src/cmd/go/internal/web/intercept/intercept.go` | verified |  |
| go | `test/fixedbugs/issue36085.dir/a.go` | verified |  |
| prysm | `beacon-chain/state/stateutil/historical_summaries_root.go` | verified |  |
| influxdb | `influxdb3_load_generator/src/commands/write_fixed.rs` | verified |  |
| prysm | `beacon-chain/db/kv/finalized_block_roots_test.go` | verified |  |
| influxdb | `core/iox_query/src/physical_optimizer/sort/order_union_sorted_inputs.rs` | verified |  |
| uniswap-contracts | `script/cli/src/screens/shared/generic_select_or_enter.rs` | verified |  |
| grafana | `public/app/features/provisioning/Repository/ResourceTreeView.tsx` | verified |  |
| influxdb | `influxdb3_catalog/src/log/versions/mod.rs` | verified |  |
| grafana | `public/app/features/dashboard-scene/solo/SoloPanelPageLogo.tsx` | verified |  |
| prysm | `beacon-chain/sync/subscriber_payload_attestation_test.go` | verified |  |
| prysm | `beacon-chain/core/helpers/block_test.go` | verified |  |
| uniswap-contracts | `src/briefcase/protocols/calibur/lib/openzeppelin-contracts/interfaces/IERC5267.sol` | verified |  |
| influxdb | `influxdb3_load_generator/src/main.rs` | verified |  |
| prysm | `validator/rpc/auth_token_test.go` | verified |  |
| grafana | `pkg/services/publicdashboards/internal/models/models_test.go` | verified |  |
| uniswap-contracts | `src/briefcase/protocols/v3-core/libraries/FullMath.sol` | verified |  |
| uniswap-contracts | `lib/oz-v4.7.0/contracts/utils/math/SafeMath.sol` | verified |  |
| prysm | `beacon-chain/core/blocks/proposer_slashing.go` | verified |  |
| prysm | `beacon-chain/verification/execution_payload_envelope.go` | verified |  |
| go | `src/runtime/vdso_freebsd.go` | verified |  |
| go | `test/simd/bug2.go` | verified |  |
| grafana | `public/app/features/datasources/components/EditDataSourceActions.tsx` | verified |  |
| go | `src/cmd/compile/internal/types2/typeset_test.go` | verified |  |
| go | `test/fixedbugs/issue20145.go` | verified |  |
| uniswap-contracts | `src/briefcase/protocols/v3-periphery/libraries/HexStrings.sol` | verified |  |
| grafana | `apps/provisioning/pkg/safepath/path_test.go` | verified |  |
| influxdb | `core/influxdb_iox_client/src/client/batched_write.rs` | verified |  |
| influxdb | `influxdb3_write/src/write_buffer/checkpoint.rs` | verified |  |
| go | `src/runtime/netpoll_kqueue_pipe.go` | verified |  |
| go | `src/cmd/internal/obj/mkcnames.go` | verified |  |
| grafana | `pkg/registry/apis/provisioning/resources/cleanup_test.go` | verified |  |
| influxdb | `core/iox_query/src/physical_optimizer/dedup/dedup_sort_order.rs` | verified |  |
| uniswap-contracts | `script/cli/src/screens/types/multiple_choice.rs` | verified |  |
| uniswap-contracts | `lib/oz-v4.7.0/contracts/mocks/wizard/MyGovernor2.sol` | verified |  |
| uniswap-contracts | `src/briefcase/protocols/v3-core/interfaces/IUniswapV3PoolDeployer.sol` | verified |  |
| uniswap-contracts | `lib/oz-v4.7.0/contracts/mocks/TimersTimestampImpl.sol` | verified |  |

### Batch 73

| repo | file | status | notes |
|------|------|--------|-------|
| prysm | `encoding/ssz/query/merkle_proof.go` | verified |  |
| uniswap-contracts | `src/briefcase/protocols/v4-hooks-public/aggregator-hooks/implementations/FluidDexT1/interfaces/IFluidDexT1.sol` | verified |  |
| uniswap-contracts | `script/cli/src/screens/shared/enter_address.rs` | verified |  |
| influxdb | `core/catalog_cache/src/local/mod.rs` | verified |  |
| influxdb | `influxdb3_load_generator/src/commands/write.rs` | verified |  |
| uniswap-contracts | `script/cli/src/screens/shared/block_explorer.rs` | verified |  |
| influxdb | `influxdb3_catalog/src/catalog/versions/v3/events.rs` | verified |  |
| grafana | `public/app/features/home/Recommendations/kubernetesData.ts` | verified |  |
| prysm | `beacon-chain/rpc/prysm/v1alpha1/validator/proposer_bid_builder_test.go` | verified |  |
| uniswap-contracts | `src/briefcase/protocols/v4-periphery/libraries/QuoterRevert.sol` | verified |  |
| go | `src/internal/goos/unix.go` | verified |  |
| prysm | `consensus-types/mock/block.go` | verified |  |
| prysm | `beacon-chain/sync/validate_sync_contribution_proof_test.go` | verified |  |
| uniswap-contracts | `script/util/insert_initcode.py` | verified |  |
| prysm | `beacon-chain/rpc/eth/helpers/validator_status.go` | verified |  |
| grafana | `public/app/features/dashboard-scene/serialization/sceneVariablesSetToVariables.ts` | verified |  |
| go | `src/cmd/pprof/pprof.go` | verified |  |
| uniswap-contracts | `script/cli/src/libs/explorer.rs` | verified |  |
| influxdb | `core/mutable_batch_lp/benches/parse_lp.rs` | verified |  |
| grafana | `public/app/features/dashboard/components/ShareModal/SharePublicDashboard/utilsTest.tsx` | verified |  |
| influxdb | `influxdb3_system_tables/src/distinct_caches.rs` | verified |  |
| prysm | `beacon-chain/state/state-native/getters_setters_lookahead_test.go` | verified |  |
| grafana | `pkg/services/auth/gcomsso/gcom_logout_hook.go` | verified |  |
| grafana | `apps/dashboard/pkg/apis/dashboard/v2beta1/constants.go` | verified |  |
| prysm | `validator/client/beacon-api/beacon_block_json_helpers.go` | verified |  |
| uniswap-contracts | `lib/oz-v4.7.0/contracts/interfaces/IERC1155.sol` | verified |  |
| prysm | `crypto/keystore/keystore.go` | verified |  |
| go | `test/typeparam/issue48094.dir/main.go` | verified |  |
| go | `src/crypto/cipher/gcm_fips140v1.26_test.go` | verified |  |
| influxdb | `core/metric/src/gauge.rs` | verified |  |
| uniswap-contracts | `src/briefcase/protocols/v4-hooks-public/aggregator-hooks/utils/AggregatorHookMiner.sol` | verified |  |
| influxdb | `core/influxdb2_client/src/models/query.rs` | verified |  |
| grafana | `pkg/services/live/pipeline/frame_output_loki.go` | verified |  |
| grafana | `public/app/plugins/panel/flamegraph/module.tsx` | verified |  |
| prysm | `beacon-chain/p2p/testing/mock_metadataprovider.go` | verified |  |
| go | `src/syscall/exec_unix.go` | verified |  |
| influxdb | `core/influxdb_iox_client/src/client/flightsql.rs` | verified |  |
| go | `src/cmd/go/internal/gover/gover.go` | verified |  |
| go | `src/runtime/tls_windows_amd64.go` | verified |  |
| grafana | `packages/grafana-data/src/transformations/matchers/predicates.ts` | verified |  |
| grafana | `pkg/tsdb/loki/schema.go` | verified |  |
| prysm | `testing/spectest/mainnet/phase0__operations__attester_slashing_test.go` | verified |  |
| influxdb | `influxdb3_catalog/src/format/records/trigger.rs` | verified |  |
| grafana | `pkg/services/grpcserver/service.go` | verified |  |
| go | `src/runtime/trace/subscribe.go` | verified |  |
| uniswap-contracts | `src/briefcase/protocols/swap-router-contracts/libraries/UniswapV2Library.sol` | verified |  |
| uniswap-contracts | `src/briefcase/deployers/permit2/Permit2Deployer.sol` | verified |  |
| go | `src/cmd/cgo/internal/test/issue42495.go` | verified |  |
| influxdb | `core/influxdb_line_protocol/fuzz/fuzz_targets/parsing_errors.rs` | verified |  |
| go | `test/defererrcheck.go` | verified |  |

### Batch 74

| repo | file | status | notes |
|------|------|--------|-------|
| grafana | `pkg/services/ngalert/api/api_provisioning_test.go` | verified |  |
| grafana | `pkg/services/live/pipeline/converter_json_auto.go` | verified |  |
| go | `test/fixedbugs/issue49110.go` | verified |  |
| go | `src/crypto/hpke/hpke_test.go` | verified |  |
| uniswap-contracts | `lib/oz-v4.7.0/contracts/mocks/ERC165CheckerMock.sol` | verified |  |
| influxdb | `core/iox_query_influxql/src/plan/planner_time_range_expression.rs` | verified |  |
| uniswap-contracts | `src/briefcase/protocols/v3-periphery/interfaces/external/IERC1271.sol` | verified |  |
| grafana | `pkg/services/ngalert/eval/eval_test.go` | verified |  |
| go | `test/ken/simpconv.go` | verified |  |
| prysm | `testing/spectest/mainnet/fulu__epoch_processing__participation_flag_updates_test.go` | verified |  |
| prysm | `beacon-chain/forkchoice/doubly-linked-tree/store.go` | verified |  |
| influxdb | `influxdb3_catalog/src/catalog/versions/v3/catalog.rs` | verified |  |
| grafana | `pkg/infra/fs/copy_test.go` | verified |  |
| influxdb | `influxdb3_catalog/src/catalog/versions/v3/ops/cache.rs` | verified |  |
| influxdb | `core/table_batch/src/values.rs` | verified |  |
| go | `src/syscall/zerrors_netbsd_arm.go` | verified |  |
| prysm | `validator/accounts/accounts_exit.go` | verified |  |
| influxdb | `core/iox_query/src/physical_optimizer/sort/order_union_sorted_inputs_for_constants.rs` | verified |  |
| go | `test/fixedbugs/bug482.go` | verified |  |
| grafana | `packages/grafana-ui/src/themes/GlobalStyles/skeletonStyles.ts` | verified |  |
| prysm | `beacon-chain/startup/synchronizer_test.go` | verified |  |
| uniswap-contracts | `src/briefcase/deployers/v4-hooks-public/WstETHHookDeployer.sol` | verified |  |
| go | `src/internal/syscall/unix/fchmodat_test.go` | verified |  |
| go | `src/os/file_wasip1.go` | verified |  |
| uniswap-contracts | `lib/oz-v4.7.0/contracts/mocks/BadBeacon.sol` | verified |  |
| prysm | `beacon-chain/core/altair/reward.go` | verified |  |
| prysm | `testing/spectest/minimal/deneb__operations__proposer_slashing_test.go` | verified |  |
| prysm | `beacon-chain/forkchoice/doubly-linked-tree/types.go` | verified |  |
| go | `test/fixedbugs/issue79274a.dir/a.go` | verified |  |
| grafana | `apps/provisioning/pkg/apis/auth/verb_aware_access_checker.go` | verified |  |
| prysm | `beacon-chain/core/gloas/payload_test.go` | verified |  |
| uniswap-contracts | `lib/oz-v4.7.0/contracts/mocks/DoubleEndedQueueMock.sol` | verified |  |
| grafana | `pkg/registry/apis/provisioning/controller/metrics.go` | verified |  |
| grafana | `public/app/core/services/echo/backends/analytics/ApplicationInsightsBackend.ts` | verified |  |
| uniswap-contracts | `lib/oz-v4.7.0/contracts/mocks/ERC721BurnableMock.sol` | verified |  |
| uniswap-contracts | `lib/oz-v4.7.0/contracts/mocks/SafeERC20Helper.sol` | verified |  |
| uniswap-contracts | `lib/oz-v4.7.0/contracts/mocks/SafeCastMock.sol` | verified |  |
| influxdb | `core/arrow_util/src/flight.rs` | verified |  |
| go | `src/os/exec/lookpath.go` | verified |  |
| grafana | `pkg/registry/apis/provisioning/controller/token_refresh.go` | verified |  |
| grafana | `packages/grafana-flamegraph/src/FlameGraphContainer.tsx` | verified |  |
| prysm | `beacon-chain/state/state-native/getters_deposit_requests.go` | verified |  |
| influxdb | `core/object_store_mem_cache/src/cache_system/hook/mod.rs` | verified |  |
| influxdb | `influxdb3_commands/src/helpers.rs` | verified |  |
| uniswap-contracts | `src/briefcase/protocols/mixed-quoter/libraries/V3PoolAddress.sol` | verified |  |
| uniswap-contracts | `lib/oz-v4.7.0/contracts/mocks/VotesMock.sol` | verified |  |
| prysm | `testing/spectest/shared/common/operations/slashing.go` | verified |  |
| go | `test/fixedbugs/bug193.go` | verified |  |
| influxdb | `core/catalog_cache/src/lib.rs` | verified |  |
| influxdb | `core/influxdb_influxql_parser/src/parameter.rs` | verified |  |

### Batch 75

| repo | file | status | notes |
|------|------|--------|-------|
| influxdb | `influxdb3_py_api/src/line_builder/line_builder.py` | verified |  |
| influxdb | `influxdb3_catalog/src/format/records/generation.rs` | verified |  |
| grafana | `pkg/infra/db/dbtest/dbtest.go` | verified |  |
| uniswap-contracts | `src/briefcase/protocols/v4-core/libraries/SqrtPriceMath.sol` | verified |  |
| go | `src/go/ast/example_test.go` | verified |  |
| uniswap-contracts | `src/briefcase/protocols/swap-router-contracts/interfaces/IV3SwapRouter.sol` | verified |  |
| prysm | `cmd/validator/slashing-protection/import_export_test.go` | verified |  |
| go | `src/os/types_windows.go` | verified |  |
| prysm | `proto/engine/v1/blobs_bundle.go` | verified |  |
| uniswap-contracts | `lib/oz-v4.7.0/contracts/mocks/ERC777Mock.sol` | verified |  |
| go | `test/fixedbugs/issue7223.go` | verified |  |
| go | `test/fixedbugs/issue22581.go` | verified |  |
| uniswap-contracts | `lib/oz-v4.7.0/contracts/crosschain/optimism/CrossChainEnabledOptimism.sol` | verified |  |
| grafana | `public/app/features/plugins/sandbox/distortions.ts` | verified |  |
| go | `test/typeparam/issue48716.go` | verified |  |
| grafana | `pkg/services/annotations/annotationsimpl/cleanup_test.go` | verified |  |
| uniswap-contracts | `script/cli/src/screens/shared/text_display_screen.rs` | verified |  |
| grafana | `public/app/features/templating/templateProxies.ts` | verified |  |
| influxdb | `influxdb3_telemetry/src/sampler.rs` | verified |  |
| prysm | `validator/client/grpc-api/grpc_client_manager_test.go` | verified |  |
| go | `src/cmd/internal/obj/ppc64/obj9.go` | verified |  |
| grafana | `public/app/features/canvas/elements/server/server.tsx` | verified |  |
| go | `src/runtime/signal_openbsd_ppc64.go` | verified |  |
| prysm | `tools/analyzers/modernize/forvar/analyzer.go` | verified |  |
| influxdb | `core/flightsql/src/planner.rs` | verified |  |
| influxdb | `core/object_store_metrics/src/stream.rs` | verified |  |
| go | `test/fixedbugs/issue62498.dir/a.go` | verified |  |
| influxdb | `core/iox_http/src/lib.rs` | verified |  |
| go | `test/fixedbugs/issue43551.dir/b.go` | verified |  |
| influxdb | `core/iox_query/src/exec/gapfill/date_bin_gap_expander.rs` | verified |  |
| grafana | `public/locales/enterprise/i18next.config.ts` | verified |  |
| prysm | `beacon-chain/p2p/message_id.go` | verified |  |
| grafana | `pkg/services/supportbundles/supportbundlesimpl/service_bundle_test.go` | verified |  |
| influxdb | `influxdb3_write/src/table_index/test_persisted_snapshot_conversion.rs` | verified |  |
| prysm | `validator/rpc/beacon.go` | verified |  |
| influxdb | `core/object_store_metrics/src/metrics.rs` | verified |  |
| grafana | `public/app/features/plugins/admin/components/Badges/PluginInstallBadge.tsx` | verified |  |
| uniswap-contracts | `lib/oz-v4.7.0/contracts/utils/cryptography/MerkleProof.sol` | verified |  |
| prysm | `beacon-chain/sync/backfill/verify.go` | verified |  |
| grafana | `pkg/codegen/jenny_ts_types.go` | verified |  |
| prysm | `beacon-chain/db/slasherkv/slasher_test.go` | verified |  |
| prysm | `runtime/interop/generate_keys.go` | verified |  |
| uniswap-contracts | `lib/oz-v4.7.0/contracts/mocks/ERC165Mock.sol` | verified |  |
| go | `test/typeparam/issue50598.dir/main.go` | verified |  |
| influxdb | `core/influxdb_influxql_parser/src/expression/conditional.rs` | verified |  |
| uniswap-contracts | `src/briefcase/protocols/lib-external/webauthn-sol/src/WebAuthn.sol` | verified |  |
| prysm | `beacon-chain/p2p/message_id_test.go` | verified |  |
| uniswap-contracts | `src/briefcase/protocols/v3-periphery/interfaces/INonfungibleTokenPositionDescriptor.sol` | verified |  |
| grafana | `apps/alerting/rules/pkg/apis/types.go` | verified |  |
| uniswap-contracts | `lib/oz-v4.7.0/contracts/utils/structs/EnumerableMap.sol` | verified |  |

### Batch 76

| repo | file | status | notes |
|------|------|--------|-------|
| prysm | `monitoring/clientstats/updaters.go` | verified |  |
| go | `src/simd/archsimd/internal/simd_test/convert_helpers_128_test.go` | verified |  |
| prysm | `config/util_test.go` | verified |  |
| influxdb | `core/influxdb2_client/src/api/label.rs` | verified |  |
| uniswap-contracts | `lib/oz-v4.7.0/contracts/token/ERC20/IERC20.sol` | verified |  |
| go | `test/fixedbugs/issue62313.go` | verified |  |
| uniswap-contracts | `lib/oz-v4.7.0/contracts/proxy/utils/Initializable.sol` | verified |  |
| uniswap-contracts | `src/briefcase/protocols/v4-hooks-public/aggregator-hooks/implementations/StableSwap/interfaces/ICurveFactory.sol` | verified |  |
| influxdb | `core/object_store_mem_cache/src/lib.rs` | verified |  |
| prysm | `beacon-chain/das/log.go` | verified |  |
| go | `src/hash/crc32/crc32_arm64.go` | verified |  |
| influxdb | `core/iox_query_influxql/src/plan/udf.rs` | verified |  |
| uniswap-contracts | `src/briefcase/protocols/v4-core/interfaces/IHooks.sol` | verified |  |
| grafana | `public/app/features/explore/TraceView/useSearch.ts` | verified |  |
| influxdb | `influxdb3_wal/src/snapshot_tracker.rs` | verified |  |
| uniswap-contracts | `lib/oz-v4.7.0/contracts/interfaces/IERC1155Receiver.sol` | verified |  |
| go | `test/fixedbugs/bug333.go` | verified |  |
| influxdb | `core/iox_query/src/statistics/stats_utils.rs` | verified |  |
| prysm | `beacon-chain/p2p/partialdatacolumnbroadcaster/integrationtest/two_node_test.go` | verified |  |
| go | `src/cmd/compile/internal/ir/expr.go` | verified |  |
| prysm | `testing/spectest/minimal/gloas__epoch_processing__slashings_test.go` | verified |  |
| grafana | `public/app/plugins/datasource/loki/components/monaco-query-field/MonacoQueryFieldProps.ts` | verified |  |
| go | `test/fixedbugs/bug104.go` | verified |  |
| go | `test/dwarf/dwarf.dir/z6.go` | verified |  |
| grafana | `pkg/services/authz/zanzana/schema/transform_test.go` | verified |  |
| go | `src/runtime/netpoll_solaris.go` | verified |  |
| influxdb | `influxdb3_write/src/persister.rs` | verified |  |
| influxdb | `influxdb3_catalog/src/log/versions/v4.rs` | verified |  |
| uniswap-contracts | `src/briefcase/protocols/v3-core/interfaces/callback/IUniswapV3SwapCallback.sol` | verified |  |
| prysm | `validator/keymanager/derived/keymanager.go` | verified |  |
| prysm | `testing/spectest/shared/bellatrix/operations/block_header.go` | verified |  |
| grafana | `pkg/services/auth/authimpl/auth_token_test.go` | verified |  |
| influxdb | `influxdb3_cache/src/distinct_cache/mod.rs` | verified |  |
| grafana | `public/app/plugins/panel/barchart/BarChartLegend.tsx` | verified |  |
| go | `test/fixedbugs/bug203.go` | verified |  |
| influxdb | `core/authz/src/iox_authorizer.rs` | verified |  |
| uniswap-contracts | `lib/oz-v4.7.0/contracts/interfaces/IERC1820Implementer.sol` | verified |  |
| grafana | `packages/grafana-runtime/src/services/dataSource/logging.ts` | verified |  |
| influxdb | `influxdb3_system_tables/src/queries.rs` | verified |  |
| uniswap-contracts | `src/briefcase/protocols/v3-periphery/libraries/PoolAddress.sol` | verified |  |
| grafana | `pkg/services/sqlstore/sqlstore_test.go` | verified |  |
| grafana | `public/app/features/alerting/unified/components/EmptyAreaWithCTA.tsx` | verified |  |
| prysm | `beacon-chain/operations/attestations/mock/mock.go` | verified |  |
| prysm | `beacon-chain/sync/rpc_data_column_sidecars_by_range_test.go` | verified |  |
| uniswap-contracts | `src/briefcase/protocols/v4-periphery/libraries/SlippageCheck.sol` | verified |  |
| go | `src/math/tan.go` | verified |  |
| uniswap-contracts | `src/briefcase/protocols/lib-external/solady/src/utils/LibString.sol` | verified |  |
| prysm | `beacon-chain/rpc/testutil/db.go` | verified |  |
| grafana | `pkg/login/social/connectors/okta_oauth.go` | verified |  |
| grafana | `pkg/services/dashboardversion/dashverimpl/dashver_test.go` | verified |  |

