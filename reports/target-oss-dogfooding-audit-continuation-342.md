# Target OSS no-LLM dogfooding audit — continuation 342 (batch 343)

Run: 2026-07-22T20:49:27.391383+00:00

## Summary

- Files audited: 50
- Verified: 50
- Refuted: 0
- Unverifiable: 0

All sampled files passed no-LLM verification; no new tool-side fixes were required.

## Sample details

| repo | file | status | notes |
|------|------|--------|-------|
| go | `src/archive/tar/reader.go` | verified |  |
| go | `src/cmd/asm/internal/arch/riscv64.go` | verified |  |
| go | `src/cmd/cgo/internal/test/issue43639.go` | verified |  |
| go | `src/cmd/internal/objabi/pkgspecial.go` | verified |  |
| go | `src/crypto/tls/ech_test.go` | verified |  |
| go | `src/crypto/tls/handshake_test.go` | verified |  |
| go | `src/go/scanner/scanner_test.go` | verified |  |
| go | `src/internal/fuzz/minimize.go` | verified |  |
| go | `src/net/http/internal/httpcommon/httpcommon.go` | verified |  |
| go | `src/net/smtp/smtp_test.go` | verified |  |
| go | `src/os/executable_windows.go` | verified |  |
| go | `test/codegen/issue69635.go` | verified |  |
| go | `test/fixedbugs/bug327.go` | verified |  |
| go | `test/fixedbugs/issue53619.go` | verified |  |
| grafana | `apps/dashboard/pkg/apis/dashboard/v0alpha1/dashboard_schema_gen.go` | verified |  |
| grafana | `apps/dashboard/pkg/apis/dashboard/v0alpha1/snapshot_spec_gen.go` | verified |  |
| grafana | `apps/logsdrilldown/pkg/apis/logsdrilldown/v1alpha1/logsdrilldown_spec_gen.go` | verified |  |
| grafana | `apps/provisioning/pkg/safepath/path.go` | verified |  |
| grafana | `packages/grafana-api-clients/src/scripts/generate-rtk-apis.ts` | verified |  |
| grafana | `packages/grafana-ui/src/types/slate-react.d.ts` | verified |  |
| grafana | `pkg/api/grafana_com_proxy.go` | verified |  |
| grafana | `pkg/plugins/repo/service.go` | verified |  |
| grafana | `pkg/registry/apis/iam/globalrole/inmemory/models_test.go` | verified |  |
| grafana | `pkg/registry/apis/provisioning/jobs/sync/sync_condition.go` | verified |  |
| grafana | `pkg/registry/apis/userstorage/register.go` | verified |  |
| grafana | `pkg/services/ngalert/notifier/legacy_storage/imported_test.go` | verified |  |
| grafana | `pkg/storage/unified/resource/storage_backend.go` | verified |  |
| grafana | `pkg/storage/unified/search/disk_cleanup_test.go` | verified |  |
| grafana | `pkg/storage/unified/sql/continue.go` | verified |  |
| grafana | `pkg/tests/apis/provisioning/foldermetadata/update_folder_metadata_test.go` | verified |  |
| grafana | `pkg/tsdb/cloudwatch/models/resources/dimension_values_request_test.go` | verified |  |
| grafana | `public/app/core/services/journey/JourneyTrackerImpl.ts` | verified |  |
| grafana | `public/app/features/alerting/unified/components/export/GrafanaReceiversExporter.tsx` | verified |  |
| grafana | `public/app/features/alerting/unified/components/rule-viewer/DeleteModal.tsx` | verified |  |
| grafana | `public/app/features/alerting/unified/utils/k8s/constants.ts` | verified |  |
| grafana | `public/app/features/dashboard-scene/embedding/EmbeddedDashboardTestPage.tsx` | verified |  |
| grafana | `public/app/features/dashboard-scene/panel-edit/LibraryPanelEditModals.tsx` | verified |  |
| grafana | `public/app/features/explore/ContentOutline/ContentOutline.tsx` | verified |  |
| grafana | `public/app/features/explore/TraceView/useChildrenState.ts` | verified |  |
| grafana | `public/app/features/variables/custom/adapter.ts` | verified |  |
| prysm | `beacon-chain/core/blocks/log.go` | verified |  |
| prysm | `beacon-chain/core/transition/gloas.go` | verified |  |
| prysm | `beacon-chain/core/transition/state_fuzz_test.go` | verified |  |
| prysm | `beacon-chain/operations/attestations/attmap/map.go` | verified |  |
| prysm | `beacon-chain/state/stateutil/field_root_validator.go` | verified |  |
| prysm | `beacon-chain/sync/rpc_ping.go` | verified |  |
| prysm | `monitoring/tracing/tracer.go` | verified |  |
| prysm | `testing/spectest/mainnet/fulu__operations__attestation_test.go` | verified |  |
| prysm | `testing/spectest/shared/capella/ssz_static/ssz_static.go` | verified |  |
| prysm | `time/slots/slottime_test.go` | verified |  |
