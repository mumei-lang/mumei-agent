# Target OSS no-LLM dogfooding audit — continuation 456 (batch 457)

Run: 2026-07-23T03:43:03.623306+00:00

## Summary

- Files audited: 50
- Verified: 50
- Refuted: 0
- Unverifiable: 0

All sampled files passed no-LLM verification; no new tool-side fixes were required.

## Sample details

| repo | file | status | notes |
|------|------|--------|-------|
| go | `src/cmd/internal/obj/s390x/anames.go` | verified |  |
| go | `src/cmd/internal/testdir/testdir_test.go` | verified |  |
| go | `src/crypto/fips140/enforcement.go` | verified |  |
| go | `src/debug/dwarf/export_test.go` | verified |  |
| go | `src/go/types/context.go` | verified |  |
| go | `src/go/types/gcsizes.go` | verified |  |
| go | `src/html/template/escape_test.go` | verified |  |
| go | `src/io/pipe.go` | verified |  |
| go | `src/math/big/arith_amd64.go` | verified |  |
| go | `src/mime/type_unix.go` | verified |  |
| go | `src/runtime/nbpipe_pipe_test.go` | verified |  |
| go | `src/runtime/signal_linux_ppc64x.go` | verified |  |
| go | `src/runtime/sizeof_test.go` | verified |  |
| go | `src/runtime/utf8.go` | verified |  |
| go | `src/simd/archsimd/_gen/simdgen/gen_simdIntrinsics.go` | verified |  |
| go | `src/strings/iter_test.go` | verified |  |
| go | `src/time/zoneinfo_goroot.go` | verified |  |
| go | `test/fixedbugs/issue11750.go` | verified |  |
| go | `test/fixedbugs/issue18895.go` | verified |  |
| go | `test/fixedbugs/issue25507.go` | verified |  |
| go | `test/fixedbugs/issue38356.go` | verified |  |
| go | `test/typeparam/issue48042.go` | verified |  |
| grafana | `apps/dashboard/pkg/migration/conversion/metrics.go` | verified |  |
| grafana | `apps/example/pkg/apis/example/v1alpha1/example_object_gen.go` | verified |  |
| grafana | `e2e-playwright/dashboards-suite/utils/makeDashboard.ts` | verified |  |
| grafana | `packages/grafana-ui/src/components/RadialGauge/RadialText.tsx` | verified |  |
| grafana | `packages/grafana-ui/src/components/Table/TableRT/FilterPopup.tsx` | verified |  |
| grafana | `packages/grafana-ui/src/themes/GlobalStyles/utilityClasses.ts` | verified |  |
| grafana | `pkg/registry/apis/dashboard/snapshot/snapshot_legacy_store_test.go` | verified |  |
| grafana | `pkg/registry/apis/iam/display/keys.go` | verified |  |
| grafana | `pkg/registry/apps/annotation/graphite.go` | verified |  |
| grafana | `pkg/services/auth/id.go` | verified |  |
| grafana | `pkg/services/authz/zanzana/server/server_mutate_folder.go` | verified |  |
| grafana | `pkg/services/ngalert/limits.go` | verified |  |
| grafana | `pkg/services/ngalert/metrics/ngalert.go` | verified |  |
| grafana | `pkg/services/ngalert/provisioning/validation/provenance.go` | verified |  |
| grafana | `pkg/services/pluginsintegration/plugincontext/plugincontext_test.go` | verified |  |
| grafana | `pkg/services/star/startest/fake.go` | verified |  |
| grafana | `pkg/storage/secret/metadata/secure_value_model.go` | verified |  |
| grafana | `pkg/storage/unified/search/embed/embedder/bedrock/embed_dense_test.go` | verified |  |
| grafana | `public/app/features/alerting/unified/api/grafana.ts` | verified |  |
| grafana | `public/app/features/alerting/unified/components/contact-points/components/Modals.tsx` | verified |  |
| grafana | `public/app/features/alerting/unified/components/rule-editor/FolderSelectorV2.tsx` | verified |  |
| grafana | `public/app/features/alerting/unified/components/rule-editor/notificaton-preview/NotificationPreviewGrafanaManaged.tsx` | verified |  |
| grafana | `public/app/features/connections/tabs/ConnectData/ConnectData.tsx` | verified |  |
| grafana | `public/app/features/dashboard-scene/settings/annotations/AnnotationEditableElement.tsx` | verified |  |
| grafana | `public/app/features/logs/components/panel/LogLineContext.tsx` | verified |  |
| grafana | `public/app/features/provisioning/Config/EnablePushToConfiguredBranchOption.tsx` | verified |  |
| grafana | `public/app/plugins/datasource/graphite/types.ts` | verified |  |
| grafana | `public/app/plugins/panel/nodeGraph/useNodeLimit.ts` | verified |  |
