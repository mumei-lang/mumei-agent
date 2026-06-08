// Fixture: contradictory specification.
// The requires clause demands x > 0 AND x < 0, which is unsatisfiable.

atom impossible_positive(x: i64) -> i64
    requires: x > 0 && x < 0;
    ensures: result >= 0;
    body: x;
