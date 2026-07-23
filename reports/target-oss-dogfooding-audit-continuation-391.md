# Target OSS no-LLM dogfooding audit — continuation 391 (batch 392)

Run: 2026-07-23T00:09:58.055324+00:00

## Summary

- Files audited: 50
- Verified: 50
- Refuted: 0
- Unverifiable: 0

All sampled files passed no-LLM verification; no new tool-side fixes were required.

## Sample details

| repo | file | status | notes |
|------|------|--------|-------|
| go | `src/cmd/compile/internal/ssa/lca_test.go` | verified |  |
| go | `src/cmd/compile/internal/test/reproduciblebuilds_test.go` | verified |  |
| go | `src/cmd/cover/export_test.go` | verified |  |
| go | `src/cmd/link/internal/s390x/obj.go` | verified |  |
| go | `src/compress/flate/huffman_bit_writer_test.go` | verified |  |
| go | `src/crypto/internal/fips140/export_test.go` | verified |  |
| go | `src/encoding/binary/varint.go` | verified |  |
| go | `src/internal/poll/fd_windows_test.go` | verified |  |
| go | `src/net/internal/socktest/sys_cloexec.go` | verified |  |
| go | `src/runtime/defs_linux_mips64x.go` | verified |  |
| go | `src/runtime/vdso_freebsd_arm64.go` | verified |  |
| go | `src/sort/example_multi_test.go` | verified |  |
| go | `src/syscall/zsyscall_linux_mipsle.go` | verified |  |
| go | `test/fixedbugs/bug047.go` | verified |  |
| go | `test/fixedbugs/issue54280.go` | verified |  |
| go | `test/interface/struct.go` | verified |  |
| go | `test/typeparam/listimp2.dir/a.go` | verified |  |
| go | `test/typeparam/orderedmap.go` | verified |  |
| grafana | `apps/dashboard/pkg/migration/schemaversion/v28.go` | verified |  |
| grafana | `apps/iam/pkg/apis/iam/v0alpha1/teamlbacrule_object_gen.go` | verified |  |
| grafana | `apps/logsdrilldown/pkg/apis/logsdrilldown/v1beta1/logsdrilldowndefaultcolumns_object_gen.go` | verified |  |
| grafana | `apps/provisioning/pkg/repository/lister_test.go` | verified |  |
| grafana | `devenv/docker/blocks/stateful_webhook/main.go` | verified |  |
| grafana | `jest.config.js` | verified |  |
| grafana | `packages/grafana-data/src/transformations/transformers/filterByValue.ts` | verified |  |
| grafana | `packages/grafana-i18n/src/i18n.tsx` | verified |  |
| grafana | `packages/grafana-sql/src/utils/sql.utils.ts` | verified |  |
| grafana | `packages/grafana-ui/src/components/ThemeDemos/ThemeDemo.tsx` | verified |  |
| grafana | `pkg/plugins/manager/pipeline/initialization/initialization.go` | verified |  |
| grafana | `pkg/registry/apis/folders/sub_children.go` | verified |  |
| grafana | `pkg/registry/apis/query/errors_test.go` | verified |  |
| grafana | `pkg/services/apiserver/appinstaller/installer_test.go` | verified |  |
| grafana | `pkg/tests/api/shorturl/short_url_test.go` | verified |  |
| grafana | `pkg/util/xorm/error.go` | verified |  |
| grafana | `public/app/core/components/AppChrome/MegaMenu/MegaMenuHeader.tsx` | verified |  |
| grafana | `public/app/core/time_series2.ts` | verified |  |
| grafana | `public/app/features/alerting/unified/components/AlertLabelDropdown.tsx` | verified |  |
| grafana | `public/app/features/alerting/unified/components/alert-groups/ReceiverFilter.tsx` | verified |  |
| grafana | `public/app/features/alerting/unified/components/silences/SilencesTable.tsx` | verified |  |
| grafana | `public/app/features/alerting/unified/rule-list/components/DataSourceSection.tsx` | verified |  |
| grafana | `public/app/features/auth-config/state/actions.ts` | verified |  |
| grafana | `public/app/features/dashboard-scene/edit-pane/dashboard/DraggableList.tsx` | verified |  |
| grafana | `public/app/features/dashboard-scene/scene/GoToSnapshotOriginButton.tsx` | verified |  |
| grafana | `public/app/features/explore/RichHistory/RichHistoryStarredTab.tsx` | verified |  |
| grafana | `public/app/features/explore/TraceView/useHoverIndentGuide.ts` | verified |  |
| grafana | `public/app/features/library-panels/components/LibraryPanelsView/actions.ts` | verified |  |
| grafana | `public/app/features/provisioning/Wizard/BootstrapStepCardIcons.tsx` | verified |  |
| grafana | `public/app/plugins/panel/canvas/components/connections/ConnectionSVG.tsx` | verified |  |
| grafana | `public/app/plugins/panel/logstable/panelcfg.gen.ts` | verified |  |
| grafana | `public/app/types/acl.ts` | verified |  |
