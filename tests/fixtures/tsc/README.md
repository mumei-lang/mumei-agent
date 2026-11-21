# TypeScript compiler snapshot fixtures

These envelopes capture the operator helper's output for the adjacent source
files. With Node.js available, regenerate them by providing the helper
directory:

```sh
python3 tests/fixtures/tsc/regenerate.py tools/ts-bindings
```

The helper's `package-lock.json` pins TypeScript 5.9.3. Run `npm ci` in
`tools/ts-bindings` before regenerating. The compiler host reads only the input
file and TypeScript's packaged `lib*.d.ts` files.
