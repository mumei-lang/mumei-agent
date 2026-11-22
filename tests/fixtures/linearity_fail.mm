// Fixture: linearity (ownership) violation.
// Token is a move type (scalars like i64 are Copy); t is moved into a
// and then used again.

struct Token { id: i64 }

atom use_twice(t: Token) -> i64
    body: {
        let a = t;
        let b = t;
        a.id + b.id
    };
