# Target OSS no-LLM dogfooding audit — continuation 486 (batch 487)

Run: 2026-07-23T05:50:14.311410+00:00

## Summary

- Files audited: 50
- Verified: 50
- Refuted: 0
- Unverifiable: 0

All sampled files passed no-LLM verification; no new tool-side fixes were required.

## Sample details

| repo | file | status | notes |
|------|------|--------|-------|
| go | `src/cmd/cgo/internal/test/issue76861/a.go` | verified |  |
| go | `src/cmd/internal/obj/textflag.go` | verified |  |
| go | `src/debug/buildinfo/buildinfo_test.go` | verified |  |
| go | `src/encoding/json/internal/jsonwire/wire.go` | verified |  |
| go | `src/encoding/json/v2/arshal_test.go` | verified |  |
| go | `src/encoding/json/v2_indent.go` | verified |  |
| go | `src/internal/bytealg/compare_generic.go` | verified |  |
| go | `src/internal/goos/zgoos_freebsd.go` | verified |  |
| go | `src/internal/poll/iovec_unix.go` | verified |  |
| go | `src/internal/runtime/atomic/doc.go` | verified |  |
| go | `src/internal/syscall/unix/nonblocking_wasip1.go` | verified |  |
| go | `src/internal/testenv/testenv_notwin.go` | verified |  |
| go | `src/net/cgo_aix.go` | verified |  |
| go | `src/slices/example_test.go` | verified |  |
| go | `src/syscall/zsyscall_plan9_arm.go` | verified |  |
| go | `test/chan/select3.go` | verified |  |
| go | `test/cmp6.go` | verified |  |
| go | `test/fixedbugs/issue15572.go` | verified |  |
| go | `test/fixedbugs/issue19201.go` | verified |  |
| go | `test/fixedbugs/issue24755.go` | verified |  |
| go | `test/fixedbugs/issue30566b.go` | verified |  |
| go | `test/fixedbugs/issue50788.go` | verified |  |
| go | `test/fixedbugs/issue68264.go` | verified |  |
| go | `test/range.go` | verified |  |
| go | `test/typeparam/issue51765.go` | verified |  |
| grafana | `packages/grafana-plugin-configs/utils.ts` | verified |  |
| grafana | `packages/grafana-ui/src/components/Icon/Icon.tsx` | verified |  |
| grafana | `packages/grafana-ui/src/components/Table/TableNG/TableNG.tsx` | verified |  |
| grafana | `packages/grafana-ui/src/slate-plugins/selection_shortcuts.ts` | verified |  |
| grafana | `pkg/infra/nats/enabled_test.go` | verified |  |
| grafana | `pkg/middleware/csp.go` | verified |  |
| grafana | `pkg/registry/apis/iam/resource_permission_hooks.go` | verified |  |
| grafana | `pkg/registry/apis/provisioning/jobs/driver.go` | verified |  |
| grafana | `pkg/services/ngalert/api/forking_alertmanager.go` | verified |  |
| grafana | `pkg/services/sqlstore/migrations/ualert/alert_rule_group_collation.go` | verified |  |
| grafana | `pkg/storage/unified/migrations/registry.go` | verified |  |
| grafana | `pkg/tests/apis/datasource/proxy_test.go` | verified |  |
| grafana | `pkg/tests/apis/provisioning/git/helper_test.go` | verified |  |
| grafana | `pkg/tsdb/cloudwatch/data_sources_test.go` | verified |  |
| grafana | `pkg/tsdb/cloudwatch/external_id_test.go` | verified |  |
| grafana | `public/app/core/components/NestedFolderPicker/useTreeInteractions.ts` | verified |  |
| grafana | `public/app/features/dashboard-scene/utils/drilldownUtils.ts` | verified |  |
| grafana | `public/app/features/dashboard/components/ShareModal/ShareSnapshot.tsx` | verified |  |
| grafana | `public/app/features/logs/components/panel/usePopoverMenu.ts` | verified |  |
| grafana | `public/app/features/logs/logsModel.ts` | verified |  |
| grafana | `public/app/features/provisioning/components/Shared/RepoInvalidStateBanner.tsx` | verified |  |
| grafana | `public/app/features/provisioning/constants.ts` | verified |  |
| grafana | `public/app/features/variables/shared/testing/variableBuilder.ts` | verified |  |
| grafana | `public/app/plugins/panel/geomap/layers/basemaps/generic.ts` | verified |  |
| grafana | `public/app/plugins/panel/piechart/module.tsx` | verified |  |
