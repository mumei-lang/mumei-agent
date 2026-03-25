// Fixture: invariant violation.
// Conflicting constraints: x > 10 and x < 5 cannot both hold.

atom check_bounds(x: i64) -> i64
    requires: x > 10 && x < 5;
    ensures: result == x;
    body: x;
