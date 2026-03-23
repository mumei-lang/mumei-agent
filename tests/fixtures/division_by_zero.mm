// Fixture: division by zero without a guarding precondition.

atom unsafe_div(a: i64, b: i64) -> i64
    ensures: result == a / b;
    body: a / b;
