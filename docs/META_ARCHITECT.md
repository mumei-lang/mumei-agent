# Meta-Architect: Architectural Refactoring Agent

## Overview

The Meta-Architect is a high-level self-healing layer for architectural
oscillation. When local repair loops repeat the same failure or exhaust budget,
it inspects cross-atom dependencies and proposes interface-level refactorings
instead of stopping at manual review.

## When It Triggers

- Repeated verifier failures with the same counterexample signature
- Retry, token, solver-time, or action-class budget exhaustion
- Circular dependencies in cross-specification reports
- Caller/callee contract conflicts across atom boundaries

## Analysis Inputs

- `mumei verify --cross-spec-verify` and its `cross_spec.json`
- Self-healing retry history
- Current source contracts (`requires` / `ensures`)

## Refactoring Strategies

1. Relax preconditions when a callee requires more than its caller guarantees
2. Strengthen postconditions when a caller needs stronger callee guarantees
3. Add validation functions at module boundaries
4. Split atoms by extracting an interface layer for cycles or highly coupled nodes

## Self-Healing Integration

`agent.self_healing` invokes `MetaArchitect` before falling back to manual review
when budget policy marks an exhausted or repeating loop as architectural. The
first actionable proposal is applied through `agent.strategies.refactor_strategy`
and then re-verified by the normal loop.
