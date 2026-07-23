# Target OSS no-LLM dogfooding audit — continuation 501 (batch 502)

Run: 2026-07-23T07:06:35.555419+00:00

## Summary

- Files audited: 50
- Verified: 50
- Refuted: 0
- Unverifiable: 0

All sampled files passed no-LLM verification; no new tool-side fixes were required.

## Sample details

| repo | file | status | notes |
|------|------|--------|-------|
| go | `src/cmd/compile/internal/escape/utils.go` | verified |  |
| go | `src/cmd/go/internal/doc/pkg.go` | verified |  |
| go | `src/cmd/link/internal/ld/nooptcgolink_test.go` | verified |  |
| go | `src/cmd/link/internal/loader/loader_test.go` | verified |  |
| go | `src/crypto/hpke/aead.go` | verified |  |
| go | `src/go/types/termlist_test.go` | verified |  |
| go | `src/internal/syscall/unix/arc4random_darwin.go` | verified |  |
| go | `src/math/export_s390x_test.go` | verified |  |
| go | `src/mime/quotedprintable/writer_test.go` | verified |  |
| go | `src/net/dnsconfig_unix.go` | verified |  |
| go | `src/net/sendfile_windows.go` | verified |  |
| go | `src/os/wait6_freebsd_arm.go` | verified |  |
| go | `src/runtime/debug/stack.go` | verified |  |
| go | `src/runtime/trace/trace_test.go` | verified |  |
| go | `src/simd/archsimd/_gen/unify/unify_test.go` | verified |  |
| go | `src/strconv/bytealg.go` | verified |  |
| go | `test/fixedbugs/bug356.go` | verified |  |
| go | `test/fixedbugs/issue13169.go` | verified |  |
| go | `test/fixedbugs/issue13821.go` | verified |  |
| go | `test/fixedbugs/issue15548.dir/b.go` | verified |  |
| go | `test/fixedbugs/issue44325.go` | verified |  |
| go | `test/fixedbugs/issue50671.go` | verified |  |
| go | `test/typeparam/issue48185a.dir/p.go` | verified |  |
| grafana | `apps/dashboard/pkg/migration/schemaversion/v10_test.go` | verified |  |
| grafana | `apps/dashboard/pkg/migration/schemaversion/v19.go` | verified |  |
| grafana | `apps/provisioning/pkg/generated/clientset/versioned/typed/provisioning/v0alpha1/fake/fake_repository.go` | verified |  |
| grafana | `packages/grafana-api-clients/src/clients/rtkq/dashboard/v1beta1/baseAPI.ts` | verified |  |
| grafana | `packages/grafana-data/src/datetime/timezones.ts` | verified |  |
| grafana | `packages/grafana-e2e-selectors/src/types/index.ts` | verified |  |
| grafana | `packages/grafana-schema/src/index.gen.ts` | verified |  |
| grafana | `packages/grafana-ui/src/components/Segment/SegmentSection.tsx` | verified |  |
| grafana | `pkg/registry/apps/annotation/config.go` | verified |  |
| grafana | `pkg/services/live/features/watch.go` | verified |  |
| grafana | `pkg/services/ngalert/api/compat_templates.go` | verified |  |
| grafana | `pkg/services/ngalert/api/persist.go` | verified |  |
| grafana | `pkg/setting/setting_annotations_test.go` | verified |  |
| grafana | `pkg/setting/setting_openfeature_test.go` | verified |  |
| grafana | `pkg/storage/unified/search/embed/embedder/vertex/vertex.go` | verified |  |
| grafana | `pkg/tests/apis/provisioning/foldermetadata/create_folder_git_test.go` | verified |  |
| grafana | `pkg/tests/apis/provisioning/nats/historicjob/historicjob_test.go` | verified |  |
| grafana | `pkg/tsdb/influxdb/flux/executor_test.go` | verified |  |
| grafana | `public/app/features/alerting/unified/rule-list/filter/utils.ts` | verified |  |
| grafana | `public/app/features/alerting/unified/styles/table.ts` | verified |  |
| grafana | `public/app/features/alerting/unified/types/time.ts` | verified |  |
| grafana | `public/app/features/canvas/elements/server/types/single.tsx` | verified |  |
| grafana | `public/app/features/commandPalette/KBarResults.tsx` | verified |  |
| grafana | `public/app/features/connections/components/FeatureHighlightsTabPage.tsx` | verified |  |
| grafana | `public/app/features/correlations/Forms/TransformationEditorRow.tsx` | verified |  |
| grafana | `public/app/features/dashboard-scene/embedding/EmbeddedDashboardLazy.tsx` | verified |  |
| grafana | `public/app/features/provisioning/Job/JobContent.tsx` | verified |  |
