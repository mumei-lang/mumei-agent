# Target OSS no-LLM dogfooding audit — continuation 429 (batch 430)

Run: 2026-07-23T01:55:12.583380+00:00

## Summary

- Files audited: 50
- Verified: 50
- Refuted: 0
- Unverifiable: 0

All sampled files passed no-LLM verification; no new tool-side fixes were required.

## Sample details

| repo | file | status | notes |
|------|------|--------|-------|
| go | `src/cmd/compile/internal/ssa/licm.go` | verified |  |
| go | `src/cmd/internal/objabi/line.go` | verified |  |
| go | `src/cmd/link/internal/mips/asm.go` | verified |  |
| go | `src/encoding/json/scanner_test.go` | verified |  |
| go | `src/go/internal/srcimporter/srcimporter_test.go` | verified |  |
| go | `src/html/example_test.go` | verified |  |
| go | `src/internal/routebsd/message_freebsd_test.go` | verified |  |
| go | `src/internal/syscall/unix/sysnum_linux_386.go` | verified |  |
| go | `src/log/slog/multi_handler_test.go` | verified |  |
| go | `src/math/rand/race_test.go` | verified |  |
| go | `src/net/textproto/writer_test.go` | verified |  |
| go | `src/runtime/sys_loong64.go` | verified |  |
| go | `src/runtime/traceevent.go` | verified |  |
| go | `src/strings/strings_test.go` | verified |  |
| go | `src/syscall/zsysnum_openbsd_arm.go` | verified |  |
| go | `src/testing/example_loop_test.go` | verified |  |
| go | `test/dwarf/dwarf.dir/z10.go` | verified |  |
| go | `test/fixedbugs/issue59709.dir/dcache.go` | verified |  |
| go | `test/fixedbugs/issue77534.go` | verified |  |
| go | `test/varerr.go` | verified |  |
| grafana | `apps/iam/pkg/apis/iam/v0alpha1/team_client_gen.go` | verified |  |
| grafana | `apps/provisioning/pkg/connection/github/client_mock.go` | verified |  |
| grafana | `packages/grafana-runtime/src/components/FolderPicker.tsx` | verified |  |
| grafana | `packages/grafana-schema/src/raw/composable/piechart/panelcfg/x/types.gen.ts` | verified |  |
| grafana | `packages/grafana-ui/src/components/DataSourceSettings/TLSAuthSettings.tsx` | verified |  |
| grafana | `packages/grafana-ui/src/components/Forms/RadioButtonGroup/RadioButtonGroup.tsx` | verified |  |
| grafana | `packages/grafana-ui/src/components/MatchersUI/fieldMatchersUI.ts` | verified |  |
| grafana | `packages/grafana-ui/src/components/RadialGauge/utils.ts` | verified |  |
| grafana | `packages/grafana-ui/src/components/Table/TableRT/FooterRow.tsx` | verified |  |
| grafana | `pkg/api/signup.go` | verified |  |
| grafana | `pkg/expr/query_convert.go` | verified |  |
| grafana | `pkg/infra/remotecache/redis_storage.go` | verified |  |
| grafana | `pkg/registry/apis/folders/sub_children_test.go` | verified |  |
| grafana | `pkg/registry/apps/annotation/observability.go` | verified |  |
| grafana | `pkg/services/authz/rollout_test.go` | verified |  |
| grafana | `pkg/services/authz/zanzana/common/translations.go` | verified |  |
| grafana | `pkg/services/authz/zanzana/store/migration/migrator_test.go` | verified |  |
| grafana | `pkg/services/ngalert/notifier/crypto.go` | verified |  |
| grafana | `pkg/storage/unified/migrations/testcases/playlists.go` | verified |  |
| grafana | `pkg/tsdb/grafana-testdata-datasource/sims/waveform.go` | verified |  |
| grafana | `public/app/features/alerting/unified/components/contact-points/DuplicateMessageTemplate.tsx` | verified |  |
| grafana | `public/app/features/alerting/unified/components/rule-editor/CustomAnnotationHeaderField.tsx` | verified |  |
| grafana | `public/app/features/browse-dashboards/components/TagsCell.tsx` | verified |  |
| grafana | `public/app/features/gops/configuration-tracker/alerting/hooks.ts` | verified |  |
| grafana | `public/app/features/provisioning/Job/JobAlerts.tsx` | verified |  |
| grafana | `public/app/features/provisioning/components/Folders/ProvisionedFolderPreviewBanner.tsx` | verified |  |
| grafana | `public/app/features/provisioning/hooks/useRepositoryAllJobs.ts` | verified |  |
| grafana | `public/app/plugins/datasource/cloudwatch/mocks/metric-math-test-data/afterFunctionQuery.ts` | verified |  |
| grafana | `public/app/plugins/panel/text/textPanelMigrationHandler.ts` | verified |  |
| grafana | `public/app/plugins/panel/welcome/module.ts` | verified |  |
