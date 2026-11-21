# TypeScript compiler binding helper

This operator-side helper captures a single `.ts` or `.tsx` source file using
the pinned TypeScript compiler API. It does not read a project `tsconfig`,
ambient types, or user `node_modules`; the compiler host serves only the input
file and `lib*.d.ts` files shipped with TypeScript.

```sh
npm ci
node helper.js path/to/file.ts > envelope.json
```

Use `file.tsx` for TSX input. The envelope records the exact compiler options
and source text for the agent's pure, fail-closed reader. The agent does not
run Node or this helper.
