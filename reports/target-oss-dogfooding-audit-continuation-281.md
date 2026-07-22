# Target OSS no-LLM dogfooding audit — continuation 281 (batch 282)

Run: 2026-07-22T16:56:12.035368+00:00

## Summary

- Files audited: 50
- Verified: 50
- Refuted: 0
- Unverifiable: 0

All sampled files passed no-LLM verification; no new tool-side fixes were required.

## Sample details

| repo | file | status | notes |
|------|------|--------|-------|
| go | `src/cmd/compile/internal/inline/inlheur/trace_off.go` | verified |  |
| go | `src/cmd/internal/objfile/goobj.go` | verified |  |
| go | `src/cmd/link/internal/ld/outbuf_notdarwin.go` | verified |  |
| go | `src/crypto/hpke/hpke.go` | verified |  |
| go | `src/crypto/internal/fips140/tls13/tls13.go` | verified |  |
| go | `src/html/entity.go` | verified |  |
| go | `src/internal/goexperiment/exp_cgocheck2_off.go` | verified |  |
| go | `src/net/http/client_test.go` | verified |  |
| go | `src/runtime/valgrind0.go` | verified |  |
| go | `test/chan/select5.go` | verified |  |
| go | `test/fixedbugs/issue26335.go` | verified |  |
| go | `test/fixedbugs/issue56280.dir/a.go` | verified |  |
| go | `test/typeparam/issue47708.go` | verified |  |
| go | `test/typeparam/issue48604.go` | verified |  |
| grafana | `apps/alerting/notifications/pkg/apis/alertingnotifications/v0alpha1/receiver_schema_gen.go` | verified |  |
| grafana | `apps/provisioning/pkg/generated/applyconfiguration/provisioning/v0alpha1/tokenstatus.go` | verified |  |
| grafana | `e2e-playwright/plugin-e2e/mysql/utils.ts` | verified |  |
| grafana | `packages/grafana-ui/src/components/Modal/ModalTabsHeader.tsx` | verified |  |
| grafana | `packages/grafana-ui/src/components/uPlot/plugins/XAxisInteractionAreaPlugin.tsx` | verified |  |
| grafana | `pkg/api/pluginproxy/utils_test.go` | verified |  |
| grafana | `pkg/registry/apis/dashboard/variable.go` | verified |  |
| grafana | `pkg/registry/apis/folders/folder_storage.go` | verified |  |
| grafana | `pkg/services/authz/zanzana/common/info_test.go` | verified |  |
| grafana | `pkg/services/dashboards/service/client/client.go` | verified |  |
| grafana | `pkg/services/datasources/models_test.go` | verified |  |
| grafana | `pkg/services/live/remotewrite/convert.go` | verified |  |
| grafana | `pkg/services/publicdashboards/internal/service/intervalv2/intervalv2_test.go` | verified |  |
| grafana | `pkg/storage/unified/resource/kv/context.go` | verified |  |
| grafana | `pkg/storage/unified/search/bleve.go` | verified |  |
| grafana | `pkg/tests/apis/client.go` | verified |  |
| grafana | `pkg/tests/apis/provisioning/foldermetadata/migrate_folder_ids_test.go` | verified |  |
| grafana | `pkg/tsdb/mysql/mysql_service.go` | verified |  |
| grafana | `public/app/features/alerting/unified/components/mute-timings/util.tsx` | verified |  |
| grafana | `public/app/features/explore/ContentOutline/ContentOutlineItemButton.tsx` | verified |  |
| grafana | `public/app/features/explore/ExploreToolbar.tsx` | verified |  |
| grafana | `public/app/plugins/datasource/azuremonitor/components/QueryEditor/QueryEditor.tsx` | verified |  |
| grafana | `public/app/plugins/datasource/grafana-postgresql-datasource/postgresMetaQuery.ts` | verified |  |
| grafana | `public/app/plugins/panel/geomap/editor/MapViewEditor.tsx` | verified |  |
| grafana | `public/app/types/explore.ts` | verified |  |
| prysm | `beacon-chain/blockchain/weak_subjectivity_checks_test.go` | verified |  |
| prysm | `beacon-chain/db/kv/state_diff_helpers_test.go` | verified |  |
| prysm | `beacon-chain/monitor/process_exit.go` | verified |  |
| prysm | `beacon-chain/rpc/endpoints_test.go` | verified |  |
| prysm | `beacon-chain/state/state-native/multi_value_slices.go` | verified |  |
| prysm | `beacon-chain/state/stateutil/unrealized_justification.go` | verified |  |
| prysm | `testing/endtoend/evaluators/beaconapi/verify.go` | verified |  |
| prysm | `testing/spectest/mainnet/bellatrix__ssz_static__ssz_static_test.go` | verified |  |
| prysm | `testing/spectest/shared/gloas/epoch_processing/proposer_lookahead.go` | verified |  |
| prysm | `validator/client/beacon-api/index_test.go` | verified |  |
| prysm | `validator/client/key_reload.go` | verified |  |
