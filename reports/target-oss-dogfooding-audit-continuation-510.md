# Target OSS no-LLM dogfooding audit — continuation 510 (batch 511)

Run: 2026-07-23T07:23:18.455299+00:00

## Summary

- Files audited: 50
- Verified: 50
- Refuted: 0
- Unverifiable: 0

All sampled files passed no-LLM verification; no new tool-side fixes were required.

## Sample details

| repo | file | status | notes |
|------|------|--------|-------|
| go | `src/cmd/compile/internal/gc/main.go` | verified |  |
| go | `src/cmd/compile/internal/importer/ureader.go` | verified |  |
| go | `src/cmd/compile/internal/mips64/ssa.go` | verified |  |
| go | `src/cmd/compile/internal/ssa/tuple.go` | verified |  |
| go | `src/cmd/compile/internal/test/switch_test.go` | verified |  |
| go | `src/cmd/internal/edit/edit_test.go` | verified |  |
| go | `src/cmd/internal/obj/arm64/anames.go` | verified |  |
| go | `src/crypto/internal/fips140/bigmod/nat_asm.go` | verified |  |
| go | `src/crypto/x509/oid_test.go` | verified |  |
| go | `src/os/removeall_test.go` | verified |  |
| go | `src/runtime/os_freebsd2.go` | verified |  |
| go | `src/runtime/security_aix.go` | verified |  |
| go | `src/simd/archsimd/_gen/simdgen/arm64/operands_test.go` | verified |  |
| go | `src/simd/simd_stubs.go` | verified |  |
| go | `src/syscall/route_openbsd.go` | verified |  |
| go | `src/syscall/syscall_netbsd_386.go` | verified |  |
| go | `test/chan/powser1.go` | verified |  |
| go | `test/fixedbugs/bug061.go` | verified |  |
| go | `test/fixedbugs/bug191.dir/main.go` | verified |  |
| go | `test/fixedbugs/bug380.go` | verified |  |
| go | `test/fixedbugs/bug423.go` | verified |  |
| go | `test/fixedbugs/issue45948.go` | verified |  |
| go | `test/fixedbugs/issue48088.dir/a.go` | verified |  |
| go | `test/fixedbugs/issue74648.go` | verified |  |
| go | `test/interface/recursive1.go` | verified |  |
| grafana | `apps/advisor/pkg/app/checks/instancechecks/out_of_support_step_test.go` | verified |  |
| grafana | `apps/dashboard/pkg/apis/dashboard/v2alpha1/dashboard_schema_gen.go` | verified |  |
| grafana | `apps/dashboard/pkg/apis/dashboard/v2beta1/dashboard_status_gen.go` | verified |  |
| grafana | `packages/grafana-sql/src/components/visual-query-builder/WhereRow.tsx` | verified |  |
| grafana | `packages/grafana-ui/src/themes/GlobalStyles/alerting.ts` | verified |  |
| grafana | `pkg/api/http_server.go` | verified |  |
| grafana | `pkg/services/ngalert/schedule/alert_rule.go` | verified |  |
| grafana | `pkg/services/promtypemigration/azure_prom_mig_test.go` | verified |  |
| grafana | `pkg/services/sqlstore/migrations/ualert/rule_notification_settings_mig.go` | verified |  |
| grafana | `pkg/storage/unified/resource/search_managed_test.go` | verified |  |
| grafana | `pkg/storage/unified/resource/storage_backend_gc_test.go` | verified |  |
| grafana | `pkg/storage/unified/resourcepb/search_grpc.pb.go` | verified |  |
| grafana | `pkg/storage/unified/search/bleve_mappings_internal_test.go` | verified |  |
| grafana | `pkg/tests/apis/alerting/notifications/templategroup/templates_group_test.go` | verified |  |
| grafana | `pkg/tsdb/graphite/healthcheck_test.go` | verified |  |
| grafana | `pkg/util/testutil/user_test.go` | verified |  |
| grafana | `public/app/features/alerting/unified/components/receivers/form/TestContactPointModal.tsx` | verified |  |
| grafana | `public/app/features/canvas/element.ts` | verified |  |
| grafana | `public/app/features/dashboard-scene/sharing/ShareButton/share-internally/ShareInternally.tsx` | verified |  |
| grafana | `public/app/features/panel/components/VizTypePicker/types.ts` | verified |  |
| grafana | `public/app/features/plugins/admin/components/InstallControls/InstallControlsButton.tsx` | verified |  |
| grafana | `public/app/features/plugins/extensions/registry/AddedFunctionsRegistry.ts` | verified |  |
| grafana | `public/app/features/variables/state/actions.ts` | verified |  |
| grafana | `public/app/plugins/panel/geomap/editor/StyleRuleEditor.tsx` | verified |  |
| grafana | `public/app/plugins/panel/geomap/utils/utils.ts` | verified |  |
