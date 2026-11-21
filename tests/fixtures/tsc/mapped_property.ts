type M = { [K in "a" | "b"]: number };
declare const m: M;
const { a: x } = m;
