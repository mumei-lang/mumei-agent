# Target OSS no-LLM dogfooding audit — continuation 388 (batch 389)

Run: 2026-07-23T00:03:03.795356+00:00

## Summary

- Files audited: 50
- Verified: 50
- Refuted: 0
- Unverifiable: 0

All sampled files passed no-LLM verification; no new tool-side fixes were required.

## Sample details

| repo | file | status | notes |
|------|------|--------|-------|
| go | `misc/cgo/gmp/gmp.go` | verified |  |
| go | `src/cmd/link/internal/ld/lib.go` | verified |  |
| go | `src/compress/flate/regmask_amd64.go` | verified |  |
| go | `src/crypto/ecdh/ecdh_wycheproof_test.go` | verified |  |
| go | `src/go/types/infer.go` | verified |  |
| go | `src/internal/reflectlite/reflect_mirror_test.go` | verified |  |
| go | `src/internal/strconv/ftoa_test.go` | verified |  |
| go | `src/internal/syscall/unix/renameat_sysnum_linux.go` | verified |  |
| go | `src/internal/testenv/opt.go` | verified |  |
| go | `src/os/stat.go` | verified |  |
| go | `src/runtime/defs_linux_mipsx.go` | verified |  |
| go | `src/syscall/ztypes_linux_386.go` | verified |  |
| go | `test/fixedbugs/bug075.go` | verified |  |
| go | `test/fixedbugs/issue12006.go` | verified |  |
| go | `test/fixedbugs/issue71759.go` | verified |  |
| go | `test/typeparam/issue50642.go` | verified |  |
| go | `test/typeparam/shape_assert.go` | verified |  |
| grafana | `apps/advisor/pkg/app/checks/instancechecks/check.go` | verified |  |
| grafana | `apps/dashvalidator/pkg/apis/manifestdata/dashvalidator_manifest.go` | verified |  |
| grafana | `apps/logsdrilldown/pkg/apis/logsdrilldown/v1alpha1/logsdrilldowndefaults_codec_gen.go` | verified |  |
| grafana | `apps/provisioning/pkg/repository/github/factory_test.go` | verified |  |
| grafana | `apps/provisioning/pkg/repository/staged.go` | verified |  |
| grafana | `packages/grafana-api-clients/src/generator/packageExports.ts` | verified |  |
| grafana | `packages/grafana-data/src/transformations/transformers/labelsToFields.ts` | verified |  |
| grafana | `packages/grafana-flamegraph/src/CallTree/ActionsCell.tsx` | verified |  |
| grafana | `packages/grafana-test-utils/src/fixtures/scopes.ts` | verified |  |
| grafana | `pkg/kinds/dashboard/dashboard_spec_gen.go` | verified |  |
| grafana | `pkg/plugins/pluginassets/modulehash/modulehash_test.go` | verified |  |
| grafana | `pkg/services/annotations/annotationstest/fake.go` | verified |  |
| grafana | `pkg/services/authz/rollout.go` | verified |  |
| grafana | `pkg/services/datasources/guardian/provider.go` | verified |  |
| grafana | `pkg/services/folder/registry.go` | verified |  |
| grafana | `pkg/services/ngalert/store/deltas.go` | verified |  |
| grafana | `pkg/storage/unified/apistore/restoptions.go` | verified |  |
| grafana | `pkg/storage/unified/search/embed/embedder/batch_process.go` | verified |  |
| grafana | `pkg/storage/unified/search/remote_index_store_fuzz_test.go` | verified |  |
| grafana | `pkg/tsdb/influxdb/simplejson/simplejson.go` | verified |  |
| grafana | `public/app/core/context/ModalsContextProvider.tsx` | verified |  |
| grafana | `public/app/features/alerting/unified/components/export/providers.ts` | verified |  |
| grafana | `public/app/features/alerting/unified/mocks/server/events.ts` | verified |  |
| grafana | `public/app/features/correlations/Forms/TransformationsEditor.tsx` | verified |  |
| grafana | `public/app/features/dashboard-scene/solo/ViewPanelWrapper.tsx` | verified |  |
| grafana | `public/app/features/dashboard-scene/utils/variables.ts` | verified |  |
| grafana | `public/app/features/dashboard/components/PanelEditor/state/selectors.ts` | verified |  |
| grafana | `public/app/features/dashboard/components/ShareModal/SharePublicDashboard/ModalAlerts/EmailSharingPricingAlert.tsx` | verified |  |
| grafana | `public/app/features/migrate-to-cloud/onprem/TypeCell.tsx` | verified |  |
| grafana | `public/app/plugins/datasource/grafana-postgresql-datasource/configuration/ConfigurationEditor.tsx` | verified |  |
| grafana | `public/app/plugins/panel/table/suggestions.ts` | verified |  |
| grafana | `public/app/plugins/panel/text/TextPanel.tsx` | verified |  |
| grafana | `public/app/plugins/panel/timeseries/TimeSeriesTooltip.tsx` | verified |  |
