# Ollama KV Cache & Long-Context Tuning

`docker-compose.yml` configures the local Ollama service for long-context runs:

```yaml
OLLAMA_KV_CACHE_TYPE: q8_0
OLLAMA_NUM_CTX: "32768"
```

These are the defaults the agent ships with. The README lists the same two
values; this document explains what they do, how to tune them, and the research
directions for stronger KV-cache compression.

## Current settings

- `OLLAMA_KV_CACHE_TYPE=q8_0` uses the KV-cache quantization currently available
  through llama.cpp / Ollama-compatible backends, roughly halving KV-cache
  memory versus FP16 and allowing longer context before memory exhaustion.
- `OLLAMA_NUM_CTX=32768` raises the context target from the common 2048 default
  to 32768. Lower it on memory-constrained machines, or raise it only after
  confirming enough GPU/CPU RAM.

## Future KV-cache compression (TurboQuant / PolarQuant)

TurboQuant and PolarQuant show that stronger KV-cache compression is plausible:

- **TurboQuant** uses randomized rotation plus scalar quantization and reports
  neutral quality at about 3.5 bits/channel for the KV cache.
- **PolarQuant** uses random preconditioning plus polar-coordinate angle
  quantization and reports over 4.2x KV-cache compression on long-context
  evaluations.

Once those methods are exposed by llama.cpp / Ollama as stable cache types,
replace `q8_0` with the backend's published type name (for example a future
`turbo*_0` / `polar*_0` cache type) and re-benchmark quality, latency, and
maximum context before making it the default.
