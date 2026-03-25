// Fixture: precondition violation.
// safe_divide lacks the b != 0 guard, so division by zero is possible.

atom safe_divide(a: i64, b: i64) -> i64
    requires: true;
    ensures: result == a / b;
    body: a / b;
