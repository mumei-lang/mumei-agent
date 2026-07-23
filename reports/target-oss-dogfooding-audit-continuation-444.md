# Target OSS no-LLM dogfooding audit — continuation 444 (batch 445)

Run: 2026-07-23T02:49:14.239356+00:00

## Summary

- Files audited: 50
- Verified: 50
- Refuted: 0
- Unverifiable: 0

All sampled files passed no-LLM verification; no new tool-side fixes were required.

## Sample details

| repo | file | status | notes |
|------|------|--------|-------|
| go | `src/archive/tar/strconv_test.go` | verified |  |
| go | `src/cmd/cgo/internal/test/issue20266.go` | verified |  |
| go | `src/cmd/compile/internal/ssa/op.go` | verified |  |
| go | `src/cmd/internal/bio/buf_mmap.go` | verified |  |
| go | `src/crypto/internal/fips140/tls12/cast.go` | verified |  |
| go | `src/encoding/json/encode.go` | verified |  |
| go | `src/hash/fnv/fnv_test.go` | verified |  |
| go | `src/html/template/html_test.go` | verified |  |
| go | `src/internal/pkgbits/doc.go` | verified |  |
| go | `src/math/big/arithvec_s390x.go` | verified |  |
| go | `src/runtime/cgocall.go` | verified |  |
| go | `test/abi/store_reg_args.go` | verified |  |
| go | `test/fixedbugs/bug279.go` | verified |  |
| go | `test/fixedbugs/bug466.dir/b.go` | verified |  |
| go | `test/fixedbugs/issue59404part2.go` | verified |  |
| go | `test/import4.dir/empty.go` | verified |  |
| go | `test/interface/embed3.dir/embed0.go` | verified |  |
| go | `test/typeparam/issue47892b.dir/main.go` | verified |  |
| grafana | `apps/iam/pkg/apis/iam/v0alpha1/team_createteammember_response_object_types_gen.go` | verified |  |
| grafana | `apps/live/pkg/app/app_test.go` | verified |  |
| grafana | `packages/grafana-data/src/transformations/matchers/fieldValueMatcher.ts` | verified |  |
| grafana | `packages/grafana-ui/src/components/uPlot/config/UPlotThresholds.ts` | verified |  |
| grafana | `pkg/apiserver/auditing/noop.go` | verified |  |
| grafana | `pkg/infra/log/file_test.go` | verified |  |
| grafana | `pkg/plugins/manager/loader/loader.go` | verified |  |
| grafana | `pkg/registry/apis/provisioning/jobs/concurrent_driver.go` | verified |  |
| grafana | `pkg/registry/apis/provisioning/jobs/sync/changes.go` | verified |  |
| grafana | `pkg/registry/apps/alerting/rules/recordingrule/legacy_storage.go` | verified |  |
| grafana | `pkg/services/apiserver/builder/admission.go` | verified |  |
| grafana | `pkg/services/cloudmigration/cloudmigrationimpl/snapshot_mgmt.go` | verified |  |
| grafana | `pkg/services/folder/model.go` | verified |  |
| grafana | `pkg/services/ngalert/accesscontrol/fakes/rules.go` | verified |  |
| grafana | `pkg/services/promtypemigration/migrator.go` | verified |  |
| grafana | `pkg/services/publicdashboards/internal/service/service_wapper.go` | verified |  |
| grafana | `pkg/services/sqlstore/migrations/usermig/user_lowercase_login_and_email.go` | verified |  |
| grafana | `pkg/services/sqlstore/migrator/upsert_test.go` | verified |  |
| grafana | `pkg/tests/apis/provisioning/foldermetadata/full/export_folders_test.go` | verified |  |
| grafana | `pkg/tsdb/influxdb/fsql/arrow.go` | verified |  |
| grafana | `public/app/core/components/SharedPreferences/SharedPreferences.tsx` | verified |  |
| grafana | `public/app/features/alerting/unified/components/WithReturnButton.tsx` | verified |  |
| grafana | `public/app/features/alerting/unified/components/notification-policies/PromDurationInput.tsx` | verified |  |
| grafana | `public/app/features/alerting/unified/components/rule-editor/EvaluationGroupFieldRow.tsx` | verified |  |
| grafana | `public/app/features/alerting/unified/triage/instance-details/instanceStateUtils.ts` | verified |  |
| grafana | `public/app/features/connections/constants.ts` | verified |  |
| grafana | `public/app/features/explore/TraceView/components/model/ddg/PathElem.tsx` | verified |  |
| grafana | `public/app/features/home/AlertsIncidents/severity.ts` | verified |  |
| grafana | `public/app/features/provisioning/hooks/useConnectionOptions.ts` | verified |  |
| grafana | `public/app/features/variables/state/sharedReducer.ts` | verified | No Mumei atoms were generated from the extracted forge task spec. |
| grafana | `public/app/plugins/datasource/azuremonitor/components/MetricsQueryEditor/dataHooks.ts` | verified |  |
| grafana | `public/app/plugins/datasource/loki/LanguageProvider.ts` | verified |  |
