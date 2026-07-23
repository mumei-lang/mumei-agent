# Target OSS no-LLM dogfooding audit — continuation 484 (batch 485)

Run: 2026-07-23T05:46:00.025696+00:00

## Summary

- Files audited: 50
- Verified: 50
- Refuted: 0
- Unverifiable: 0

All sampled files passed no-LLM verification; no new tool-side fixes were required.

## Sample details

| repo | file | status | notes |
|------|------|--------|-------|
| go | `src/bytes/buffer.go` | verified |  |
| go | `src/cmd/compile/internal/base/flag.go` | verified |  |
| go | `src/cmd/compile/internal/liveness/mergelocals.go` | verified |  |
| go | `src/cmd/compile/internal/ssa/known_bits.go` | verified |  |
| go | `src/cmd/go/internal/cfg/bench_test.go` | verified |  |
| go | `src/cmd/go/internal/fsys/fsys_test.go` | verified |  |
| go | `src/crypto/cipher/ctr.go` | verified |  |
| go | `src/encoding/json/v2_encode.go` | verified |  |
| go | `src/go/types/index.go` | verified |  |
| go | `src/internal/runtime/maps/runtime_fast64.go` | verified |  |
| go | `src/internal/syscall/unix/waitid_linux.go` | verified |  |
| go | `src/math/arith_s390x.go` | verified |  |
| go | `src/net/sockopt_posix.go` | verified |  |
| go | `src/os/zero_copy_freebsd.go` | verified |  |
| go | `src/runtime/fastlog2.go` | verified |  |
| go | `src/runtime/vgetrandom_linux.go` | verified |  |
| go | `src/sync/map_test.go` | verified |  |
| go | `src/unicode/utf16/utf16.go` | verified |  |
| go | `test/align.go` | verified |  |
| go | `test/escape_hash_maphash.go` | verified |  |
| go | `test/fixedbugs/bug137.go` | verified |  |
| go | `test/fixedbugs/bug280.go` | verified |  |
| go | `test/fixedbugs/bug291.go` | verified |  |
| go | `test/fixedbugs/bug465.go` | verified |  |
| go | `test/fixedbugs/issue29855.go` | verified |  |
| go | `test/fixedbugs/issue48301.go` | verified |  |
| grafana | `apps/alerting/rules/pkg/apis/alerting/v0alpha1/rulesequence_object_gen.go` | verified |  |
| grafana | `apps/dashboard/pkg/migration/schemaversion/v23.go` | verified |  |
| grafana | `apps/example/pkg/apis/example/v1alpha1/example_client_gen.go` | verified |  |
| grafana | `apps/live/pkg/apis/live/v1alpha1/channel_schema_gen.go` | verified |  |
| grafana | `packages/grafana-ui/src/components/VizLegend/types.ts` | verified |  |
| grafana | `packages/grafana-ui/src/utils/closePopover.ts` | verified |  |
| grafana | `pkg/registry/apis/provisioning/controller/conditions_test.go` | verified |  |
| grafana | `pkg/services/annotations/annotationsimpl/time.go` | verified |  |
| grafana | `pkg/services/ldap/api/service.go` | verified |  |
| grafana | `pkg/services/libraryelements/accesscontrol_test.go` | verified |  |
| grafana | `pkg/services/ngalert/notifier/alertmanager_mock/Alertmanager.go` | verified |  |
| grafana | `pkg/services/searchusers/sortopts/sortopts.go` | verified |  |
| grafana | `pkg/tests/apis/provisioning/repository/repository_subresources_auth_test.go` | verified |  |
| grafana | `public/app/core/components/AppNotifications/StoredNotificationItem.tsx` | verified |  |
| grafana | `public/app/features/connections/hooks/useDataSourceSettingsNav.ts` | verified |  |
| grafana | `public/app/features/migrate-to-cloud/cloud/MigrationTokenPane/CreateTokenModal.tsx` | verified |  |
| grafana | `public/app/features/provisioning/hooks/useFolderMetadataStatus.ts` | verified |  |
| grafana | `public/app/features/query/state/processing/revision.ts` | verified |  |
| grafana | `public/app/features/transformers/editors/CalculateFieldTransformerEditor/constants.ts` | verified |  |
| grafana | `public/app/plugins/datasource/cloudwatch/components/QueryEditor/MetricsQueryEditor/SQLBuilderEditor/SQLBuilderEditor.tsx` | verified |  |
| grafana | `public/app/plugins/datasource/loki/metricTimeSplitting.ts` | verified |  |
| grafana | `public/app/plugins/panel/geomap/layers/basemaps/carto.ts` | verified |  |
| grafana | `public/lib/monaco-languages/index.ts` | verified |  |
| grafana | `scripts/cli/themeTemplates/_variables.scss.tmpl.ts` | verified |  |
