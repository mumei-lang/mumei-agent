# Target OSS no-LLM dogfooding audit — continuation 28 (batch 29)

Run: 2026-07-21T03:26:41.423270Z

## Summary

- Files audited: 50
- Verified: 50
- Refuted: 0
- Unverifiable: 0

All 50 sampled files passed no-LLM verification in this batch. No new tool-side fixes were required.

## Sample details

| repo | file | status | notes |
|------|------|--------|-------|
| grafana | `pkg/services/ngalert/provisioning/mute_timings.go` | verified |  |
| go | `src/simd/archsimd/internal/simd_test/binary_wasm_test.go` | verified |  |
| grafana | `packages/grafana-ui/src/components/UsersIndicator/UserIcon.story.tsx` | verified |  |
| grafana | `public/app/core/components/ThemeSelector/ThemeCard.test.tsx` | verified |  |
| go | `src/encoding/json/jsontext/state_test.go` | verified |  |
| grafana | `pkg/services/pluginsintegration/angulardetectorsprovider/gcom.go` | verified |  |
| go | `src/math/cmplx/phase.go` | verified |  |
| go | `src/crypto/rand/util_test.go` | verified |  |
| go | `test/fixedbugs/issue47068.dir/a.go` | verified |  |
| grafana | `pkg/storage/unified/search/vector/promoter.go` | verified |  |
| grafana | `public/app/features/explore/TraceView/components/selectors/trace.ts` | verified |  |
| grafana | `pkg/services/authz/zanzana/server/server_store.go` | verified |  |
| prysm | `testing/spectest/mainnet/capella__finality__finality_test.go` | verified | No Mumei atoms |
| grafana | `public/app/features/dashboard-scene/utils/getVizSuggestionForQuery.test.ts` | verified |  |
| go | `src/runtime/defs2_linux.go` | verified |  |
| prysm | `validator/keymanager/local/log.go` | verified |  |
| go | `test/fixedbugs/issue8132.go` | verified |  |
| grafana | `public/app/plugins/datasource/azuremonitor/components/MetricsQueryEditor/MetricsQueryEditor.test.tsx` | verified |  |
| influxdb | `influxdb3_processing_engine/src/environment.rs` | verified |  |
| go | `src/net/http/httputil/example_test.go` | verified | No Mumei atoms |
| go | `src/internal/fuzz/counters_supported.go` | verified |  |
| go | `src/cmd/go/internal/workcmd/init.go` | verified |  |
| go | `src/internal/routebsd/interface_multicast.go` | verified |  |
| grafana | `public/app/features/provisioning/components/ProvisionedFormGate.test.tsx` | verified |  |
| grafana | `apps/dashboard/pkg/migration/conversion/conversion_cache_test.go` | verified |  |
| go | `test/fixedbugs/issue24763.go` | verified |  |
| go | `test/fixedbugs/issue61895.go` | verified |  |
| go | `test/fixedbugs/issue32175.go` | verified |  |
| go | `src/internal/types/testdata/fixedbugs/issue39982.go` | verified | No Mumei atoms |
| grafana | `public/app/features/dashboard-scene/v2schema/DashboardSchemaEditor.tsx` | verified |  |
| prysm | `beacon-chain/startup/clock_test.go` | verified |  |
| grafana | `pkg/storage/unified/resource/transaction.go` | verified |  |
| prysm | `beacon-chain/rpc/eth/light-client/server.go` | verified |  |
| go | `test/fixedbugs/issue26153.go` | verified |  |
| go | `src/syscall/time_nofake.go` | verified |  |
| grafana | `pkg/services/encryption/encryption.go` | verified |  |
| grafana | `pkg/services/auth/jwt/signing_test.go` | verified |  |
| go | `src/runtime/testdata/testgoroutineleakprofile/goker/kubernetes1321.go` | verified |  |
| grafana | `packages/grafana-ui/src/components/MatchersUI/FieldNamesMatcherEditor.tsx` | verified |  |
| go | `src/reflect/abi_test.go` | verified |  |
| grafana | `public/app/types/user.ts` | verified |  |
| go | `test/fixedbugs/issue31636.dir/b.go` | verified |  |
| go | `test/escape6.go` | verified |  |
| grafana | `apps/dashboard/pkg/apis/dashboard/v0alpha1/conversion.go` | verified |  |
| influxdb | `influxdb3_telemetry/src/sender.rs` | verified |  |
| go | `test/fixedbugs/issue60601.go` | verified |  |
| grafana | `public/app/features/browse-dashboards/components/QuotaLimitBanner.tsx` | verified |  |
| prysm | `beacon-chain/p2p/pubsub_filter.go` | verified |  |
| grafana | `public/app/features/geo/gazetteer/worldmap.ts` | verified |  |
| grafana | `packages/grafana-data/src/utils/tests/mockTransformationsRegistry.ts` | verified |  |
