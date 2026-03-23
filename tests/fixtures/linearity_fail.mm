// Fixture: linearity (ownership) violation.
// Variable x is consumed by the first use and then used again.

atom use_twice(x: i64) -> i64
    body: {
        let a = x;
        let b = x;
        a + b
    };
