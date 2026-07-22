# Target OSS no-LLM dogfooding audit — continuation 322 (batch 323)

Run: 2026-07-22T19:36:42.881277+00:00

## Summary

- Files audited: 50
- Verified: 50
- Refuted: 0
- Unverifiable: 0

All sampled files passed no-LLM verification; no new tool-side fixes were required.

## Sample details

| repo | file | status | notes |
|------|------|--------|-------|
| go | `src/cmd/cgo/internal/test/issue7234_test.go` | verified |  |
| go | `src/cmd/compile/internal/ssa/stackalloc.go` | verified |  |
| go | `src/crypto/internal/fips140/subtle/constant_time.go` | verified |  |
| go | `src/html/template/url_test.go` | verified |  |
| go | `src/internal/goarch/zgoarch_arm64be.go` | verified |  |
| go | `src/internal/runtime/maps/table_debug.go` | verified |  |
| go | `src/mime/multipart/writer_test.go` | verified |  |
| go | `src/net/tcpconn_keepalive_solaris_test.go` | verified |  |
| go | `src/os/path.go` | verified |  |
| go | `src/runtime/note_js.go` | verified |  |
| go | `src/syscall/zerrors_linux_amd64.go` | verified |  |
| go | `test/fixedbugs/issue11362.go` | verified |  |
| go | `test/fixedbugs/issue32595.dir/b.go` | verified |  |
| go | `test/fixedbugs/issue43444.go` | verified |  |
| go | `test/fixedbugs/issue78404.go` | verified |  |
| go | `test/fixedbugs/issue8501.go` | verified |  |
| go | `test/typeparam/list.go` | verified |  |
| grafana | `apps/annotation/pkg/apis/annotation/v0alpha1/gettags_response_body_types_gen.go` | verified |  |
| grafana | `apps/annotation/pkg/app/config.go` | verified |  |
| grafana | `apps/dashboard/pkg/migration/schemaversion/v28_test.go` | verified |  |
| grafana | `apps/provisioning/pkg/apis/admission/pending_delete.go` | verified |  |
| grafana | `packages/grafana-data/src/transformations/transformers/rename.ts` | verified |  |
| grafana | `packages/grafana-ui/src/components/Segment/useExpandableLabel.tsx` | verified |  |
| grafana | `pkg/apimachinery/apis/common/v0alpha1/zz_generated.openapi.go` | verified |  |
| grafana | `pkg/expr/convert_to_full_long.go` | verified |  |
| grafana | `pkg/infra/httpclient/httpclientprovider/http_client_provider.go` | verified |  |
| grafana | `pkg/services/apikey/model.go` | verified |  |
| grafana | `pkg/services/apiserver/preferred_version.go` | verified |  |
| grafana | `pkg/services/team/teamapi/team_members_test.go` | verified |  |
| grafana | `pkg/services/team/teamimpl/legacy_team.go` | verified |  |
| grafana | `pkg/tsdb/cloudwatch/mocks/oam_client.go` | verified |  |
| grafana | `public/app/features/alerting/unified/components/InfoPausedRule.tsx` | verified |  |
| grafana | `public/app/features/alerting/unified/components/receivers/form/fields/StringArrayInput.tsx` | verified |  |
| grafana | `public/app/features/commandPalette/bucketQueryLength.ts` | verified |  |
| grafana | `public/app/features/dashboard-scene/scene/layout-default/DashboardGridItemVariableDependencyHandler.ts` | verified |  |
| grafana | `public/app/features/datasources/components/picker/DataSourceCardItem.tsx` | verified |  |
| grafana | `public/app/features/playlist/PlaylistForm.tsx` | verified |  |
| grafana | `public/app/features/provisioning/Wizard/hooks/useResourceStats.ts` | verified |  |
| grafana | `public/app/features/support-bundles/SupportBundles.tsx` | verified |  |
| grafana | `public/app/plugins/datasource/grafana-postgresql-datasource/module.ts` | verified |  |
| prysm | `api/grpc/grpcutils_test.go` | verified |  |
| prysm | `beacon-chain/blockchain/receive_execution_payload_envelope_test.go` | verified |  |
| prysm | `beacon-chain/db/pruner/pruner.go` | verified |  |
| prysm | `beacon-chain/rpc/prysm/beacon/validator_count.go` | verified |  |
| prysm | `beacon-chain/state/stateutil/compact_validator.go` | verified |  |
| prysm | `beacon-chain/sync/subscriber.go` | verified |  |
| prysm | `beacon-chain/verification/data_column_gloas_test.go` | verified |  |
| prysm | `testing/spectest/mainnet/gloas__sanity__blocks_test.go` | verified |  |
| prysm | `testing/spectest/minimal/altair__epoch_processing__randao_mixes_reset_test.go` | verified |  |
| prysm | `testing/util/fulu_block.go` | verified |  |
