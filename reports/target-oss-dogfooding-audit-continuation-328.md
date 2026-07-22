# Target OSS no-LLM dogfooding audit — continuation 328 (batch 329)

Run: 2026-07-22T19:54:53.655605+00:00

## Summary

- Files audited: 50
- Verified: 50
- Refuted: 0
- Unverifiable: 0

All sampled files passed no-LLM verification; no new tool-side fixes were required.

## Sample details

| repo | file | status | notes |
|------|------|--------|-------|
| go | `src/cmd/compile/internal/types2/gcsizes.go` | verified |  |
| go | `src/cmd/internal/cov/read_test.go` | verified |  |
| go | `src/cmd/internal/obj/x86/seh.go` | verified |  |
| go | `src/encoding/json/v2/arshal_time.go` | verified |  |
| go | `src/internal/nettest/queue.go` | verified |  |
| go | `src/internal/syscall/windows/string_windows_test.go` | verified |  |
| go | `src/io/fs/format.go` | verified |  |
| go | `src/math/atan2.go` | verified |  |
| go | `test/fixedbugs/issue16616.dir/b.go` | verified |  |
| go | `test/fixedbugs/issue27595.go` | verified |  |
| go | `test/fixedbugs/issue6789.dir/a.go` | verified |  |
| go | `test/fixedbugs/issue7998.go` | verified |  |
| go | `test/typeparam/mdempsky/8.go` | verified |  |
| go | `test/typeparam/ordered.go` | verified |  |
| grafana | `apps/alerting/notifications/pkg/apis/alertingnotifications/v0alpha1/receiver_createreceiverintegrationtest_request_body_types_gen.go` | verified |  |
| grafana | `apps/annotation/pkg/apis/annotation/v0alpha1/getsearch_response_body_types_gen.go` | verified |  |
| grafana | `apps/plugins/pkg/apis/plugins/v0alpha1/constants.go` | verified |  |
| grafana | `packages/grafana-data/src/transformations/transformers/merge.ts` | verified |  |
| grafana | `packages/grafana-schema/src/schema/dashboard/v2beta1/v2beta1_examples.ts` | verified |  |
| grafana | `packages/grafana-ui/src/components/AutoSaveField/AutoSaveField.tsx` | verified |  |
| grafana | `pkg/login/social/connectors/grafana_com_oauth_test.go` | verified |  |
| grafana | `pkg/plugins/openapi/augment.go` | verified |  |
| grafana | `pkg/registry/apis/provisioning/jobs/migrate/unifiedstorage_test.go` | verified |  |
| grafana | `pkg/services/live/runstream/manager_test.go` | verified |  |
| grafana | `pkg/services/ngalert/api/hooks.go` | verified |  |
| grafana | `pkg/storage/legacysql/dualwrite/storage_mocks_test.go` | verified |  |
| grafana | `pkg/storage/unified/resource/limited_writer.go` | verified |  |
| grafana | `pkg/storage/unified/resource/search_test.go` | verified |  |
| grafana | `pkg/tests/api/graphite/graphite_test.go` | verified |  |
| grafana | `pkg/tests/apis/dashboard/snapshot_test.go` | verified |  |
| grafana | `pkg/tsdb/cloudwatch/models/settings_test.go` | verified |  |
| grafana | `public/app/features/browse-dashboards/components/BrowseActions/utils.ts` | verified |  |
| grafana | `public/app/features/dashboard-scene/scene/layout-rows/RowItemEditor.tsx` | verified |  |
| grafana | `public/app/features/dashboard/components/TransformationsEditor/TransformationPickerNg.tsx` | verified |  |
| grafana | `public/app/features/explore/Logs/LogsTable.tsx` | verified |  |
| grafana | `public/app/features/explore/state/utils.ts` | verified |  |
| grafana | `public/app/features/geo/editor/GazetteerPathEditor.tsx` | verified |  |
| grafana | `public/app/features/logs/components/fieldSelector/FieldSelector.tsx` | verified |  |
| grafana | `public/app/plugins/panel/barchart/quadtree.ts` | verified |  |
| grafana | `public/app/plugins/panel/canvas/components/CanvasContextMenu.tsx` | verified |  |
| prysm | `beacon-chain/das/needs_test.go` | verified |  |
| prysm | `beacon-chain/db/filesystem/pruner_test.go` | verified |  |
| prysm | `beacon-chain/execution/log_processing.go` | verified |  |
| prysm | `beacon-chain/state/state-native/setters_attestation_test.go` | verified |  |
| prysm | `proto/engine/v1/engine.ssz.go` | verified |  |
| prysm | `proto/prysm/v1alpha1/attestation_fuzz_test.go` | verified |  |
| prysm | `testing/spectest/mainnet/gloas__rewards_test.go` | verified |  |
| prysm | `testing/spectest/minimal/altair__epoch_processing__historical_roots_update_test.go` | verified |  |
| prysm | `testing/spectest/minimal/deneb__finality__finality_test.go` | verified |  |
| prysm | `validator/rpc/beacon_test.go` | verified |  |
