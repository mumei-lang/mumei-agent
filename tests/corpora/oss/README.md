# Pinned real-OSS dogfood corpus

Unmodified upstream files, fetched at the commits pinned in `MANIFEST.json`, used by
`tests/test_foreign_code_oss_corpus.py` to check that deterministic extraction
(`use_llm=False`) never produces malformed `requires` / `ensures` clauses on real-world
syntax distributions. `tests/test_foreign_code_corpus.py` keeps the synthetic
signature corpus that targets structural fragility (multi-value returns, nested
expressions, hallucinated functions); this corpus complements it with real code.

Each file is upstream-licensed (see `license` in `MANIFEST.json`) and is included
verbatim so extraction sees exactly what upstream ships — provenance lives in the
manifest rather than in injected headers. To refresh or add an entry:

```bash
curl -s -o tests/corpora/oss/<lang>/<name> \
  https://raw.githubusercontent.com/<owner>/<repo>/<ref>/<source_path>
git ls-remote https://github.com/<owner>/<repo> 'refs/tags/<ref>^{}'   # -> commit
```

then add the `path` / `language` / `upstream` / `ref` / `commit` / `source_path` /
`license` entry to `MANIFEST.json`. Keep files small: the corpus runs on every CI
push, and `test_corpus_files_stay_within_ci_budget` caps per-file line counts.
