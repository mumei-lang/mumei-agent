# Target OSS no-LLM dogfooding audit — continuation 522 (batch 523)

Run: 2026-07-23T08:04:59.591366+00:00

## Summary

- Files audited: 50
- Verified: 50
- Refuted: 0
- Unverifiable: 0

All sampled files passed no-LLM verification; no new tool-side fixes were required.

## Sample details

| repo | file | status | notes |
|------|------|--------|-------|
| go | `src/cmd/cover/doc.go` | verified |  |
| go | `src/cmd/go/internal/doc/signal_unix.go` | verified |  |
| go | `src/cmd/go/internal/telemetrystats/version_unix.go` | verified |  |
| go | `src/cmd/internal/obj/s390x/objz.go` | verified |  |
| go | `src/crypto/internal/fips140/sha256/sha256block.go` | verified |  |
| go | `src/encoding/json/v2/arshal_time_test.go` | verified |  |
| go | `src/go/format/example_test.go` | verified |  |
| go | `src/go/types/object.go` | verified |  |
| go | `src/internal/profile/proto.go` | verified |  |
| go | `src/internal/runtime/math/math_test.go` | verified |  |
| go | `src/io/fs/readlink_test.go` | verified |  |
| go | `src/math/exp.go` | verified |  |
| go | `src/math/rand/v2/pcg_test.go` | verified |  |
| go | `src/net/http/internal/ascii/print.go` | verified |  |
| go | `src/net/http/internal/http2/errors_test.go` | verified |  |
| go | `src/os/fifo_test.go` | verified |  |
| go | `src/runtime/race/timer_test.go` | verified |  |
| go | `test/codegen/spectre.go` | verified |  |
| go | `test/fixedbugs/bug381.go` | verified |  |
| go | `test/fixedbugs/issue23179.go` | verified |  |
| go | `test/fixedbugs/issue4610.go` | verified |  |
| go | `test/fixedbugs/issue46725.go` | verified |  |
| go | `test/fixedbugs/issue79886.go` | verified |  |
| go | `test/inline_sync.go` | verified |  |
| grafana | `packages/grafana-ui/src/components/Table/TableNG/refactored/TableNested.tsx` | verified |  |
| grafana | `pkg/api/org_invite.go` | verified |  |
| grafana | `pkg/clientauth/roundtripper.go` | verified |  |
| grafana | `pkg/plugins/manager/signature/signature.go` | verified |  |
| grafana | `pkg/registry/apis/iam/register_test.go` | verified |  |
| grafana | `pkg/services/auth/authimpl/external_session_store_test.go` | verified |  |
| grafana | `pkg/services/dashboards/service/metrics.go` | verified |  |
| grafana | `pkg/services/navtree/navtreeimpl/applinks_test.go` | verified |  |
| grafana | `pkg/services/pluginsintegration/clientmiddleware/forward_id_middleware.go` | verified |  |
| grafana | `pkg/storage/unified/resource/search.go` | verified |  |
| grafana | `pkg/tests/apis/provisioning/classic_delete_test.go` | verified |  |
| grafana | `pkg/tests/apis/provisioning/git/webhook/webhook_test.go` | verified |  |
| grafana | `pkg/tests/apis/provisioning/jobs/pulljob_folder_depth_test.go` | verified |  |
| grafana | `pkg/tsdb/azuremonitor/schema_metric_metadata.go` | verified |  |
| grafana | `pkg/tsdb/cloudwatch/models/cloudwatch_query.go` | verified |  |
| grafana | `public/app/core/components/Select/DashboardPicker.tsx` | verified |  |
| grafana | `public/app/features/alerting/unified/components/rule-editor/alert-rule-form/simplifiedRouting/route-settings/RouteTimings.tsx` | verified |  |
| grafana | `public/app/features/browse-dashboards/hooks/useQuotaLimits.ts` | verified |  |
| grafana | `public/app/features/dashboard-scene/panel-edit/PanelEditNext/QueryEditor/Header/QueryActionsMenu.tsx` | verified |  |
| grafana | `public/app/features/dashboard-scene/scene/new-toolbar/actions/SaveDashboard.tsx` | verified |  |
| grafana | `public/app/features/dashboard-scene/settings/variables/editors/QueryVariableEditor/ModalEditor.tsx` | verified |  |
| grafana | `public/app/features/explore/TraceView/components/types/trace.ts` | verified |  |
| grafana | `public/app/features/library-panels/components/LibraryPanelInfo/LibraryPanelInfo.tsx` | verified |  |
| grafana | `public/app/features/logs/components/panel/LogLine.tsx` | verified |  |
| grafana | `public/app/features/provisioning/Job/getJobMessage.ts` | verified |  |
| grafana | `public/app/plugins/datasource/azuremonitor/mocks/resourcePickerRows.ts` | verified |  |
