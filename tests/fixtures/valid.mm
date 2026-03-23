// Fixture: a valid atom that should pass verification.

atom safe_add(a: i64, b: i64) -> i64
    requires: a >= 0 && b >= 0;
    ensures: result == a + b;
    body: a + b;
