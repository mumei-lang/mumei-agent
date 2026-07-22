# Target OSS no-LLM dogfooding audit — continuation 355 (batch 356)

Run: 2026-07-22T21:23:05.911440+00:00

## Summary

- Files audited: 50
- Verified: 50
- Refuted: 0
- Unverifiable: 0

All sampled files passed no-LLM verification; no new tool-side fixes were required.

## Sample details

| repo | file | status | notes |
|------|------|--------|-------|
| go | `src/cmd/cgo/doc.go` | verified |  |
| go | `src/cmd/go/internal/vcweb/auth.go` | verified |  |
| go | `src/crypto/internal/fips140/bigmod/nat.go` | verified |  |
| go | `src/crypto/internal/fips140/mlkem/cast.go` | verified |  |
| go | `src/encoding/gob/dump.go` | verified |  |
| go | `src/go/doc/doc_test.go` | verified |  |
| go | `src/internal/syscall/unix/fallocate_bsd_arm.go` | verified |  |
| go | `src/runtime/os_linux_mips64x.go` | verified |  |
| go | `test/dwarf/linedirectives.go` | verified |  |
| go | `test/fixedbugs/bug189.go` | verified |  |
| go | `test/fixedbugs/issue15926.go` | verified |  |
| go | `test/fixedbugs/issue29610.go` | verified |  |
| go | `test/func.go` | verified |  |
| go | `test/prove_constant_folding.go` | verified |  |
| go | `test/typeparam/issue48716.dir/main.go` | verified |  |
| grafana | `apps/iam/pkg/app/app.go` | verified |  |
| grafana | `apps/secret/pkg/apis/secret_manifest.go` | verified |  |
| grafana | `devenv/dev-dashboards/dashboards.go` | verified |  |
| grafana | `pkg/apimachinery/apis/common/v0alpha1/types.go` | verified |  |
| grafana | `pkg/expr/mathexp/types.go` | verified |  |
| grafana | `pkg/infra/log/text/text_logger.go` | verified |  |
| grafana | `pkg/registry/apps/alerting/rules/recordingrule/compat_test.go` | verified |  |
| grafana | `pkg/server/nats_subscriber_adapter.go` | verified |  |
| grafana | `pkg/services/contexthandler/model/model.go` | verified |  |
| grafana | `pkg/services/ngalert/api/lotex_prom_test.go` | verified |  |
| grafana | `pkg/services/supportbundles/supportbundlesimpl/store.go` | verified |  |
| grafana | `pkg/storage/unified/search/embed/dashboard/extractor.go` | verified |  |
| grafana | `pkg/tests/apis/provisioning/foldermetadata/full_sync_invalid_uid_chars_test.go` | verified |  |
| grafana | `pkg/tsdb/cloudwatch/models/resources/resource_request_test.go` | verified |  |
| grafana | `public/app/core/components/AppChrome/ExtensionSidebar/ExtensionToolbarItemButton.tsx` | verified |  |
| grafana | `public/app/core/components/AppChrome/TopBar/SignInLink.tsx` | verified |  |
| grafana | `public/app/features/alerting/unified/components/Expression.tsx` | verified |  |
| grafana | `public/app/features/alerting/unified/components/rules/central-state-history/CentralAlertHistorySceneExposedComponent.tsx` | verified |  |
| grafana | `public/app/features/alerting/unified/components/silences/SilencePeriod.tsx` | verified |  |
| grafana | `public/app/features/alerting/unified/rule-list/AlertsActivityOptOutModal.tsx` | verified |  |
| grafana | `public/app/features/annotations/events_processing.ts` | verified |  |
| grafana | `public/app/features/home/HomePage.tsx` | verified |  |
| grafana | `public/app/features/migrate-to-cloud/onprem/Page.tsx` | verified |  |
| grafana | `public/app/plugins/datasource/cloudwatch/components/QueryEditor/MetricsQueryEditor/DynamicLabelsField.tsx` | verified |  |
| grafana | `public/swagger/index.tsx` | verified |  |
| prysm | `beacon-chain/blockchain/kzg/kzg.go` | verified |  |
| prysm | `consensus-types/primitives/slot.go` | verified |  |
| prysm | `testing/endtoend/geth_deps.go` | verified |  |
| prysm | `testing/spectest/minimal/capella__rewards__rewards_test.go` | verified |  |
| prysm | `testing/spectest/minimal/electra__operations__attester_slashing_test.go` | verified |  |
| prysm | `testing/spectest/shared/altair/ssz_static/ssz_static.go` | verified |  |
| prysm | `testing/spectest/shared/common/forkchoice/type.go` | verified |  |
| prysm | `tools/analyzers/modernize/appendclipped/analyzer.go` | verified |  |
| prysm | `validator/accounts/doc.go` | verified |  |
| prysm | `validator/client/payload_availability_test.go` | verified |  |
