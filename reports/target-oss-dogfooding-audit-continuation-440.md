# Target OSS no-LLM dogfooding audit — continuation 440 (batch 441)

Run: 2026-07-23T02:30:02.039335+00:00

## Summary

- Files audited: 50
- Verified: 50
- Refuted: 0
- Unverifiable: 0

All sampled files passed no-LLM verification; no new tool-side fixes were required.

## Sample details

| repo | file | status | notes |
|------|------|--------|-------|
| go | `src/cmd/compile/internal/inline/inlheur/score_callresult_uses.go` | verified |  |
| go | `src/cmd/compile/internal/noder/lex.go` | verified |  |
| go | `src/cmd/link/internal/ld/ar.go` | verified |  |
| go | `src/cmd/nm/script_test.go` | verified |  |
| go | `src/crypto/hmac/hmac_test.go` | verified |  |
| go | `src/crypto/internal/boring/boring_test.go` | verified |  |
| go | `src/go/parser/short_test.go` | verified |  |
| go | `src/internal/fuzz/mutators_byteslice_test.go` | verified |  |
| go | `src/internal/pkgbits/codes.go` | verified |  |
| go | `src/internal/pkgbits/pkgbits_test.go` | verified |  |
| go | `src/internal/profile/profile.go` | verified |  |
| go | `src/log/slog/multi_handler.go` | verified |  |
| go | `src/os/exec/exec_test.go` | verified |  |
| go | `src/os/export_freebsd_test.go` | verified |  |
| go | `src/sync/oncefunc.go` | verified |  |
| go | `test/escape_selfassign.go` | verified |  |
| go | `test/fixedbugs/bug097.go` | verified |  |
| go | `test/fixedbugs/issue4099.go` | verified |  |
| go | `test/label1.go` | verified |  |
| go | `test/typeparam/issue47514c.dir/a.go` | verified |  |
| go | `test/typeparam/issue49547.go` | verified |  |
| go | `test/typeparam/stringerimp.go` | verified |  |
| grafana | `apps/alerting/notifications/pkg/apis/alertingnotifications/v1beta1/templategroup_schema_gen.go` | verified |  |
| grafana | `apps/dashboard/pkg/migration/schemaversion/v42_test.go` | verified |  |
| grafana | `apps/live/pkg/apis/live/v1alpha1/channel_spec_gen.go` | verified |  |
| grafana | `apps/preferences/pkg/apis/preferences/v1/doc.go` | verified |  |
| grafana | `packages/grafana-api-clients/src/clients/rtkq/notifications.alerting/v1beta1/endpoints.gen.ts` | verified |  |
| grafana | `packages/grafana-api-clients/src/clients/rtkq/playlist/v1/baseAPI.ts` | verified |  |
| grafana | `packages/grafana-ui/src/components/Card/Card.tsx` | verified |  |
| grafana | `packages/grafana-ui/src/components/DateTimePickers/TimeRangeInput.tsx` | verified |  |
| grafana | `packages/grafana-ui/src/components/DateTimePickers/TimeZonePicker/TimeZoneOption.tsx` | verified |  |
| grafana | `pkg/registry/apis/provisioning/jobs/move/worker.go` | verified |  |
| grafana | `pkg/registry/apis/provisioning/jobs/queue_mock.go` | verified |  |
| grafana | `pkg/registry/apis/provisioning/webhooks/pullrequest/worker_test.go` | verified |  |
| grafana | `pkg/services/authn/authnimpl/sync/groups_claim_sync.go` | verified |  |
| grafana | `pkg/services/ngalert/notifier/redis_peer_test.go` | verified |  |
| grafana | `pkg/services/ngalert/state/historian/query.go` | verified |  |
| grafana | `pkg/services/team/teamimpl/team.go` | verified |  |
| grafana | `public/app/features/alerting/unified/components/RuleNotificationSection.tsx` | verified |  |
| grafana | `public/app/features/connections/tabs/ConnectData/ConnectDataLegacy.tsx` | verified |  |
| grafana | `public/app/features/dashboard-scene/edit-pane/outline/DashboardOutline.tsx` | verified |  |
| grafana | `public/app/features/dashboard-scene/mutation-api/commands/getLayout.ts` | verified |  |
| grafana | `public/app/features/dashboard-scene/settings/DashboardTemplateEditView.tsx` | verified |  |
| grafana | `public/app/features/explore/TraceView/components/TracePageHeader/SpanGraph/CanvasSpanGraph.tsx` | verified |  |
| grafana | `public/app/features/library-panels/components/LibraryPanelsSearch/LibraryPanelsSearch.tsx` | verified |  |
| grafana | `public/app/features/logs/components/panel/LogLineDetailsComponent.tsx` | verified |  |
| grafana | `public/app/features/plugins/admin/constants.ts` | verified |  |
| grafana | `public/app/features/query/components/QueryEditorRow.tsx` | verified |  |
| grafana | `public/app/plugins/panel/timeseries/utils.ts` | verified |  |
| grafana | `public/swagger/K8sNameLookup.tsx` | verified |  |
