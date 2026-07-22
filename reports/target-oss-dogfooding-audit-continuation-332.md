# Target OSS no-LLM dogfooding audit — continuation 332 (batch 333)

Run: 2026-07-22T20:11:17.731445+00:00

## Summary

- Files audited: 50
- Verified: 50
- Refuted: 0
- Unverifiable: 0

All sampled files passed no-LLM verification; no new tool-side fixes were required.

## Sample details

| repo | file | status | notes |
|------|------|--------|-------|
| go | `misc/cgo/gmp/pi.go` | verified |  |
| go | `src/cmd/compile/internal/ssa/rewriteWasm.go` | verified |  |
| go | `src/cmd/internal/obj/x86/anames.go` | verified |  |
| go | `src/cmd/internal/objabi/stack.go` | verified |  |
| go | `src/crypto/ecdsa/example_test.go` | verified |  |
| go | `src/crypto/internal/fips140/sha256/sha256block_noasm.go` | verified |  |
| go | `src/internal/abi/stack.go` | verified |  |
| go | `src/net/file_stub.go` | verified |  |
| go | `src/net/udpsock_plan9_test.go` | verified |  |
| go | `src/reflect/all_test.go` | verified |  |
| go | `src/runtime/debug_test.go` | verified |  |
| go | `test/bloop.go` | verified |  |
| go | `test/fixedbugs/bug491.go` | verified |  |
| go | `test/fixedbugs/issue22200b.go` | verified |  |
| grafana | `packages/grafana-ui/src/components/VizLegend/VizLegendTable.tsx` | verified |  |
| grafana | `pkg/apimachinery/utils/meta.go` | verified |  |
| grafana | `pkg/apimachinery/utils/tableConverter_test.go` | verified |  |
| grafana | `pkg/apiserver/readonly/store.go` | verified |  |
| grafana | `pkg/apiserver/rest/storage_mock.go` | verified |  |
| grafana | `pkg/clientauth/roundtripper_test.go` | verified |  |
| grafana | `pkg/components/imguploader/localuploader.go` | verified |  |
| grafana | `pkg/infra/httpclient/httpclientprovider/http_logger_middleware_test.go` | verified |  |
| grafana | `pkg/registry/apis/provisioning/history.go` | verified |  |
| grafana | `pkg/registry/apis/secret/mutator/keeper_test.go` | verified |  |
| grafana | `pkg/services/accesscontrol/database/externalservices_test.go` | verified |  |
| grafana | `pkg/services/ngalert/api/lotex_ruler_test.go` | verified |  |
| grafana | `pkg/services/sqlstore/migrator/migrator.go` | verified |  |
| grafana | `pkg/services/sqlstore/sqlstore_testinfra_test.go` | verified |  |
| grafana | `pkg/storage/unified/resource/list_with_field_selectors.go` | verified |  |
| grafana | `pkg/tsdb/grafana-testdata-datasource/admission_handler_test.go` | verified |  |
| grafana | `pkg/tsdb/loki/step.go` | verified |  |
| grafana | `public/app/features/alerting/unified/utils/matchers.ts` | verified |  |
| grafana | `public/app/features/alerting/unified/utils/navigation.ts` | verified |  |
| grafana | `public/app/features/migrate-to-cloud/onprem/EmptyState/EmptyState.tsx` | verified |  |
| grafana | `public/app/features/plugins/components/AppRootPage.tsx` | verified |  |
| grafana | `public/app/features/provisioning/Shared/RepositoryTypeCards.tsx` | verified |  |
| grafana | `public/app/plugins/datasource/cloudwatch/components/shared/MetricStatEditor/MetricStatEditor.tsx` | verified |  |
| grafana | `public/app/plugins/panel/canvas/components/connections/ConnectionAnchors.tsx` | verified |  |
| grafana | `public/app/plugins/panel/nodeGraph/Edge.tsx` | verified |  |
| grafana | `public/app/plugins/panel/trend/TrendPanel.tsx` | verified |  |
| prysm | `beacon-chain/blockchain/service_norace_test.go` | verified |  |
| prysm | `beacon-chain/core/requests/withdrawals_test.go` | verified |  |
| prysm | `beacon-chain/core/validators/slashing_test.go` | verified |  |
| prysm | `beacon-chain/p2p/pubsub.go` | verified |  |
| prysm | `beacon-chain/rpc/prysm/v1alpha1/validator/attester_test.go` | verified |  |
| prysm | `beacon-chain/sync/rpc_metadata_test.go` | verified |  |
| prysm | `testing/endtoend/minimal_builder_e2e_test.go` | verified |  |
| prysm | `testing/spectest/minimal/deneb__operations__block_header_test.go` | verified |  |
| prysm | `validator/client/attest.go` | verified |  |
| prysm | `validator/keymanager/types.go` | verified |  |
