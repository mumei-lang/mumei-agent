# Target OSS no-LLM dogfooding audit — continuation 329 (batch 330)

Run: 2026-07-22T20:01:51.119496+00:00

## Summary

- Files audited: 50
- Verified: 50
- Refuted: 0
- Unverifiable: 0

All sampled files passed no-LLM verification; no new tool-side fixes were required.

## Sample details

| repo | file | status | notes |
|------|------|--------|-------|
| go | `src/cmd/go/internal/modload/import_test.go` | verified |  |
| go | `src/cmd/link/internal/ld/outbuf_windows.go` | verified |  |
| go | `src/crypto/tls/key_agreement.go` | verified |  |
| go | `src/encoding/json/v2/fields.go` | verified |  |
| go | `src/internal/runtime/atomic/atomic_wasm.go` | verified |  |
| go | `src/internal/runtime/maps/export_test.go` | verified |  |
| go | `src/math/cmplx/example_test.go` | verified |  |
| go | `src/os/rawconn.go` | verified |  |
| go | `src/reflect/swapper.go` | verified |  |
| go | `src/reflect/tostring_test.go` | verified |  |
| go | `src/syscall/route_freebsd_32bit.go` | verified |  |
| go | `src/testing/synctest/synctest.go` | verified |  |
| go | `test/fixedbugs/bug007.go` | verified |  |
| go | `test/fixedbugs/issue5755.dir/a.go` | verified |  |
| go | `test/fixedbugs/issue6703w.go` | verified |  |
| grafana | `apps/alerting/notifications/pkg/apis/alertingnotifications/v1beta1/fakes/timeinterval_gen.go` | verified |  |
| grafana | `apps/provisioning/pkg/generated/applyconfiguration/provisioning/v0alpha1/syncstatus.go` | verified |  |
| grafana | `packages/grafana-data/src/field/FieldConfigOptionsRegistry.tsx` | verified |  |
| grafana | `packages/grafana-schema/src/raw/composable/xychart/panelcfg/x/types.gen.ts` | verified |  |
| grafana | `packages/grafana-ui/src/components/CallToActionCard/CallToActionCard.tsx` | verified |  |
| grafana | `pkg/plugins/backendplugin/grpcplugin/log_wrapper.go` | verified |  |
| grafana | `pkg/registry/apis/appplugin/settings.go` | verified |  |
| grafana | `pkg/registry/apis/provisioning/jobs/sync/sync_condition_test.go` | verified |  |
| grafana | `pkg/registry/apis/provisioning/repository_fields.go` | verified |  |
| grafana | `pkg/services/featuremgmt/usage_stats_test.go` | verified |  |
| grafana | `pkg/services/ngalert/models/admin_configuration_test.go` | verified |  |
| grafana | `pkg/services/sqlstore/migrations/usermig/test/user_test.go` | verified |  |
| grafana | `pkg/services/sqlstore/session_test.go` | verified |  |
| grafana | `pkg/tsdb/cloudwatch/models/settings.go` | verified |  |
| grafana | `pkg/tsdb/cloudwatch/response_parser.go` | verified |  |
| grafana | `pkg/util/errhttp/writer.go` | verified |  |
| grafana | `public/app/core/components/SVG/SanitizedSVG.tsx` | verified |  |
| grafana | `public/app/core/components/SharedPreferences/useSharedPreferences.ts` | verified |  |
| grafana | `public/app/features/alerting/unified/components/rules/RuleDetailsDataSources.tsx` | verified |  |
| grafana | `public/app/features/auth-config/fields.tsx` | verified |  |
| grafana | `public/app/features/datasources/components/DataSourceTypeCardList.tsx` | verified |  |
| grafana | `public/app/features/explore/Logs/utils/url.ts` | verified |  |
| grafana | `public/app/plugins/panel/bargauge/BarGaugeLegend.tsx` | verified |  |
| grafana | `public/app/plugins/panel/flamegraph/types.ts` | verified |  |
| prysm | `beacon-chain/cache/depositsnapshot/log.go` | verified |  |
| prysm | `beacon-chain/monitor/process_sync_committee.go` | verified |  |
| prysm | `beacon-chain/p2p/peers/peerdata/store_test.go` | verified |  |
| prysm | `beacon-chain/state/stategen/replayer_test.go` | verified |  |
| prysm | `beacon-chain/sync/rpc_metadata.go` | verified |  |
| prysm | `beacon-chain/sync/validate_execution_payload_envelope.go` | verified |  |
| prysm | `cmd/flags.go` | verified |  |
| prysm | `testing/spectest/minimal/deneb__operations__withdrawals_test.go` | verified |  |
| prysm | `testing/spectest/minimal/fulu__epoch_processing__eth1_data_reset_test.go` | verified |  |
| prysm | `validator/client/beacon-api/test-helpers/fulu_beacon_block_test_helpers.go` | verified |  |
| prysm | `validator/client/beacon-api/wait_for_chain_start_test.go` | verified |  |
