# Target OSS no-LLM dogfooding audit — continuation 344 (batch 345)

Run: 2026-07-22T20:53:15.431375+00:00

## Summary

- Files audited: 50
- Verified: 50
- Refuted: 0
- Unverifiable: 0

All sampled files passed no-LLM verification; no new tool-side fixes were required.

## Sample details

| repo | file | status | notes |
|------|------|--------|-------|
| go | `src/cmd/compile/internal/ir/val.go` | verified |  |
| go | `src/cmd/trace/doc.go` | verified |  |
| go | `src/crypto/mldsa/example_test.go` | verified |  |
| go | `src/encoding/json/jsontext/export.go` | verified |  |
| go | `src/image/image.go` | verified |  |
| go | `src/io/ioutil/tempfile.go` | verified |  |
| go | `src/net/http/httptest/httptest_test.go` | verified |  |
| go | `test/fixedbugs/issue23814.go` | verified |  |
| go | `test/fixedbugs/issue25984.dir/q.go` | verified |  |
| go | `test/fixedbugs/issue32901.go` | verified |  |
| go | `test/fixedbugs/issue39472.go` | verified |  |
| go | `test/fixedbugs/issue4326.dir/q1.go` | verified |  |
| go | `test/fixedbugs/issue44335.dir/a.go` | verified |  |
| go | `test/fixedbugs/issue47185.dir/bad/bad.go` | verified |  |
| go | `test/retjmp.dir/main.go` | verified |  |
| go | `test/typeparam/subdict.go` | verified |  |
| grafana | `apps/alerting/notifications/pkg/apis/alertingnotifications/v0alpha1/templategroup_codec_gen.go` | verified |  |
| grafana | `apps/iam/pkg/apis/iam/v0alpha1/team_getteamgroups_response_object_types_gen.go` | verified |  |
| grafana | `packages/grafana-data/src/text/text.ts` | verified |  |
| grafana | `packages/grafana-data/src/themes/createV1Theme.ts` | verified |  |
| grafana | `packages/grafana-schema/src/raw/composable/heatmap/panelcfg/x/types.gen.ts` | verified |  |
| grafana | `pkg/infra/httpclient/httpclientprovider/http_client_provider_test.go` | verified |  |
| grafana | `pkg/kinds/general.go` | verified |  |
| grafana | `pkg/registry/apis/collections/legacy/stars.go` | verified |  |
| grafana | `pkg/registry/apis/iam/resourcepermission/mapper.go` | verified |  |
| grafana | `pkg/registry/apis/provisioning/jobs/sync/syncer_mock.go` | verified |  |
| grafana | `pkg/registry/apps/correlations/register.go` | verified |  |
| grafana | `pkg/services/accesscontrol/acimpl/accesscontrol.go` | verified |  |
| grafana | `pkg/services/authz/rbac/store/sql_test.go` | verified |  |
| grafana | `pkg/services/ngalert/api/authorization.go` | verified |  |
| grafana | `pkg/storage/unified/resource/watch_publisher_test.go` | verified |  |
| grafana | `pkg/util/ip_address_test.go` | verified |  |
| grafana | `public/app/core/services/StateManagerBase.ts` | verified |  |
| grafana | `public/app/features/dashboard-scene/addToDashboard/AddToDashboardFormExposedComponent.tsx` | verified |  |
| grafana | `public/app/features/dashboard-scene/conditional-rendering/conditions/types.ts` | verified |  |
| grafana | `public/app/features/dashboard-scene/panel-edit/PanelEditNext/QueryEditor/Header/ContentHeader.tsx` | verified |  |
| grafana | `public/app/features/dashboard/dashgrid/DashboardLibrary/TemplateDashboardModal.tsx` | verified |  |
| grafana | `public/app/features/manage-dashboards/import/utils/validation.ts` | verified |  |
| grafana | `public/app/features/provisioning/components/Dashboards/SaveProvisionedDashboardForm.tsx` | verified |  |
| grafana | `public/app/features/scopes/dashboards/ScopesDashboardsService.ts` | verified |  |
| prysm | `api/client/builder/client_test.go` | verified |  |
| prysm | `beacon-chain/builder/service.go` | verified |  |
| prysm | `beacon-chain/db/kv/migration.go` | verified |  |
| prysm | `beacon-chain/operations/attestations/kv/seen_bits_test.go` | verified |  |
| prysm | `beacon-chain/rpc/prysm/v1alpha1/validator/proposer_deneb.go` | verified |  |
| prysm | `beacon-chain/state/state-native/setters_eth1_test.go` | verified |  |
| prysm | `testing/util/helpers_test.go` | verified |  |
| prysm | `validator/client/beacon-api/beacon_api_validator_client_test.go` | verified |  |
| prysm | `validator/client/beacon-api/submit_signed_aggregate_proof.go` | verified |  |
| prysm | `validator/client/testutil/helper.go` | verified |  |
