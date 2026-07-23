# Target OSS no-LLM dogfooding audit — continuation 503 (batch 504)

Run: 2026-07-23T07:10:32.431356+00:00

## Summary

- Files audited: 50
- Verified: 50
- Refuted: 0
- Unverifiable: 0

All sampled files passed no-LLM verification; no new tool-side fixes were required.

## Sample details

| repo | file | status | notes |
|------|------|--------|-------|
| go | `src/cmd/compile/internal/abt/avlint32.go` | verified |  |
| go | `src/cmd/compile/internal/typecheck/export.go` | verified |  |
| go | `src/cmd/internal/obj/x86/ytab.go` | verified |  |
| go | `src/cmd/internal/script/scripttest/doc.go` | verified |  |
| go | `src/crypto/internal/fips140/cast.go` | verified |  |
| go | `src/crypto/rsa/rsa_export_test.go` | verified |  |
| go | `src/fmt/doc.go` | verified |  |
| go | `src/go/doc/comment/parse_test.go` | verified |  |
| go | `src/go/parser/performance_test.go` | verified |  |
| go | `src/internal/syscall/windows/at_windows.go` | verified |  |
| go | `src/maps/maps_test.go` | verified |  |
| go | `src/reflect/arena.go` | verified |  |
| go | `src/runtime/covermeta.go` | verified |  |
| go | `src/runtime/defs_linux_386.go` | verified |  |
| go | `src/simd/archsimd/slicepart_arm64.go` | verified |  |
| go | `src/unicode/digit_test.go` | verified |  |
| go | `test/fixedbugs/bug064.go` | verified |  |
| go | `test/fixedbugs/bug248.dir/bug1.go` | verified |  |
| go | `test/fixedbugs/bug294.go` | verified |  |
| go | `test/fixedbugs/bug432.go` | verified |  |
| go | `test/fixedbugs/bug492.go` | verified |  |
| go | `test/fixedbugs/issue11053.go` | verified |  |
| go | `test/fixedbugs/issue44378.go` | verified |  |
| go | `test/method4.dir/method4a.go` | verified |  |
| go | `test/rotate.go` | verified |  |
| go | `test/typeparam/mdempsky/2.go` | verified |  |
| grafana | `apps/dashboard/pkg/apis/dashboard/v2/doc.go` | verified |  |
| grafana | `apps/provisioning/pkg/generated/clientset/versioned/typed/provisioning/v0alpha1/provisioning_client.go` | verified |  |
| grafana | `apps/provisioning/pkg/repository/reader_mock.go` | verified |  |
| grafana | `e2e-playwright/test-plugins/grafana-test-datasource/tests/utils.ts` | verified |  |
| grafana | `packages/grafana-ui/src/components/Table/TableNG/refactored/TableFlat.tsx` | verified |  |
| grafana | `pkg/expr/sql/db_test.go` | verified |  |
| grafana | `pkg/registry/apis/dashboard/register_test.go` | verified |  |
| grafana | `pkg/registry/apis/iam/datasourcek8s/k8s_test.go` | verified |  |
| grafana | `pkg/services/cloudmigration/gmsclient/inmemory_client.go` | verified |  |
| grafana | `pkg/services/folder/access_control.go` | verified |  |
| grafana | `pkg/services/ngalert/schedule/schedule_unit_test.go` | verified |  |
| grafana | `pkg/services/preference/timezone.go` | verified |  |
| grafana | `pkg/storage/unified/search/bleve_postrank_authz_internal_test.go` | verified |  |
| grafana | `pkg/storage/unified/sql/backend_blob.go` | verified |  |
| grafana | `pkg/tests/alertmanager/mimir.go` | verified |  |
| grafana | `public/app/core/components/Upgrade/UpgradeBox.tsx` | verified |  |
| grafana | `public/app/features/alerting/unified/hooks/useFolder.ts` | verified |  |
| grafana | `public/app/features/alerting/unified/types/receiver-form.ts` | verified |  |
| grafana | `public/app/features/apiserver/guards.ts` | verified |  |
| grafana | `public/app/features/browse-dashboards/fixtures/libraryElements.fixture.ts` | verified |  |
| grafana | `public/app/features/dashboard-scene/inspect/HelpWizard/HelpWizard.tsx` | verified |  |
| grafana | `public/app/features/dashboard-scene/scene/new-toolbar/actions/PlayListPreviousButton.tsx` | verified |  |
| grafana | `public/app/features/dashboard-scene/scene/panel-timerange/PanelTimeRangeDrawer.tsx` | verified |  |
| grafana | `public/app/types/jquery/jquery.d.ts` | verified |  |
