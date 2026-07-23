# Target OSS no-LLM dogfooding audit — continuation 483 (batch 484)

Run: 2026-07-23T05:44:06.787321+00:00

## Summary

- Files audited: 50
- Verified: 50
- Refuted: 0
- Unverifiable: 0

All sampled files passed no-LLM verification; no new tool-side fixes were required.

## Sample details

| repo | file | status | notes |
|------|------|--------|-------|
| go | `src/cmd/compile/internal/logopt/log_opts.go` | verified |  |
| go | `src/cmd/internal/osinfo/os_uname.go` | verified |  |
| go | `src/cmd/link/internal/ld/outbuf_nommap.go` | verified |  |
| go | `src/crypto/hpke/kem.go` | verified |  |
| go | `src/internal/cpu/export_x86_test.go` | verified |  |
| go | `src/internal/goarch/zgoarch_riscv64.go` | verified |  |
| go | `src/math/big/arith_decl_pure.go` | verified |  |
| go | `src/math/hypot.go` | verified |  |
| go | `src/net/http/filetransport_test.go` | verified |  |
| go | `src/net/unixsock_posix.go` | verified |  |
| go | `src/runtime/secret/doc.go` | verified |  |
| go | `src/simd/archsimd/_gen/unify/value.go` | verified |  |
| go | `src/simd/archsimd/shuffles_amd64.go` | verified |  |
| go | `src/testing/run_example.go` | verified |  |
| go | `test/fixedbugs/bug457.go` | verified |  |
| go | `test/fixedbugs/bug467.dir/p1.go` | verified |  |
| go | `test/fixedbugs/issue11656.dir/issue11656.go` | verified |  |
| go | `test/fixedbugs/issue29013b.go` | verified |  |
| go | `test/fixedbugs/issue44432.go` | verified |  |
| go | `test/fixedbugs/issue48471.go` | verified |  |
| go | `test/fixedbugs/issue49592.go` | verified |  |
| go | `test/fixedbugs/issue8440.go` | verified |  |
| go | `test/nilptr5.go` | verified |  |
| go | `test/typeparam/genembed.go` | verified |  |
| go | `test/typeparam/issue48454.dir/b.go` | verified |  |
| grafana | `apps/dashboard/pkg/migration/schemaversion/v7.go` | verified |  |
| grafana | `apps/plugins/pkg/apis/plugins/v0alpha1/meta_schema_gen.go` | verified |  |
| grafana | `packages/grafana-data/src/dataframe/FieldCache.ts` | verified |  |
| grafana | `packages/grafana-ui/src/components/PanelContainer/PanelContainer.tsx` | verified |  |
| grafana | `packages/grafana-ui/src/components/RadialGauge/ThresholdsBar.tsx` | verified |  |
| grafana | `pkg/apis/datasource/v0alpha1/query_test.go` | verified |  |
| grafana | `pkg/apiserver/auditing/middleware.go` | verified |  |
| grafana | `pkg/login/social/connectors/google_oauth.go` | verified |  |
| grafana | `pkg/registry/apis/iam/team/mutate_test.go` | verified |  |
| grafana | `pkg/registry/apis/secret/inline/inline_secure_value_test.go` | verified |  |
| grafana | `pkg/registry/apps/annotation/lifecycle.go` | verified |  |
| grafana | `pkg/services/auth/jwt/jwt.go` | verified |  |
| grafana | `pkg/services/ssosettings/ssosettingstests/fallback_strategy_fake.go` | verified |  |
| grafana | `pkg/storage/legacysql/dualwrite/service.go` | verified |  |
| grafana | `public/app/core/components/AppChrome/AppChromeUpdate.tsx` | verified |  |
| grafana | `public/app/core/components/AppChrome/TopBar/useHelpNode.tsx` | verified |  |
| grafana | `public/app/features/alerting/unified/components/contact-points/components/ContactPointsFilter.tsx` | verified |  |
| grafana | `public/app/features/alerting/unified/components/notification-policies/EditDefaultPolicyForm.tsx` | verified |  |
| grafana | `public/app/features/explore/ContentOutline/ContentOutlineItem.tsx` | verified |  |
| grafana | `public/app/features/explore/state/testHelpers.ts` | verified |  |
| grafana | `public/app/features/plugins/extensions/ExtensionErrorAlert.tsx` | verified |  |
| grafana | `public/app/features/search/tempI18nPhrases.ts` | verified |  |
| grafana | `public/app/plugins/datasource/grafana/timeRegions.ts` | verified |  |
| grafana | `public/app/plugins/panel/bargauge/BarGaugeMigrations.ts` | verified |  |
| grafana | `public/app/plugins/panel/xychart/XYChartPanel.tsx` | verified |  |
