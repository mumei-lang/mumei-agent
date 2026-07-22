# Target OSS no-LLM dogfooding audit — continuation 374 (batch 375)

Run: 2026-07-22T22:30:02.219551+00:00

## Summary

- Files audited: 50
- Verified: 50
- Refuted: 0
- Unverifiable: 0

All sampled files passed no-LLM verification; no new tool-side fixes were required.

## Sample details

| repo | file | status | notes |
|------|------|--------|-------|
| go | `src/cmd/compile/internal/ssa/_gen/genericOps.go` | verified |  |
| go | `src/cmd/go/internal/vcweb/fossil.go` | verified |  |
| go | `src/crypto/internal/fips140/sha256/_asm/sha256block_amd64_avx2.go` | verified |  |
| go | `src/crypto/internal/fips140test/fips140v1.26_test.go` | verified |  |
| go | `src/internal/syscall/execenv/execenv_windows.go` | verified |  |
| go | `src/os/export_unix_test.go` | verified |  |
| go | `src/os/root_plan9.go` | verified |  |
| go | `src/runtime/debug/panic_test.go` | verified |  |
| go | `src/runtime/stubs.go` | verified |  |
| go | `src/syscall/errors_plan9.go` | verified |  |
| go | `src/syscall/zsysnum_netbsd_386.go` | verified |  |
| go | `test/fixedbugs/bug293.go` | verified |  |
| go | `test/fixedbugs/issue11945.go` | verified |  |
| go | `test/fixedbugs/issue16616.dir/a.go` | verified |  |
| go | `test/fixedbugs/issue23870.go` | verified |  |
| go | `test/fixedbugs/issue48092.go` | verified |  |
| go | `test/fixedbugs/issue6964.go` | verified |  |
| go | `test/fixedbugs/issue78355.go` | verified |  |
| go | `test/import6.go` | verified |  |
| go | `test/wasmmemsize.go` | verified |  |
| grafana | `.levignore.js` | verified |  |
| grafana | `apps/alerting/notifications/pkg/apis/alertingnotifications/v0alpha1/routingtree_schema_gen.go` | verified |  |
| grafana | `apps/alerting/notifications/pkg/apis/alertingnotifications/v1beta1/receiver_codec_gen.go` | verified |  |
| grafana | `apps/alerting/rules/plugin/src/generated/recordingrule/v0alpha1/types.metadata.gen.ts` | verified |  |
| grafana | `apps/annotation/pkg/apis/annotation/v0alpha1/constants.go` | verified |  |
| grafana | `apps/folder/pkg/apis/folder/v1/zz_generated.defaults.go` | verified |  |
| grafana | `apps/playlist/pkg/apis/playlist/v0alpha1/playlist_spec_gen.go` | verified |  |
| grafana | `apps/provisioning/pkg/connection/secure_test.go` | verified |  |
| grafana | `packages/grafana-data/src/transformations/transformers/ids.ts` | verified |  |
| grafana | `packages/grafana-data/src/types/dataLink.ts` | verified |  |
| grafana | `packages/grafana-data/src/types/scopes.ts` | verified |  |
| grafana | `packages/grafana-schema/src/raw/dashboard/x/types.gen.ts` | verified |  |
| grafana | `packages/grafana-ui/src/utils/floating.ts` | verified |  |
| grafana | `pkg/generated/clientset/versioned/fake/clientset_generated.go` | verified |  |
| grafana | `pkg/plugins/plugins.go` | verified |  |
| grafana | `pkg/services/ngalert/api/util.go` | verified |  |
| grafana | `pkg/services/ngalert/notifier/redis_channel_test.go` | verified |  |
| grafana | `pkg/services/pluginsintegration/pluginconfig/azure_settings.go` | verified |  |
| grafana | `pkg/services/screenshot/ratelimit.go` | verified |  |
| grafana | `pkg/services/serviceaccounts/database/token_store.go` | verified |  |
| grafana | `pkg/storage/unified/resourcepb/resource.pb.go` | verified |  |
| grafana | `pkg/tsdb/grafana-testdata-datasource/sims/engine_test.go` | verified |  |
| grafana | `pkg/tsdb/influxdb/healthcheck.go` | verified |  |
| grafana | `public/app/features/alerting/unified/components/Tokenize.tsx` | verified |  |
| grafana | `public/app/features/alerting/unified/components/contact-points/EditMessageTemplate.tsx` | verified |  |
| grafana | `public/app/features/alerting/unified/components/contact-points/NewMessageTemplate.tsx` | verified |  |
| grafana | `public/app/features/dashboard-scene/sharing/ShareLibraryPanelTab.tsx` | verified |  |
| grafana | `public/app/features/dashboard-scene/utils/clone.ts` | verified |  |
| grafana | `public/app/features/explore/PrometheusListView/utils/getRawPrometheusListItemsFromDataFrame.ts` | verified |  |
| grafana | `public/app/features/inspector/InspectDataOptions.tsx` | verified |  |
