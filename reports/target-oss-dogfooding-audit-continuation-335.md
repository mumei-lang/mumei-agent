# Target OSS no-LLM dogfooding audit — continuation 335 (batch 336)

Run: 2026-07-22T20:22:06.039436+00:00

## Summary

- Files audited: 50
- Verified: 50
- Refuted: 0
- Unverifiable: 0

All sampled files passed no-LLM verification; no new tool-side fixes were required.

## Sample details

| repo | file | status | notes |
|------|------|--------|-------|
| go | `src/hash/crc32/gen.go` | verified |  |
| go | `src/internal/syscall/windows/psapi_windows.go` | verified |  |
| go | `src/net/cgo_unix_test.go` | verified |  |
| go | `src/net/http/pattern_test.go` | verified |  |
| go | `src/net/sendfile_unix_test.go` | verified |  |
| go | `src/os/sys_js.go` | verified |  |
| go | `src/syscall/pwd_plan9.go` | verified |  |
| go | `test/codegen/append_freegc.go` | verified |  |
| go | `test/fixedbugs/issue17194.go` | verified |  |
| go | `test/fixedbugs/issue22389.go` | verified |  |
| go | `test/fixedbugs/issue31636.dir/a.go` | verified |  |
| go | `test/fixedbugs/issue49143.dir/a.go` | verified |  |
| go | `test/fixedbugs/issue9537.go` | verified |  |
| go | `test/gc1.go` | verified |  |
| go | `test/typeparam/issue48462.go` | verified |  |
| grafana | `apps/alerting/notifications/pkg/apis/alertingnotifications/v0alpha1/timeinterval_spec_gen.go` | verified |  |
| grafana | `apps/dashboard/pkg/migration/conversion/v0.go` | verified |  |
| grafana | `apps/dashboard/pkg/migration/schemaversion/v12.go` | verified |  |
| grafana | `e2e-playwright/test-plugins/grafana-test-datasource/components/QueryEditor.tsx` | verified |  |
| grafana | `packages/grafana-data/src/transformations/transformers/organize.ts` | verified |  |
| grafana | `packages/grafana-ui/src/components/Table/TableNG/utils.ts` | verified |  |
| grafana | `packages/grafana-ui/src/components/VizLegend/FacetedLabelsFilter.tsx` | verified |  |
| grafana | `pkg/registry/apis/provisioning/controller/token_refresh_test.go` | verified |  |
| grafana | `pkg/services/authz/rbac/tree.go` | verified |  |
| grafana | `pkg/services/featuremgmt/toggles_gen.go` | verified |  |
| grafana | `pkg/services/pluginsintegration/angulardetectorsprovider/gcom_test.go` | verified |  |
| grafana | `pkg/services/pluginsintegration/keyretriever/dynamic/dynamic_retriever.go` | verified |  |
| grafana | `pkg/storage/unified/resource/tenant_deleter.go` | verified |  |
| grafana | `pkg/storage/unified/sql/sqltemplate/dialect_postgresql_test.go` | verified |  |
| grafana | `pkg/tests/apis/provisioning/foldermetadata/fixfoldermetadatajob_test.go` | verified |  |
| grafana | `pkg/tsdb/grafana-postgresql-datasource/sqleng/errors.go` | verified |  |
| grafana | `pkg/tsdb/influxdb/healthcheck_test.go` | verified |  |
| grafana | `public/app/api/clients/dashboard/v2beta1/index.ts` | verified |  |
| grafana | `public/app/core/components/TagFilter/TagFilter.tsx` | verified |  |
| grafana | `public/app/core/components/help/HelpModal.tsx` | verified |  |
| grafana | `public/app/features/alerting/unified/components/export/GrafanaRulesExporter.tsx` | verified |  |
| grafana | `public/app/features/logs/components/fieldSelector/ActiveFields.tsx` | verified |  |
| grafana | `public/app/plugins/datasource/grafana/datasource.ts` | verified |  |
| grafana | `public/app/plugins/panel/logstable/types.ts` | verified |  |
| grafana | `public/app/plugins/panel/welcome/Welcome.tsx` | verified |  |
| prysm | `beacon-chain/core/requests/consolidations.go` | verified |  |
| prysm | `cmd/validator/accounts/list.go` | verified |  |
| prysm | `container/slice/ranges.go` | verified |  |
| prysm | `encoding/bytesutil/bytes_legacy.go` | verified |  |
| prysm | `testing/spectest/mainnet/capella__light_client__single_merkle_proof_test.go` | verified |  |
| prysm | `testing/spectest/mainnet/deneb__operations__proposer_slashing_test.go` | verified |  |
| prysm | `testing/spectest/mainnet/gloas__epoch_processing__pending_deposits_test.go` | verified |  |
| prysm | `testing/spectest/mainnet/phase0__shuffling__core_shuffle_test.go` | verified |  |
| prysm | `testing/spectest/minimal/fulu__epoch_processing__pending_consolidations_test.go` | verified |  |
| prysm | `validator/client/grpc-api/grpc_validator_client_test.go` | verified |  |
