// Example: a simple atom with a precondition bug for self-healing demo.
// Running `uv run python -m agent.self_healing examples/sword_test.mm` will detect
// the verification failure and attempt to fix the `requires` clause.

atom safe_divide(a: Nat, b: Nat) -> Nat
    requires: a >= 0;
    ensures: result >= 0;
    body: a / b;
