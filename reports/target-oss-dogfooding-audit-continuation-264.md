# Target OSS no-LLM dogfooding audit — continuation 264 (batch 265)

Run: 2026-07-22T15:38:13.787143+00:00

## Summary

- Files audited: 50
- Verified: 50
- Refuted: 0
- Unverifiable: 0

All sampled files passed no-LLM verification; no new tool-side fixes were required.

## Sample details

| repo | file | status | notes |
|------|------|--------|-------|
| go | `src/cmd/compile/internal/ssa/rewriteRISCV64latelower.go` | verified |  |
| go | `src/cmd/go/internal/vcweb/vcweb.go` | verified |  |
| go | `src/crypto/cipher/cfb_test.go` | verified |  |
| go | `src/html/template/attr.go` | verified |  |
| go | `src/html/template/css_test.go` | verified |  |
| go | `src/math/rand/v2/normal.go` | verified |  |
| go | `src/net/http/netconn_test.go` | verified |  |
| go | `src/runtime/gcinfo_test.go` | verified |  |
| go | `src/syscall/route_freebsd_64bit.go` | verified |  |
| go | `test/fixedbugs/issue4518.go` | verified |  |
| go | `test/fixedbugs/issue68322.go` | verified |  |
| go | `test/fixedbugs/issue71932.go` | verified |  |
| go | `test/live_regabi.go` | verified |  |
| go | `test/map.go` | verified |  |
| go | `test/typeparam/issue51219.go` | verified |  |
| go | `test/typeparam/mdempsky/3.dir/b.go` | verified |  |
| grafana | `apps/collections/pkg/apis/collections/v1alpha1/stars_codec_gen.go` | verified |  |
| grafana | `e2e-playwright/test-plugins/grafana-extensionstest-app/components/QueryModal/index.ts` | verified |  |
| grafana | `packages/grafana-data/src/utils/flotPairs.ts` | verified |  |
| grafana | `pkg/api/avatar/avatar_test.go` | verified |  |
| grafana | `pkg/registry/apis/datasource/converter/converter_test.go` | verified |  |
| grafana | `pkg/registry/apis/preferences/legacy/validator.go` | verified |  |
| grafana | `pkg/registry/apis/provisioning/filepath_test.go` | verified |  |
| grafana | `pkg/services/accesscontrol/scope_test.go` | verified |  |
| grafana | `pkg/services/libraryelements/libraryelements_delete_test.go` | verified |  |
| grafana | `pkg/services/ngalert/state/compat.go` | verified |  |
| grafana | `pkg/services/team/teamimpl/store.go` | verified |  |
| grafana | `pkg/storage/unified/search/embed/embedder/bedrock/bedrock.go` | verified |  |
| grafana | `pkg/storage/unified/sql/test/test.go` | verified |  |
| grafana | `public/app/core/components/AppChrome/ReturnToPrevious/DismissableButton.tsx` | verified |  |
| grafana | `public/app/features/alerting/unified/components/permissions/ManagePermissions.tsx` | verified |  |
| grafana | `public/app/features/alerting/unified/components/rule-viewer/tabs/Query/DataSourceModelPreview.tsx` | verified |  |
| grafana | `public/app/features/browse-dashboards/utils/dashboards.ts` | verified |  |
| grafana | `public/app/features/dashboard-scene/conditional-rendering/conditions/utils.ts` | verified |  |
| grafana | `public/app/features/explore/TraceView/components/CriticalPath/testCases/test9.ts` | verified |  |
| grafana | `public/app/plugins/datasource/azuremonitor/azure_log_analytics/mocks/schema.ts` | verified |  |
| grafana | `public/app/plugins/panel/canvas/editor/panZoomHelp.tsx` | verified |  |
| grafana | `public/app/plugins/panel/trend/utils.ts` | verified |  |
| grafana | `scripts/webpack/dependencies.js` | verified |  |
| prysm | `beacon-chain/core/transition/stateutils/validator_index_map.go` | verified |  |
| prysm | `beacon-chain/db/slasherkv/kv_test.go` | verified |  |
| prysm | `beacon-chain/forkchoice/doc.go` | verified |  |
| prysm | `beacon-chain/rpc/eth/beacon/handlers_test.go` | verified |  |
| prysm | `beacon-chain/rpc/eth/beacon/log.go` | verified |  |
| prysm | `beacon-chain/state/stateutil/sync_committee.root.go` | verified |  |
| prysm | `beacon-chain/verification/batch.go` | verified |  |
| prysm | `encoding/ssz/detect/fieldspec.go` | verified |  |
| prysm | `proto/prysm/v1alpha1/powchain.pb.go` | verified |  |
| prysm | `testing/endtoend/minimal_postmerge_e2e_test.go` | verified |  |
| prysm | `testing/spectest/mainnet/phase0__epoch_processing__randao_mixes_reset_test.go` | verified |  |
