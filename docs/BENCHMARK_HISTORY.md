# LLM Benchmark History

Time-series summary of proliferate LLM benchmark runs. The generation table is kept to the latest 50 rows and feeds `scripts/select_benchmark_model.py`.

## Recommended model policy

- **Current recorded local winner:** `qwen3.5:4b` (latest generation benchmark: 0.857 success rate).
- **Remote profile default:** keep `gpt-4o-mini` until remote benchmark rows are recorded; workflow dispatch can still override `llm_model`.
- **Tie-breakers:** maximize success rate, then prefer shorter generated code, then lower average runtime. Remaining ties resolve to the most recent benchmark row. This is the order implemented by `scripts/select_benchmark_model.py::select_model`.

## Generation Benchmark Runs

| Date | Model | Success Rate | Avg Code Length | Avg Time (s) |
|------|-------|--------------|-----------------|-------------:|
| 2026-05-04 | qwen3.5:4b | 0.667 | 163.3 | 0.000 |
| 2026-05-25 | qwen3.5:4b | 0.857 | 178.2 | 0.000 |

## SV-COMP Style Benchmarks

| Date | Model | Success Rate | Avg Time (ms) | Category |
|------|-------|--------------|---------------|----------|
| 2026-05-25 | qwen3.5:4b | 0.880 | 1200 | svcomp |

## Dafny Puzzle Port

| Date | Model | Success Rate | Avg Time (ms) | Category |
|------|-------|--------------|---------------|----------|
| 2026-05-25 | qwen3.5:4b | 0.920 | 800 | dafny |
