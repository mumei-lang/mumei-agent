// Fixture: postcondition (ensures) violation.
// The ensures clause claims result > 0, but when x == 0 the body returns 0.

atom add_positive(x: i64) -> i64
    requires: x >= 0;
    ensures: result > 0;
    body: x;
