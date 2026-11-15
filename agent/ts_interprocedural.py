"""C06 TypeScript/JavaScript interprocedural summaries.

A deliberately narrow scalar fragment, mirroring the Go consumer's
*model* (``agent/go_interprocedural.py``) — not its producer pipeline.
There is no compiler snapshot: source annotations are the only type
signal, and calls resolve statically by name to function declarations
in the same unit. Anything outside the fragment fails CLOSED with a
declared gap — never a silently wrong summary.

Admitted:

* Parameters on a top-level `function name(...) { ... }`
  declaration — optional (`x?`) and defaulted (`x = expr`)
  parameters admit like required ones and a default's calls
  still record. Annotations are type-level and ignored
  (`f(o: Foo)` binds the index like `f(x: number)` — actuals
  scalarize at the call site); a `...rest` occupies the last
  index slot and a destructuring pattern destructures it (see
  below). Return annotations are equally type-level — `x is T`,
  `void`, `Foo`, `Promise<...>` or none at all all admit;
  recorded deps come from the actual `return` statements.
* `let`/`const`/`var` declarations whose declarators bind one
  identifier to a supported expression or to nothing (`let x;`
  binds `undefined` — no dependencies; any annotation is
  type-level and ignored — `const o: {a: number} = {a: x}`
  evaluates the value). Member stores reach a module-scope
  composite (`o.f = v` inside a function updates the shared
  `_Composite`, and an alias across scopes gets the
  copy-on-write result in both scopes).
  `using r = e` / `await using` declarations bind like `const`
  (the disposal protocol is dep-invisible; the grammar keeps an
  assignment-shaped node with `has_error`), and `debugger;` is a
  no-op like `;`.
* Scalar literals (`number`, `true`, `false`), identifier reads of
  bound parameters/locals, parentheses, pure unary (`!`, `-`, `+`,
  `~`), `void` (evaluates for calls, yields no deps) and `typeof`
  (operand deps pass through), `as`/`satisfies`/`!` assertions
  (transparent), and binary operators (`+`, `-`, `*`, `/`, `%`,
  `**`, comparisons, `==`/`===`/`!=`/`!==`, `&&`, `||`, `??`,
  `&`, `|`, `^`, `<<`, `>>`, `>>>`).
* `return expr` (dependency union over every return — an
  over-approximation, not a per-site result), bare `return` (no
  tracked result), assignments `x = e` to bound names, compound
  assignments `x op= e` for the admitted operators (deps union like
  `x = x op e`), and `x++`/`x--`/`++x`/`--x` on bound names
  (dependency-preserving). `var` bindings are function-scoped —
  they escape bare blocks and `for` initializers — while `let`/`const`
  are block-scoped and never shadow an outer name past their block.
* `if`/`else` (each branch evaluated over a scope copy and joined by
  union — a conditional store keeps both the new deps and the value
  the skipped path would have left),
  `while`, `do`/`while` and classic `for (init; cond; incr)` loops
  (bodies iterate to a dependency fixed point — a join, never an
  unroll; trip counts are not modelled — a `do`/`while`'s run-once
  guarantee is invisible to that join and shares the `while` shape),
  `switch`/`case`/`default` (clauses processed in source order in a
  shared scope — every clause body is a may-write since entry is
  conditional, and a `break` ends only the paths that entered at an
  earlier clause), unlabelled `break`/`continue` inside a loop —
  a `break` inside a `switch` targets the switch's own frame while a
  `continue` skips it and still targets the enclosing loop — and
  `try`/`catch`/`finally` with `throw` (a `throw` evaluates its
  expression for calls and unions its deps into `thrown_deps`,
  then every later statement is a may-write until a `catch`
  consumes the thrown flag; `finally` always runs — a
  `catch (e)` binds `e` to the union of the thrown deps and a
  destructured `catch ({m})`/`catch ([m])` binds every pattern
  name to that union (the thrown value is scalarized — each
  name over-approximates to it), the sound over-approximation
  for whichever throw reached it), and
  `L: stmt` labels — a labeled loop or switch claims
  the label on its own frame, any other labeled statement gets a
  plain frame, so `break L` exits exactly the labeled statement and
  `continue L` only targets labeled loops (an unknown label, or a
  `continue` to a non-loop label, closes).
* Expressions also admit `a = b`/`a op= b` used as a
  sub-expression (writes like the statement form, always as a
  may-write since e.g. a `||`/`?:` arm may not run, and yields the
  assigned dependencies) and `sequence_expression` (the comma
  operator — operands evaluate left to right, the union is the
  result).
* Object literals `{a: e, n: {c: e}}` bound to a name — a
  `_Composite` value tracking dependencies per field; member reads
  `o.f`/`o.a.b` descend to the field's deps, member writes
  `o.f = e`/`o.f op= e`/`o.f++` rewrite the field copy-on-write
  (branch joins merge field-wise, and a shape mismatch collapses
  the composite to the union of its leaf deps), string-key
  subscripts `o["f"]` act like member syntax, a dynamic `o[k]`
  read unions every field at that level plus the index's deps
  (every getter up the class chain is invoked too — the key may
  name an accessor), a dynamic write `o[k] = v` is a may-write
  on every field (scalars union the value's deps, callables
  widen their captured set and stay invocable, composites
  descend the rest of the path; every setter up the class chain
  runs), and a missing field reads as `undefined`
  (no deps). Reading or passing a whole composite flattens to the
  union of its fields. Aliasing is reference-faithful only at the
  name level: `p = o` shares the composite and a member write
  through either name reaches both bindings in the same scope —
  while a composite bound anywhere else collapses to its leaf
  deps (`{a: o2}` field values, `q = o.a` member-path bindings,
  `o.f = o2` member stores, `{o}` shorthand), so no sub-object
  alias can diverge. Method/getter/setter object members and
  member access on a scalar or unbound base stay closed.
* Array literals `[e0, e1]` bound to a name — a `_Composite` with
  positional keys: `a[0]`/`a["0"]` reads field `"0"` precisely,
  `a[i]` unions every element plus the index's deps, `a[i] = e`
  writes a literal index field, and `a.length` reads a missing
  field (`undefined` — no deps). Nested array/object literals
  keep their structure; any other composite element collapses
  like an object field value. `for..of` iterates elements,
  `for..in` iterates keys — both through the composite rules.
* `for (const k in o)` / `for (const e of o)` over a composite —
  `in` binds the key as an opaque dep-free string (a `o[k]` read
  inside still unions every field), `of` binds the union of every
  field's deps; a `let`/`const` key or element is scoped to the
  loop while `var` escapes, and a bare identifier target binds as
  a may-write (the loop may not run). Any other right-hand side
  or a non-identifier left closes.
* Arrow functions and `function` expressions bound to names —
  `const g = (v) => v + x` is a `_Callable`; `g(y)` evaluates the
  body inline with the argument bound and captured names read at
  the CALL site (closures capture by reference — the latest
  value over-approximates). Writes inside the body merge back as
  may-writes; parameter defaults union their deps when the arg
  is omitted; the body's frames and scope state stay isolated.
  Passing or returning the value collapses to its `captured`
  union (every visible binding's deps at the definition site).
  A local binding shadows a same-named function declaration, and
  calling a scalar/composite-bound name closes. Recursion hits
  `MAX_NODES` and closes the caller with `analysis_limit`.
* Member calls `o.f(x)` where the field holds a `_Callable`
  (`{f: v => v}`) — the member read resolves the callee and the
  body evaluates as with a name call. A `function` expression or
  shorthand method (`is_method`) invoked through a member path
  receives `this` = the object; an arrow does not.
* Dynamic member calls `o[k](x)` — the key can't pick the field,
  so every callable field (and every class method of an
  instance's `klass`, including computed `[k]() {}` members
  registered under synthetic names a static lookup can never
  produce) is invoked and the results union — an
  over-approximation where non-callable fields contribute their
  scalar through the member read. `o?.[k](x)` admits the same.
* `async` functions, async arrows and `await` expressions — in the
  dep model a promise is its resolved value, so `await e` passes
  the operand's deps through and `async` admits at the signature
  gate. `for await (x of y)` iterates like `of`.
* Rest formal parameters `f(a, ...rest)` — the rest name
  occupies the last index slot; a declared-function call already
  unions every evaluated argument into the result, and a
  `_Callable` invocation binds the rest name to the union of the
  remaining actuals. A parameter after `...rest` closes.
* Shorthand method definitions `{m(v) { ... }}` — a callable
  field value like an arrow, invoked through the slice-13 member
  call path (`o.m(x)`). `get`/`set`/`static` markers stay
  closed; `*` generator methods admit (yield deps union into
  the result, as below); `async` admits. `this` binds to the
  receiver object
  inside (see the classes bullet).
* Destructured formal parameters `f({a, b}, [x])` — the pattern
  occupies one scalar index; its sub-names bind member reads of
  the slot at body start (each sees the slot's whole dep set).
  The summary records the pattern text (e.g. `{a, b}`) in
  `parameters`.
* Destructured declarations `const {a, b: c = d, ...rest} = o` /
  `const [x, y = d] = arr` — each sub-name binds the member read
  at its path (defaults union the default expression's deps, a
  `...rest` binding over-approximates to the whole union, a
  nested pattern descends); a scalar source binds every sub-name
  to the whole dep union, and a composite member binds as a
  scalar (member-path rule). Positions count holes — `[p, , q]`
  binds `q` to element 2. The same walk drives assignment
  destructuring `({a} = o)` / `[x] = arr` — leaves write
  existing bindings via `_write_scope` and member targets
  (`{a: o.f} = src`) via `_member_store`, and `for` loop
  patterns `for (const {a} of rows)` — declared names land in
  the loop scope, a bare pattern assigns. A `for...of` right
  side that isn't a composite (`Object.entries(o)`) binds the
  scalar's whole dep set.
* Tagged templates `tag`...${x}...`` — the tag resolves like a
  call: declared name → transfer, bound `_Callable` (name or
  member) → inline invoke. Actuals are the dep-free cooked
  strings array then each substitution's deps.
* Classes — `class C { f = e; m(v) {...} }` at top level or in a
  body binds a `_Class` (methods/statics as `is_method`
  callables, field initializers run at `new`). `new C(args)`
  seeds `this` to a fresh `_Composite`, runs field inits and the
  `constructor` body, and yields the evolved instance — member
  calls `c.m(x)` receive `this`, and a missing instance field
  falls through to the class's methods (the prototype). `C.sf` /
  `C.sm(x)` read statics on the class object; `this` anywhere
  else is unbound. `class D extends C` inherits the method,
  static and field tables a `_Class` carries (own members
  shadow) — `super(args)` in a ctor runs the parent
  constructor on the same `this`, `super.m(x)` calls through
  the parent prototype; `super.f`/`super.f = v` are data
  field accesses on `this` itself (JS `[[Set]]` owns the
  property), and `super.p`/`super.p = v` invoke the PARENT's
  accessor on `this` (a child override is bypassed, matching
  the home-object rule); `implements` is type-level and
  admits silently. Computed member names are skipped (the
  name expression still evaluates; `o[k]()` calls close)
  and `abstract`/`declare` members close (`readonly` fields and
  parameter properties are value-identical for deps);
  `static get/set p` collect into `sgetters`/`ssetters` —
  `C.p` reads invoke the getter like a no-arg method on
  the class object, `C.p = v` invokes the setter unless an
  own `static p` data field shadows it, and `C.s = v` on a
  module-scope class name updates the shared `statics`
  table; `constructor(private a, readonly b)` parameter
  properties seed `this` fields from the bound actuals
  before the body runs;
  `*m()` generator methods admit like `function*`, private
  `#` members behave like named fields/methods keyed `#`,
  and `static {}` blocks evaluate once into the class's
  captured set. Decorators (`@dec`, `@dec(y)`, `@ns.dec(y)`
  on the class or a member) evaluate at definition time —
  a bare `@dec` is the call `dec(C)`, a factory `@dec(y)`
  evaluates its call; the class `captured` already unions
  every local so decorator deps need no extra pin.
* Spread members in object/array literals — `{...o}` copies the
  source composite's fields (a fresh instance — writes don't
  reach `o`), `[...a]` appends its positional fields; a scalar
  spread or a computed `{[k]: v}` key adds unknown fields, so the
  whole literal collapses to a scalar dep union. Optional-chain
  `o?.f`/`o?.[k]` and non-null `x!` read like their plain forms.
* `get`/`set` members in object literals — `{get p(){}, set p(v){}}`
  collect into a synthetic accessor class on the composite, so
  `o.p`/`o.p = v` take the same invoke paths class accessors do
  with the literal instance as `this`.
* JSX — sources that fail the plain `typescript` grammar reparse
  under `tsx`; elements contribute every embedded expression's
  deps, `<Comp a={x}>{y}</Comp>` invokes a callable/component tag
  with a props composite (`children` carries the child deps) or
  records a same-unit call, and lowercase tags are host elements.
* String/`null`/`undefined` literals (dep-free), template strings
  (the result carries the union of the interpolations' deps), the
  `in`/`instanceof` binary operators (operand-dep union), and
  `delete o.f` (copy-on-write field removal propagated to aliases;
  a dynamic `delete o[k]` keeps every field — the surviving deps
  are the over-approximation).
* `import`/`export` — `import {a, b as c}`, `import * as ns`,
  `import d` bind each imported name to an `_External` marker:
  reads are dep-free, member reads stay external, and a call
  (or `new`) through one records a `TsCall` transfer yielding
  the union of its actuals — the same opaque-callee
  over-approximation as a declared-function result.
  `import type` and bare `import 'm'` bind nothing. `export`
  strips to the declaration it wraps (`export function`,
  `export class`, `export default function` register
  normally; `export {}`/`export *` bind nothing the
  function model reads). Imports are top-level only — one
  inside a body closes.
* Module resolution — when `summarize_typescript` gets a
  `resolver` (or the CLI runs with `--resolve-modules`), an
  import specifier that resolves to source text is parsed as
  its own unit: its `export`ed names (declarations, `export
  {a, b as c}` re-exports, `export default`) bind locally —
  `import {g}` to a `_Callable`, `import * as ns` to a
  `_Composite` of the export table, `import {C}` to the
  `_Class` — and an imported callable invokes under its own
  module's scope via `cval.origin` (private helpers resolve
  there, never to an importer binding). Resolution is
  bounded (MAX_MODULE_DEPTH chain depth, shared module
  cache) and strictly sharpening: a cycle, missing module,
  or unexported name leaves the binding `_External` with
  unchanged call semantics. `ts-summaries
  --resolve-modules` resolves relative `./`/`../`
  specifiers under the source file's directory, bounded by
  MAX_SOURCE_BYTES each.
* CommonJS — a unit's `module.exports`/`exports` writes
  collect into a precise export table (`exports.x = v`,
  `module.exports.x = v`, `module.exports = v`) that
  `require('./b')` resolves to; a unit that writes none
  answers a `_Composite` of its ESM `export` table. The
  same table feeds `import` interop (`import {g}`, and
  `import d` of a bare-function export via `default`).
  Unresolvable specifiers and non-string arguments keep
  the external-callee union — resolution only sharpens.
* Function declarations are first-class values: `_lookup`
  materializes `self.functions[name]` into a `_Callable`
  (captured scope unioned across materialization sites, so
  a name visible under several scopes over-approximates).
  Call sites collect each argument's evaluated VALUE in
  `values_out`; `_invoke_callable` binds a non-scalar
  actual (`_Callable`/`_Composite`/`_Class`/`_External`)
  to the parameter, so `h(g)`/`h({a: x})`/`new A(g)` let
  the callee body call `c(x)` or read `o.a` precisely.
  Member writes on a composite SHARED with an unseen
  scope — a `this` receiver or a composite actual —
  mutate its field table in place (`_aliased_objs`), so
  `a.set(x); a.get()` propagates; scope-local composites
  keep copy-on-write (the loop fixed point's pre-write
  snapshot must survive). An opaque call (declared
  function's dep-union, `_External`, `import()`) may
  write any field of a composite actual — every field
  takes the call's dep union (`_opaque_call_writes`).
* Shorthand object fields keep a function/class value's
  shape — `{e}` stores the `_Callable` like `{e: e}` —
  so `m.e(o, x)` invokes through the field. Member calls
  through `Function.prototype` on a known callable
  (`_funproto_call`): `g.call(t, a)` binds `this` = `t`;
  `g.apply(t, arr)` supplies a `_Composite` array's
  element values or covers every parameter with the
  scalar dep; `g.bind(t, a...)` returns a `_Callable`
  with the partial application in its `bound` slot —
  invocations prepend the bound actuals and apply the
  bound `this` when the call supplies none.
* A bound name that evaluates to a scalar isn't a hard close
  at call sites — `b ? g : h` joins callables to their
  captured union and the call dep-unions. `extends` on a
  non-class value ends the parent chain; the heritage
  expression's deps record as `opaque_extends` and seed the
  instance's `"*"` field bucket at construction.
* `new Map()`/`new Set()` (and weak variants) build a
  `_Composite` tagged `_MAP_SET_KLASS`: `set`/`add`/
  `delete`/`clear` may-write the entry table (literal keys
  precisely, others via `"*"`), `get`/`has`/`size`/
  iteration reads carry the entry union. `new` on a scalar-
  joined ctor dep-unions; `Function` is a known global.
* `_invoke_callable` bounds nesting at `MAX_INVOKE_DEPTH` —
  self-recursive or mutually recursive function values
  over-approximate to captured ∪ actuals past the bound
  instead of exhausting the interpreter stack.
* Destructured callable parameters (`({a}, [b]) => ...`)
  bind their sub-names through `_destructure` at invoke
  time — a scalar actual over-approximates each sub-name
  to the whole union; `a.fill(v)` may-writes its actual
  into every element.
* Labeled `for..of` claims its label for `continue L`; a
  catchless `try` keeps thrown deps for an enclosing
  handler; array literals count comma holes as positions.
* `var` names hoist to function scope; literal computed
  member keys resolve (`['m'](){}`), dynamic computed
  fields seed `"*"`; `g.extra = v` widens a callable's
  captured; an opaque `extends` seeds `"*"` with heritage
  deps plus the call's actuals.
* `m.set`/`s.add` return the updated collection; Map/Set
  method names dispatch before table entries; `bind`
  prepends an earlier `bound` (first bound `this` wins, and
  it overrides the call site's receiver); `apply` sorts
  digit keys numerically; a depth-bounded invoke may-writes
  composite actuals; `module.exports = exports` keeps the
  live table.
* Module-scope `let`/`const`/`var`/`export const` — a second
  pass over top-level declarators evaluates each into
  `self.module_locals` (params empty; `var` writes land in
  the same dict via `function_locals`). Functions read the
  module scope through `_lookup` after params; a declarator
  the model can't evaluate (an unbound call, an
  unsupported shape) closes the whole unit, and a write to
  a module-scope name from inside a function closes.
* Generators — `function*`, `function*` methods and `*m()`
  object-literal methods admit; each `yield`/`yield*` operand's
  deps union into the enclosing generator's return deps (the
  iterated values are the over-approximation), and `yield`'s
  sent-back value is dep-free. `yield_deps` isolate per callable
  the way frames do.
* Optional calls — `f?.(x)` and optional-callee forms
  `o?.f(x)`/`o.f?.(x)`/`o?.[k](x)`: a scalar (unmodellable)
  callee yields the union of the actuals — treating a
  maybe-absent callee as run is the sound
  over-approximation. A `_Callable`/`_External` callee
  takes the normal invoke/external path.
* `arguments` binds a per-function `_Composite` whose every
  element over-approximates to the whole parameter/actual
  union — `arguments[0]` and `arguments[i]` read it; a
  `f(...a)` spread actual contributes its operand's dep union.
* Well-known globals — `Math`/`Object`/`JSON`/`console`/
  `Number`/`Promise`/etc. read as `_External` through a
  `_GLOBALS` table at the end of `_lookup`: member reads stay
  external, calls and `new` yield the actuals' union, and a
  local binding or import shadows the global via the normal
  lookup order.
* Container built-ins — `a.map/filter/forEach/find/some/every/
  reduce/join/includes/push/pop/at/slice/concat/sort/keys/...`
  on a `_Composite` receiver (`_COLLECTION_METHODS`): `elem` is
  the union of every leaf dep; a function-literal or bound
  callable first arg invokes with every formal bound to
  `elem ∪ actuals` (positions can't be correlated — map's
  `(v,i,arr)` vs reduce's `(acc,v)`). `map`/`filter`/`slice`/
  `concat`/`flat`/`sort`/`keys`/etc. return a fresh
  `_Composite` (bindable via `call_expression`), scalars
  return the elem/actual union, `forEach` is dep-free, and
  `push`/`unshift` copy-on-write a grown instance onto every
  same-scope alias like `_member_store`. A user field named
  `map` still shadows the built-in.
* Member access on a computed base — `a.slice()[0]`, `f().m`,
  `new C().v`: `_member_target` returns the non-identifier base
  node and `_member_read` evaluates it, then descends the rest of
  the path. A scalar mid-path over-approximates to the scalar's
  deps (`s.length`, `x.f`) — including member *calls* on a scalar
  base (`s.indexOf(x)`, `m.f(x)` on an opaque `require` result),
  which record a `TsCall` and yield `base ∪ actuals` like an
  `_External` callee. Member stores on a computed base still
  close (no binding to rebind). Regex literals are dep-free.
* Type-only and ambient declarations — `interface I {...}`,
  `type T = {...}` and `declare ...`/`ambient_declaration` at
  top level are skipped wholesale (they evaluate to nothing —
  an ambient name simply never binds, so a use of it still
  closes at the use site). `enum
  E { A, B = expr }` (and `const enum`, `export enum`) binds a
  `_Composite` in module scope: bare members are dep-free and an
  initializer contributes its own deps — an initializer may
  name earlier members (`B = A + 1` — dep-free numbers bound
  into the eval scope), so `E.A` reads as a field. Bodiless
  `function g(v: T): R;` overload signatures are type-level and
  skipped (the implementation declaration registers the name —
  later declarations win, matching JS hoisting). `new C`
  without parentheses constructs with no actuals.
* Expression callees — `(() => x)()`, `(g)(x)`, `f?.()`: a
  non-identifier callee evaluates to a value; a `_Callable`
  invokes inline, an `_External` yields the actuals' union,
  and any other value (a scalar — including a collapsed
  callable like `(x > 0 ? g : h)`) takes the same
  over-approximation the optional-call fallback uses: the
  callee's deps plus the actuals' union, with a `TsCall`
  recorded. Parenthesized expressions preserve their value
  (no eager flatten) so `(() => x)()` and `(o).f` keep
  their shape. Tagged templates (`tag`..${x}..``) call the
  tag with the strings array plus each substitution.
* Comma sequences, dynamic imports, and meta properties —
  `(a, b, c)` evaluates every operand for its writes/calls;
  a scalar result over-approximates to the union, while a
  composite/callable last operand keeps its shape so `(o,
  f)(x)` invokes `f`. `import('m')` treats the module
  promise as an opaque callee (actuals' union + `TsCall`),
  and `import.meta`/`new.target` `meta_property` reads are
  dependency-free.
* `namespace N { ... }` — binds a `_Composite` in module
  scope: member declarators evaluate in order into a scope
  that sees the enclosing bindings, exported `function`
  members become callable fields (`N.g(x)` invokes through
  the member-call path), and a nested `internal_module`
  recurses (`A.B.g(x)`). `enum`/`class` members close the
  unit.
* `async` — `async function f(...): Promise<T>` admits when
  `T` is `number`/`boolean` (nested `Promise<Promise<T>>`
  unwraps the same way); `await` passes the operand's deps
  through, `for await (const v of a)` iterates like `for
  ..of`, and `async` arrows/function expressions bind like
  plain ones. `for(;;)`/`for(;c;)` empty slots parse as
  `empty_statement` — they read as absent.
* Class accessors — `get p()`/`set p(v)` on a class admit:
  `o.p` on an instance invokes the getter like a no-arg method
  (`this` is the instance) and records a `TsCall`; `o.p = v`
  invokes the setter with the written deps as its actual, unless
  the instance carries an own data field `p` (a field shadows
  the accessor). Static accessors admit the same through the
  statics table, and object-literal `{get p(){}}`/`{set p(v){}}`
  collect into a synthetic class's accessor tables — `this`
  binds to the literal. `abstract`/`declare` members are
  bodyless signatures and skip (the member simply never
  registers); `abstract class` registers like a normal class,
  and an index signature member skips.
* Calls `f(args)` whose callee is a `function` declared in the same
  unit — resolved by name only, including nested `function inner()`
  declarations (hoisted: a call before its site still resolves) —
  each nested declaration gets its own summary. A nested
  declaration ALSO binds a `_Callable` in the enclosing frame at
  body start, so `inner()` inside the enclosing body invokes the
  body inline with call-site bindings — `function h(){ return x; }`
  reads the enclosing parameter's deps (closures capture by
  reference). Module-scope `const g = (x) => {...}` binds a
  callable in `module_locals`, so `g(y)` resolves through the
  bound-callee path. The result conservatively depends on every
  evaluated argument and records a `TsCall` transfer; the callee
  body is opaque (self-recursion records a transfer like any other
  name-resolved call). Everything else — calls through a
  non-callable field, unresolved names — stays closed.

Closed with declared gaps: a module-scope item the model
can't evaluate closes the whole unit (`unsupported_unit`) —
top-level statements (`console.log(x)`, `init()`,
module-scope `if`/`for`) evaluate in source order in pass 2,
so an unmodelled one still closes;
`eval`, `with`, and `new` on a non-class/non-function
ctor stay
closed (`unsupported_signature` / `unsupported_statement` /
`unsupported_expression` / `binding_unavailable` / `call_unresolved`).
A member store's setter runs for its own deps like any invoked
body — `this` writes propagate through the same may-write
merge-back member calls use.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass

PROFILE = "mumei.ts-scalar-parameter-deps/v1"

# Defensive bound on evaluated syntax nodes — a parser or dispatch bug
# must never hang the analyzer.
MAX_NODES = 20000
# Nesting bound for `_invoke_callable` — self-recursive or
# deeply chained function values would otherwise exhaust the
# interpreter stack. Beyond the bound an invocation
# over-approximates to captured ∪ actuals.
MAX_INVOKE_DEPTH = 32
# Import resolution depth along a chain of relative specifiers
# — deeper chains stay `_External` like any unresolvable import.
MAX_MODULE_DEPTH = 8

# The full arithmetic/bitwise/logical operator set is admitted — the dep
# model only needs the operand union, so `/`, `%`, `**`, shifts and `??`
# over-approximate the same way `*` and `||` do.
_BINARY_OPS = {
    "+", "-", "*", "/", "%", "**",
    "<", "<=", ">", ">=",
    "==", "===", "!=", "!==",
    "&&", "||", "??",
    "&", "|", "^", "<<", ">>", ">>>",
    # `in`/`instanceof` yield booleans — the operand dep union is
    # the over-approximation.
    "in", "instanceof",
}
_UNARY_OPS = {"!", "-", "+", "~"}
_AUGMENTED_OPS = {op + "=" for op in _BINARY_OPS if op not in {"==", "===", "!=", "!==", "<", "<=", ">", ">="}}

# Top-level children that keep the unit a fragment unit.
_TOP_LEVEL = {
    "function_declaration",
    "class_declaration",
    "abstract_class_declaration",
    "comment",
    "import_statement",
    "export_statement",
    "empty_statement",
    "lexical_declaration",
    "variable_declaration",
    "generator_function_declaration",
    # Type-only declarations (`interface I {...}`, `type T =
    # {...}`) evaluate to nothing — they're skipped wholesale
    # rather than closing the unit. `declare`/ambient forms are
    # skipped the same way: they produce no runtime bindings, so
    # names they claim stay unbound and any actual use still
    # closes at the use site.
    "interface_declaration",
    "type_alias_declaration",
    "ambient_declaration",
    "enum_declaration",
    "internal_module",
    # A bodyless `function g(v: T): R;` overload signature — the
    # implementation declaration registers the name; signatures
    # are type-level and skipped.
    "function_signature",
}

# Well-known platform/library globals read as `_External` — reads
# are dep-free, member reads stay external, and a call/`new`
# through one yields its actuals' union (the opaque-callee
# over-approximation, same as imports). A local binding or import
# shadows the global through `_lookup` order.
_GLOBALS = {
    "Array",
    "Boolean",
    "Date",
    "JSON",
    "Map",
    "Math",
    "Number",
    "Object",
    "Promise",
    "Set",
    "String",
    "Symbol",
    "BigInt",
    "Function",
    "RegExp",
    "Error",
    "TypeError",
    "RangeError",
    "SyntaxError",
    "Intl",
    "Reflect",
    "Proxy",
    "WeakMap",
    "WeakSet",
    "console",
    "window",
    "globalThis",
    "document",
    "process",
    "Buffer",
    "require",
    "fetch",
    "setTimeout",
    "setInterval",
    "setImmediate",
    "queueMicrotask",
    "clearTimeout",
    "clearInterval",
    "parseInt",
    "parseFloat",
    "isNaN",
    "isFinite",
    "encodeURIComponent",
    "decodeURIComponent",
    "encodeURI",
    "decodeURI",
    "structuredClone",
    "Promise",
    "undefined",
}


# Array/object methods modelled on a `_Composite` receiver —
# only reached when the composite has no such field (a scalar
# user field named `map` still closes).
_COLLECTION_METHODS = {
    "map",
    "flatMap",
    "filter",
    "forEach",
    "find",
    "findIndex",
    "some",
    "every",
    "reduce",
    "reduceRight",
    "join",
    "includes",
    "indexOf",
    "lastIndexOf",
    "at",
    "slice",
    "concat",
    "flat",
    "sort",
    "reverse",
    "fill",
    "push",
    "unshift",
    "pop",
    "shift",
    "keys",
    "values",
    "entries",
    "toString",
}


# Declared-manifest restoration bounds and validators — the same
# fail-closed shape `GoSummarySet.from_dict` enforces: a manifest is
# declared data, so unknown keys, wrong types and oversize
# collections are malformed, never partially adopted.
MAX_MANIFEST_MEMBERS = 8192


def _require_manifest(condition: bool) -> None:
    if not condition:
        raise ValueError("declared summary manifest is malformed")


def _manifest_record(
    value, required: tuple[str, ...], optional: tuple[str, ...] = ()
) -> dict:
    if not isinstance(value, dict) or not (
        set(required) <= set(value) <= set(required) | set(optional)
    ):
        raise ValueError("declared summary manifest is malformed")
    return value


def _string(value) -> str:
    if type(value) is not str:
        raise ValueError("declared summary manifest is malformed")
    return value


def _boolean(value) -> bool:
    if type(value) is not bool:
        raise ValueError("declared summary manifest is malformed")
    return value


def _list(value) -> list:
    if type(value) is not list:
        raise ValueError("declared summary manifest is malformed")
    return value


def _deps_from_list(value) -> frozenset[int]:
    deps = _list(value)
    _require_manifest(
        len(deps) <= MAX_MANIFEST_MEMBERS
        and all(type(d) is int and d >= 0 for d in deps)
    )
    return frozenset(deps)


@dataclass(frozen=True)
class TsSpan:
    """Source byte span (single file — no file index yet)."""

    start: int
    end: int

    def to_dict(self) -> dict:
        return {"start": self.start, "end": self.end}

    @classmethod
    def from_dict(cls, value) -> "TsSpan":
        v = _manifest_record(value, ("start", "end"))
        _require_manifest(
            type(v["start"]) is int
            and type(v["end"]) is int
            and 0 <= v["start"] <= v["end"]
        )
        return cls(v["start"], v["end"])


@dataclass(frozen=True)
class TsGap:
    """A declared reason a function's summary is unavailable."""

    reason: str
    span: TsSpan
    callee: str = ""

    def to_dict(self) -> dict:
        out = {"reason": self.reason, "span": self.span.to_dict()}
        if self.callee:
            out["callee"] = self.callee
        return out

    @classmethod
    def from_dict(cls, value) -> "TsGap":
        v = _manifest_record(value, ("reason", "span"), ("callee",))
        return cls(
            _string(v["reason"]),
            TsSpan.from_dict(v["span"]),
            _string(v["callee"]) if "callee" in v else "",
        )


@dataclass(frozen=True)
class TsCall:
    """A same-unit call transfer: the callee name, per-argument
    dependency sets and the unioned result dependencies."""

    span: TsSpan
    callee: str
    arguments: tuple[frozenset[int], ...]
    result: frozenset[int]

    def to_dict(self) -> dict:
        return {
            "span": self.span.to_dict(),
            "callee": self.callee,
            "arguments": [sorted(a) for a in self.arguments],
            "result": sorted(self.result),
        }

    @classmethod
    def from_dict(cls, value) -> "TsCall":
        v = _manifest_record(
            value, ("span", "callee", "arguments", "result")
        )
        arguments = _list(v["arguments"])
        _require_manifest(len(arguments) <= MAX_MANIFEST_MEMBERS)
        return cls(
            TsSpan.from_dict(v["span"]),
            _string(v["callee"]),
            tuple(_deps_from_list(a) for a in arguments),
            _deps_from_list(v["result"]),
        )


@dataclass(frozen=True)
class TsFunctionSummary:
    name: str
    available: bool
    parameters: tuple[str, ...]
    # `None` means unavailable — never an empty set; an empty set is a
    # parameter-independent result, and a function without a return
    # expression reports an empty set too (no result is tracked).
    return_dependencies: frozenset[int] | None
    calls: tuple[TsCall, ...]
    gaps: tuple[TsGap, ...]
    # Reserved for a later type-identity layer (the Go consumer's
    # `pinned` member/signature ids); always empty in slice 0.
    pinned: tuple[str, ...] = ()
    effects: str = "none_in_supported_fragment"

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "available": self.available,
            "parameters": list(self.parameters),
            "return_dependencies": (
                None
                if self.return_dependencies is None
                else sorted(self.return_dependencies)
            ),
            "calls": [c.to_dict() for c in self.calls],
            "gaps": [g.to_dict() for g in self.gaps],
            "pinned": list(self.pinned),
            "effects": self.effects,
        }

    @classmethod
    def from_dict(cls, value) -> "TsFunctionSummary":
        v = _manifest_record(
            value,
            (
                "name",
                "available",
                "parameters",
                "return_dependencies",
                "calls",
                "gaps",
                "pinned",
                "effects",
            ),
        )
        parameters = _list(v["parameters"])
        calls = _list(v["calls"])
        gaps = _list(v["gaps"])
        pinned = _list(v["pinned"])
        _require_manifest(
            len(parameters) <= MAX_MANIFEST_MEMBERS
            and len(calls) <= MAX_MANIFEST_MEMBERS
            and len(gaps) <= MAX_MANIFEST_MEMBERS
            and len(pinned) <= MAX_MANIFEST_MEMBERS
        )
        deps = v["return_dependencies"]
        restored_deps = None if deps is None else _deps_from_list(deps)
        restored_gaps = tuple(TsGap.from_dict(g) for g in gaps)
        available = _boolean(v["available"])
        # A manifest may not contradict itself: `available` tracks
        # exactly "a result was derived and no gap was recorded" —
        # a forged flag cannot borrow trust the record lacks.
        _require_manifest(
            available == (restored_deps is not None)
            and available == (not restored_gaps)
        )
        return cls(
            _string(v["name"]),
            available,
            tuple(_string(p) for p in parameters),
            restored_deps,
            tuple(TsCall.from_dict(c) for c in calls),
            restored_gaps,
            tuple(_string(p) for p in pinned),
            _string(v["effects"]),
        )


@dataclass(frozen=True)
class TsSummarySet:
    context_key: str
    functions: tuple[TsFunctionSummary, ...]
    profile: str = PROFILE

    def to_dict(self) -> dict:
        return {
            "schema_version": self.profile,
            "context_key": self.context_key,
            "functions": [f.to_dict() for f in self.functions],
        }

    @classmethod
    def from_dict(cls, value) -> "TsSummarySet":
        """Restore a declared manifest — strict, bounded, fail-closed.

        The manifest is declared data, not trusted input: unknown or
        missing keys, wrong types and oversize collections are all
        malformed — the caller fails closed rather than adopting a
        partial set."""
        v = _manifest_record(
            value,
            ("schema_version", "context_key", "functions"),
        )
        _require_manifest(v["schema_version"] == PROFILE)
        functions = _list(v["functions"])
        _require_manifest(len(functions) <= MAX_MANIFEST_MEMBERS)
        return cls(
            _string(v["context_key"]),
            tuple(TsFunctionSummary.from_dict(f) for f in functions),
        )


class _Unsupported(Exception):
    """A closed path in the fragment — carries the declared gap."""

    def __init__(self, reason: str, span: TsSpan, callee: str = "") -> None:
        super().__init__(reason)
        self.reason = reason
        self.span = span
        self.callee = callee


def _span(node) -> TsSpan:
    return TsSpan(node.start_byte, node.end_byte)


def _children(node) -> list:
    return node.named_children


def _has_optional_chain(node) -> bool:
    """`node` or a descendant marks an optional step (`?.`,
    `optional_chain`)."""
    if node is None:
        return False
    if node.type in {"?.", "optional_chain"}:
        return True
    return any(_has_optional_chain(c) for c in node.children)


class _Composite:
    """An object-shaped value: field name -> scalar deps or nested
    `_Composite`. Treated as immutable — a member write produces a
    new instance bound to the base name, so branch scopes may share
    an instance freely. `klass` is the `_Class` an instance came
    from (None for literals) — method lookup falls through to it."""

    __slots__ = ("fields", "klass", "deleted")

    def __init__(self, fields: dict, klass=None, deleted=None) -> None:
        self.fields = fields
        self.klass = klass
        # Names of fields a `delete` may have removed — a join
        # keeps the field's deps (it may have survived) while the
        # marker keeps the prototype fallback reachable on reads.
        self.deleted = deleted if deleted is not None else frozenset()


class _Callable:
    """A function value: an `arrow_function`/`function_expression`
    bound to a name. `params`/`defaults` describe its formal
    parameters; `captured` over-approximates its closure reads —
    the union of every visible binding's deps at the definition
    site — so passing or returning the value is a scalar.
    `rest` is the index of a `...rest` formal (-1 when absent):
    invocation binds it to the union of every remaining actual.
    `is_method` marks values that receive `this` when invoked
    through a member path (`function` expressions and shorthand
    methods — arrows never do)."""

    __slots__ = (
        "node", "params", "defaults", "captured", "rest",
        "is_method", "param_props", "origin", "bound", "patterns",
        "alts", "extra",
    )

    def __init__(
        self, node, params, defaults, captured, rest=-1, is_method=False
    ) -> None:
        self.node = node
        self.params = params
        self.defaults = defaults
        # Alternate callees the same member slot may resolve to
        # (a maybe-deleted own field hiding a prototype method) —
        # every invocation runs them all and unions the results.
        self.alts = ()
        # Deps that also flow through the member slot this value
        # was read from — a maybe-deleted field's getter fallback —
        # unioned into every invocation's result.
        self.extra = frozenset()
        self.captured = captured
        self.rest = rest
        self.is_method = is_method
        # Constructor parameter properties — names declared
        # `public`/`private`/`protected`/`readonly` on a ctor
        # parameter; `new` seeds `this` fields from the bound
        # actuals before the body runs.
        self.param_props: frozenset = frozenset()
        # `Function.prototype.bind` partial application: a
        # `(deps, values, this)` triple prepended to every
        # invocation's actuals — the params stay full-length so
        # bound positions bind their recorded values.
        self.bound = None
        # Parameter positions declared as `object_pattern`/
        # `array_pattern` — `g = ({a}, [b]) => ...` stores the
        # pattern node per index; the invoke binds its sub-names
        # through `_destructure` instead of a scalar slot.
        self.patterns: dict = {}
        # The `_Builder` that created this value — a callable
        # imported from another module invokes under its own
        # module's scope (its private helpers and module bindings
        # resolve there), never the importer's. `None` means the
        # building builder itself.
        self.origin = None



class _External:
    """An imported name: the callee/ctor lives outside the unit.
    A call through it records a `TsCall` transfer and yields the
    union of its actuals (the opaque-callee over-approximation);
    any member read stays external (a namespace import)."""

    __slots__ = ()


class _Class:
    """A class value: `ctor` (`_Callable` or None), `methods` /
    `statics` (name -> `_Callable` for methods, scalar deps for
    static fields), `field_inits` (name -> initializer node) and
    `parent` (the `extends` `_Class` or None). `getters`/`setters`
    hold `get p()`/`set p(v)` accessors — a read invokes the
    getter like a no-arg method, a store invokes the setter with
    the written deps. Generators, `abstract` members and
    computed names close the class instead.
    `captured` flattens the whole class to a scalar."""

    __slots__ = (
        "ctor", "methods", "statics", "field_inits", "captured",
        "parent", "getters", "setters", "sgetters", "ssetters",
        "dyn_field_deps", "opaque_extends",
    )

    def __init__(
        self, ctor, methods, statics, field_inits, captured,
        parent=None, getters=None, setters=None,
        sgetters=None, ssetters=None,
        dyn_field_deps=frozenset(), opaque_extends=frozenset(),
    ):
        self.ctor = ctor
        self.methods = methods
        self.statics = statics
        self.field_inits = field_inits
        self.captured = captured
        self.parent = parent
        self.getters = getters if getters is not None else {}
        self.setters = setters if setters is not None else {}
        self.sgetters = sgetters if sgetters is not None else {}
        self.ssetters = ssetters if ssetters is not None else {}
        # Deps of fields declared with a non-literal computed
        # name (`[k] = e`) — every instance seeds `"*"` with it
        # so a dynamic member read sees the write.
        self.dyn_field_deps = dyn_field_deps
        # Deps of a non-`_Class` `extends` expression — the
        # opaque parent ctor may write any `this` field with the
        # subclass's actuals, so instances seed `"*"` with them.
        self.opaque_extends = opaque_extends


# `new Map()`/`new Set()`/weak variants yield a `_Composite`
# tagged with this sentinel class so `_collection_call` gives
# them map/set semantics instead of array ones.
_MAP_SET_METHODS = {
    "set",
    "add",
    "get",
    "has",
    "delete",
    "clear",
    "size",
    "forEach",
    "keys",
    "values",
    "entries",
}


def _scalar_of(value) -> frozenset[int]:
    """Flatten a value to scalar deps — reading or passing a whole
    composite over-approximates to the union of its leaf deps; a
    callable flattens to its captured deps."""
    if isinstance(value, _Composite):
        result = frozenset()
        for field in value.fields.values():
            result |= _scalar_of(field)
        if value.klass is not None:
            result |= value.klass.captured
        return result
    if isinstance(value, _Callable):
        result = value.captured | value.extra
        for alt in value.alts:
            # A maybe-deleted slot's other candidates keep their
            # captured deps too — scalarizing the value sees them.
            result |= _scalar_of(alt)
        return result
    if isinstance(value, _Class):
        return value.captured
    if isinstance(value, _External):
        return frozenset()
    return value


_MAP_SET_KLASS = _Class(
    None, {}, {}, {}, frozenset()
)


def _computed_key(node):
    """Literal key of a `computed_property_name` child —
    `['m']`/`[0]` resolve, anything dynamic returns None."""
    if node.type == "string":
        return node.text.decode().strip("\"'")
    if node.type == "number":
        return node.text.decode()
    return None


def _callee_name(node):
    """Callee label for a `TsCall` — identifier/member paths
    only. Any non-identifier segment (a string-literal key in
    `o["..."]`, a computed property, a call-expression callee)
    renders as `?` so literal text inside the callee expression
    can never reach the JSON output."""
    if node is None:
        return "?"
    if node.type == "identifier":
        return node.text.decode()
    if node.type == "parenthesized_expression":
        inner = next(iter(_children(node)), None)
        return _callee_name(inner)
    if node.type == "member_expression":
        obj = node.child_by_field_name("object")
        prop = node.child_by_field_name("property")
        base = _callee_name(obj)
        if prop is not None and prop.type == "property_identifier":
            return f"{base}.{prop.text.decode()}"
        return f"{base}[?]"
    if node.type == "subscript_expression":
        obj = node.child_by_field_name("object")
        return f"{_callee_name(obj)}[?]"
    return "?"


def _merge_vals(old, new):
    """Join two values: scalar|scalar unions, composite|composite
    merges field-wise, and a shape mismatch collapses the composite
    to its leaf deps (a name can't be both shapes at once)."""
    if old is new:
        # join(x, x) = x — returning `old` keeps the composite's
        # identity, so every other name aliasing it (and every
        # marked shared reference) still sees the same object.
        return old
    if isinstance(old, _Composite) and isinstance(new, _Composite):
        fields = dict(old.fields)
        for key, nval in new.fields.items():
            if key in fields:
                fields[key] = _merge_vals(fields[key], nval)
            else:
                fields[key] = nval
        # Same class keeps method resolution; a class divergence
        # (or a plain literal join) loses it — reads then collapse.
        klass = old.klass if old.klass is new.klass else None
        return _Composite(
            fields, klass, old.deleted | new.deleted
        )
    if isinstance(old, _Composite) or isinstance(new, _Composite):
        return _scalar_of(old) | _scalar_of(new)
    if isinstance(old, _Callable) and isinstance(new, _Callable):
        # Both candidates stay invocable — scalarizing here would
        # stop a later `name(x)`/`o.f(x)` from analyzing the body.
        return _merge_callables(old, new)
    if isinstance(old, _Callable) and isinstance(new, frozenset):
        return _widen_callable(old, new)
    if isinstance(new, _Callable) and isinstance(old, frozenset):
        return _widen_callable(new, old)
    # Two scalars union their leaf deps.
    return _scalar_of(old) | _scalar_of(new)


def _alt_key(alt):
    """Dedup key for alternate candidates: node identity plus the
    bound-argument deps — `f.bind(t, a)` and `f.bind(t, b)` share a
    node but are different partial applications."""
    if alt.bound is None:
        return (id(alt.node), None)
    return (id(alt.node), alt.bound[0])


def _merge_callables(old, new):
    """Join two function values keeping both invocable: the merged
    value is `old` carrying `new` as an extra alternate candidate."""
    if old.node is new.node:
        # Same primary candidate — but `new` may carry alts the
        # branch-local merge already collected (e.g. `g = n`
        # inside a branch merged `n` first, then `_join` merges
        # that result against `old`). Keep every candidate. A
        # differing `bound` makes `new` itself a distinct
        # candidate — `f.bind(t, a)` merged with `f.bind(t, b)`
        # must not drop `b`'s bound actuals.
        extras = list(new.alts)
        if new.bound != old.bound:
            extras.append(new)
        seen = {_alt_key(alt) for alt in old.alts}
        kept = tuple(
            alt for alt in extras if _alt_key(alt) not in seen
        )
        if not kept and not (new.extra - old.extra) and not (
            new.captured - old.captured
        ):
            return old
        merged = _Callable(
            old.node,
            old.params,
            old.defaults,
            old.captured | new.captured,
            old.rest,
            old.is_method,
        )
        merged.param_props = old.param_props
        merged.origin = old.origin
        merged.patterns = old.patterns
        merged.bound = old.bound
        merged.alts = old.alts + kept
        merged.extra = old.extra | new.extra
        return merged
    merged = _Callable(
        old.node,
        old.params,
        old.defaults,
        old.captured | new.captured,
        old.rest,
        old.is_method,
    )
    merged.param_props = old.param_props
    merged.origin = old.origin
    merged.patterns = old.patterns
    merged.bound = old.bound
    merged.alts = old.alts + (new,)
    merged.extra = old.extra | new.extra
    return merged


def _widen_callable(old, deps):
    """Join a function value with scalar deps: stays invocable with
    the deps folded into its extra bucket."""
    widened = _Callable(
        old.node,
        old.params,
        old.defaults,
        old.captured | deps,
        old.rest,
        old.is_method,
    )
    widened.param_props = old.param_props
    widened.origin = old.origin
    widened.patterns = old.patterns
    widened.bound = old.bound
    widened.alts = old.alts
    widened.extra = old.extra | deps
    return widened


def _deep_fields(fields):
    """Structure-only deep copy of a composite's field table for
    the loop fixed-point snapshot — nested `_Composite`s are
    cloned so in-place may-writes can't corrupt the snapshot;
    leaf deps and callables are immutable and shared."""
    out = {}
    for key, val in fields.items():
        if isinstance(val, _Composite):
            out[key] = _Composite(
                _deep_fields(val.fields), val.klass, val.deleted
            )
        else:
            out[key] = val
    return out


def _merge_into(old, new):
    """In-place union of an isolated-candidate world's writes into
    the caller's composite — mutating preserves object identity, so
    every alias (another frame name, an outer caller holding the
    same object) sees the merged writes too."""
    for key, nval in new.fields.items():
        if key in old.fields:
            oval = old.fields[key]
            if isinstance(oval, _Composite) and isinstance(
                nval, _Composite
            ):
                _merge_into(oval, nval)
            else:
                old.fields[key] = _merge_vals(oval, nval)
        else:
            old.fields[key] = nval
    old.deleted |= new.deleted


def _val_leq(new, old) -> bool:
    """`new` adds nothing over `old` — the fixed-point test."""
    if isinstance(old, _Composite) and isinstance(new, _Composite):
        if not new.deleted <= old.deleted:
            # New deletions are new information too.
            return False
        for key, nval in new.fields.items():
            if key not in old.fields or not _val_leq(
                nval, old.fields[key]
            ):
                return False
        return True
    if isinstance(new, _Composite):
        return _scalar_of(new) <= _scalar_of(old)
    if isinstance(old, _Composite):
        return False
    return _scalar_of(new) <= _scalar_of(old)


def _composite_delete(composite, path, span):
    """Copy-on-write `delete composite.path` — removes the leaf
    field and returns the updated `_Composite`."""
    fields = dict(composite.fields)
    deleted = composite.deleted
    key = path[0]
    if len(path) == 1:
        fields.pop(key, None)
        deleted = deleted | {key}
    else:
        sub = fields.get(key)
        if not isinstance(sub, _Composite):
            # The intermediate field is scalar or absent — nothing
            # to delete through.
            raise _Unsupported("unsupported_expression", span)
        fields[key] = _composite_delete(sub, path[1:], span)
    return _Composite(fields, composite.klass, deleted)


def _clone_value(val, memo):
    """Copy-on-write clone for an isolated candidate invocation.

    `_Composite`s deep-clone (callee writes must not reach the
    other candidates' view); `_Callable`s clone shallow — every
    slot is a frozenset or a tuple, so sharing is safe; scalars,
    `_External`s and `_Class`es share (their tables are read-only
    in this model). `memo` keeps intra-frame aliasing intact:
    two names bound to the same object get the same clone."""
    if not isinstance(val, (_Composite, _Callable)):
        return val
    oid = id(val)
    if oid in memo:
        return memo[oid]
    if isinstance(val, _Composite):
        clone = _Composite({}, val.klass, val.deleted)
        memo[oid] = clone
        for key, fval in val.fields.items():
            clone.fields[key] = _clone_value(fval, memo)
        return clone
    clone = _Callable(
        val.node, val.params, val.defaults, val.captured,
        val.rest, val.is_method,
    )
    memo[oid] = clone
    clone.param_props = val.param_props
    clone.origin = val.origin
    clone.patterns = val.patterns
    clone.bound = val.bound
    clone.alts = val.alts
    clone.extra = val.extra
    return clone


def _composite_set(composite, path, value, conditional, span):
    """Copy-on-write member store: `composite.path = value`,
    returning the updated `_Composite`."""
    fields = dict(composite.fields)
    deleted = composite.deleted
    key = path[0]
    if len(path) == 1:
        old = fields.get(key)
        fields[key] = (
            _merge_vals(old, value)
            if conditional and old is not None
            else value
        )
        if not conditional:
            # A definite write resurrects the field.
            deleted = deleted - {key}
    else:
        sub = fields.get(key)
        if not isinstance(sub, _Composite):
            raise _Unsupported("unsupported_expression", span)
        fields[key] = _composite_set(
            sub, path[1:], value, conditional, span
        )
    return _Composite(fields, composite.klass, deleted)


def _pattern_binders(pattern):
    """The local names a destructuring pattern binds. Used to name
    a parameter slot WITHOUT the pattern's raw text — a default
    like `{a = read_secret()}` must not leak source into the
    manifest's `parameters`."""
    names: list = []

    def walk(node):
        if node.type in {
            "identifier",
            "shorthand_property_identifier",
            "shorthand_property_identifier_pattern",
        }:
            names.append(node.text.decode())
            return
        if node.type == "property_identifier":
            return  # a key, not a binding
        if node.type == "assignment_pattern":
            # `{a = default}` — only the left side binds; the
            # default's expression never names anything.
            left = node.child_by_field_name("left")
            if left is not None:
                walk(left)
            return
        if node.type in {"pair", "pair_pattern"}:
            value = node.child_by_field_name("value")
            if value is not None:
                walk(value)
            return
        for child in node.named_children:
            walk(child)

    walk(pattern)
    return names


def _composite_dyn_set(composite, path, value, span):
    """Copy-on-write member store through a dynamic key:
    `composite[k].rest = value`. The target field is unknown, so
    every field is a may-write — a scalar unions the value's
    deps, a `_Callable` widens its captured set (keeping it
    invocable — the real write may not have replaced it), a
    `_Composite` descends the rest of the path (or collapses to
    the union at the last step)."""
    fields = dict(composite.fields)
    key = path[0]
    if key is not None:
        if len(path) == 1:
            old = fields.get(key)
            fields[key] = (
                _merge_vals(old, value) if old is not None else value
            )
        else:
            sub = fields.get(key)
            if not isinstance(sub, _Composite):
                raise _Unsupported("unsupported_expression", span)
            fields[key] = _composite_dyn_set(
                sub, path[1:], value, span
            )
        return _Composite(fields, composite.klass)
    vdeps = _scalar_of(value)
    # The write's key is unknown — a never-named field it may
    # add records its deps in the `"*"` bucket so a later read
    # of a missing key still carries them.
    fields["*"] = fields.get("*", frozenset()) | vdeps
    for fname, fval in fields.items():
        if len(path) > 1 and isinstance(fval, _Composite):
            fields[fname] = _composite_dyn_set(
                fval, path[1:], value, span
            )
        elif isinstance(fval, _Callable):
            widened = _Callable(
                fval.node,
                fval.params,
                fval.defaults,
                fval.captured | vdeps,
                fval.rest,
                fval.is_method,
            )
            widened.param_props = fval.param_props
            widened.origin = fval.origin
            widened.patterns = fval.patterns
            widened.bound = fval.bound
            widened.alts = fval.alts
            widened.extra = fval.extra
            fields[fname] = widened
        else:
            fields[fname] = _scalar_of(fval) | vdeps
    return _Composite(fields, composite.klass, composite.deleted)


def _syntax(raw: bytes):
    try:
        from tree_sitter import Language, Parser
        import tree_sitter_typescript

        root = (
            Parser(Language(tree_sitter_typescript.language_typescript()))
            .parse(raw)
            .root_node
        )
        if root.has_error:
            # `.tsx` sources — JSX lives in the tsx grammar; the
            # plain typescript grammar rejects the syntax
            # entirely. Only retry when the first parse failed.
            root = (
                Parser(Language(tree_sitter_typescript.language_tsx()))
                .parse(raw)
                .root_node
            )
        return None if root.has_error else root
    except (ImportError, ValueError, TypeError, RuntimeError):
        return None


class _Builder:
    """Evaluates one unit's functions in dependency-set space."""

    def __init__(
        self,
        root,
        resolver=None,
        resolving=frozenset(),
        module_cache=None,
        module_digests=None,
        source_path=None,
    ) -> None:
        self.functions: dict[str, object] = {}
        self.classes: dict[str, object] = {}
        self._class_cache: dict[str, object] = {}
        self._fn_cache: dict[str, object] = {}
        # `_Composite` objects shared with an UNSEEN scope — a
        # `this` receiver or a composite actual bound to a
        # parameter. A member write on one mutates its field
        # table in place (the caller's `a` when `this.f = v`
        # ran inside `a.set(...)`); objects local to a scope
        # (e.g. a loop-join artifact) must keep copy-on-write
        # so the fixed-point's pre-write snapshot survives.
        self._aliased_objs: set = set()
        # >0 while evaluating code that may not run (a conditional
        # branch, a loop body, the RHS of `&&`/`||`/`??`, a `?:` arm
        # or a `?.` call): in-place writes to shared composites then
        # UNION instead of replacing, so the skipped-path value
        # survives the join.
        self._may_depth = 0
        # Optional module resolver: maps an import specifier to
        # source text (None = no resolver / unresolvable — the
        # names stay `_External`, the existing over-approximation).
        # `resolving` is the ancestor-specifier stack for cycle
        # detection; `module_cache` shares built export tables
        # across the whole top-level call.
        self.resolver = resolver
        self.resolving = resolving
        # The importing unit's own path — `_resolve_builder`
        # hands it to the resolver so `./`/`../` specifiers
        # resolve against THIS module's directory, not the
        # entry file's. None = no origin (in-memory resolvers).
        self.source_path = source_path
        if resolver is not None:
            try:
                import inspect

                self._resolver_importer = (
                    len(inspect.signature(resolver).parameters) > 1
                )
            except (TypeError, ValueError):
                self._resolver_importer = False
        else:
            self._resolver_importer = False
        self.module_cache = (
            module_cache if module_cache is not None else {}
        )
        # sha256 of every module source the resolver returned —
        # shared across the unit like `module_cache` so the
        # context key covers the whole analyzed input, not just
        # the primary file's bytes.
        self.module_digests = (
            module_digests if module_digests is not None else {}
        )
        # Local name -> value bound by a resolved import.
        self.imported_bindings: dict = {}
        # Exported name -> local name this unit re-exports, and
        # the materialized export table an importer reads.
        self.export_names: dict[str, str] = {}
        self.default_export_node = None
        self.exports: dict = {}
        # A unit is closed when any top-level node is not an
        # admitted kind — ambient declares, namespaces and
        # top-level statements all qualify.
        self.unit_gap: TsGap | None = None
        self.imports: set[str] = set()
        # Module-scope value bindings — top-level declarators
        # evaluated in source order in pass 2, read by `_lookup`
        # after params and before the class/import registries.
        self.module_locals: dict = {}
        # Declarations AND plain statements, in source order —
        # both evaluate in module scope during pass 2 (a
        # statement that can't be modelled closes the unit).
        module_items: list = []
        for child in root.named_children:
            if child.type in _TOP_LEVEL:
                if child.type in {
                    "function_declaration",
                    "generator_function_declaration",
                }:
                    name = child.child_by_field_name("name")
                    if name is not None:
                        self.functions[name.text.decode()] = child
                if child.type in {
                    "class_declaration",
                    "abstract_class_declaration",
                }:
                    name = child.child_by_field_name("name")
                    if name is not None:
                        self.classes[name.text.decode()] = child
                if child.type == "import_statement":
                    self._register_import(child)
                if child.type == "export_statement":
                    # `export` wraps a declaration — strip the
                    # marker and register what it declares; a
                    # `export {}`/`export default`/`export *`
                    # binds nothing the function model reads.
                    self._register_export(child, module_items)
                    for inner in child.named_children:
                        if inner.type in {
                            "function_declaration",
                            "generator_function_declaration",
                        }:
                            name = inner.child_by_field_name("name")
                            if name is not None:
                                self.functions[
                                    name.text.decode()
                                ] = inner
                            elif any(
                                c.type == "default"
                                and not c.is_named
                                for c in child.children
                            ):
                                # `export default function() {}`.
                                self.functions["default"] = inner
                        if inner.type in {
                            "class_declaration",
                            "abstract_class_declaration",
                        }:
                            name = inner.child_by_field_name("name")
                            if name is not None:
                                self.classes[
                                    name.text.decode()
                                ] = inner
                            elif any(
                                c.type == "default"
                                and not c.is_named
                                for c in child.children
                            ):
                                self.classes["default"] = inner
                        if inner.type in {
                            "lexical_declaration",
                            "variable_declaration",
                            "enum_declaration",
                            "internal_module",
                        }:
                            module_items.append(inner)
                if child.type in {
                    "lexical_declaration",
                    "variable_declaration",
                    "enum_declaration",
                    "internal_module",
                }:
                    module_items.append(child)
            else:
                # A top-level statement (`console.log(x)`,
                # `init()`, a module-scope `if`/`for`/...) runs
                # once at import — evaluate it in pass 2 in
                # source order; a statement the model can't
                # express still closes the unit.
                module_items.append(child)
        self.frames: list[dict[str, bool]] = []
        # Function-level scope for `var` bindings, set per body; plus
        # the let/const block-scope save stack and the var-name set.
        self.function_locals: dict[str, frozenset[int]] = {}
        self.var_names: set[str] = set()
        self.block_stack: list[dict[str, frozenset[int] | None]] = []
        # Whether a `throw` on some path unwound the current statement
        # list — statements after it are may-writes until a `catch`
        # consumes the flag or it propagates out of the function.
        self.thrown: list[bool] = [False]
        # The dep union of every `throw` expression since the flag
        # was last consumed — a `catch (e)` binds `e` to it.
        self.thrown_deps: list = [frozenset()]
        # Labels the next loop/switch frame claims — a `break L` or
        # `continue L` looks its frame up by name.
        self.pending_labels: list[str] = []
        # `yield` operand deps collected for the innermost
        # generator body/callable invocation being evaluated.
        self.yield_deps: list[frozenset[int]] = []
        # CommonJS surface — `module.exports`/`exports` seed a
        # shared composite so `exports.g = f` / `module.exports =
        # {...}` bind a real export table a `require` can read.
        # A file that declares `exports` as a local shadows it
        # normally.
        _cjs_table = _Composite({})
        self._cjs_seed = _cjs_table
        # The CJS export table the model tracks precisely: field
        # writes collect into `_cjs_fields`, a whole-table rebind
        # (`module.exports = v`) into `_cjs_whole`. The seeds
        # keep in-module `module`/`exports` reads working under
        # the normal (scalar-collapsing) member model; the
        # require path reads this precise table instead.
        self._cjs_fields = _Composite({})
        self._cjs_whole = None
        # `module.exports = v` (or a bare `exports = v`)
        # detaches the `exports` alias from the live export
        # object — subsequent `exports.x` writes land on the
        # old object and never reach `module.exports`.
        self._cjs_exports_detached = False
        self._invoke_depth = 0
        self.module_locals.setdefault(
            "module", _Composite({"exports": _cjs_table})
        )
        self.module_locals.setdefault("exports", _cjs_table)
        # Pass 2 — evaluate module-scope items in source
        # order now that every function/class name is registered
        # (a `const g = f()` may call a declaration hoisted past
        # its site). `var` writes land in `module_locals` by
        # pointing `function_locals` at it for the pass. An
        # item that can't be modelled closes the unit.
        saved_flocals = self.function_locals
        self.function_locals = self.module_locals
        mcount = [0]
        for node in module_items:
            try:
                if node.type == "enum_declaration":
                    self._register_enum(node)
                elif node.type == "internal_module":
                    self._register_namespace(node)
                elif self._cjs_export_store(node, mcount):
                    pass
                else:
                    self.statement(
                        node,
                        {},
                        self.module_locals,
                        [],
                        mcount,
                        [frozenset()],
                        [False],
                        False,
                    )
            except _Unsupported:
                if self.unit_gap is None:
                    self.unit_gap = TsGap(
                        "unsupported_unit", _span(node)
                    )
                break
        self.function_locals = saved_flocals
        # Materialize the export table an importing builder reads.
        # Anything unmodelable simply isn't exported — the
        # importer's name stays `_External`, the same
        # over-approximation as before resolution existed.
        for exported, local in self.export_names.items():
            value = self._export_value(local)
            if value is not None:
                self.exports[exported] = value
        if self.default_export_node is not None:
            try:
                self.exports["default"] = self._eval(
                    self.default_export_node,
                    {},
                    self.module_locals,
                    [],
                    [0],
                )
            except _Unsupported:
                pass

    def _export_value(self, local):
        """The value bound to a local name for re-export — a
        function/class declaration becomes its callable/class
        value; a module binding or resolved import re-exports
        directly."""
        if local in self.functions:
            try:
                return self._callable_value(
                    self.functions[local], {}, self.module_locals
                )
            except _Unsupported:
                return None
        if local in self.classes:
            try:
                return self._class_value(
                    self.classes[local], {}, self.module_locals
                )
            except _Unsupported:
                return None
        if local in self.module_locals:
            return self.module_locals[local]
        if local in self.imported_bindings:
            return self.imported_bindings[local]
        return None

    def _register_export(self, node, module_items) -> None:
        """Record which local names an `export` statement exposes.
        `export default <expr>` keeps the expression node for
        post-pass-2 evaluation; `export {a, b as c}` maps each
        exported alias to its local name; `export *` exports
        nothing the model reads. `export type {...}` is
        type-level and exports nothing at all."""
        if any(
            c.type == "type" and not c.is_named
            for c in node.children
        ):
            return
        is_default = any(
            c.type == "default" and not c.is_named
            for c in node.children
        )
        has_from = any(
            c.type == "from" and not c.is_named
            for c in node.children
        )
        from_exports = (
            self._resolve_module(node) if has_from else None
        )
        for inner in node.named_children:
            if inner.type == "export_clause":
                for spec in _children(inner):
                    if spec.type != "export_specifier":
                        continue
                    ids = [
                        c for c in spec.children if c.is_named
                    ]
                    if ids:
                        local = ids[0].text.decode()
                        alias = (
                            ids[1].text.decode()
                            if len(ids) > 1
                            else local
                        )
                        if has_from:
                            # `export {a as b} from 'm'` —
                            # re-export the resolved module's
                            # binding directly; an unexported
                            # name exports nothing.
                            if (
                                from_exports is not None
                                and local in from_exports
                            ):
                                self.exports[alias] = (
                                    from_exports[local]
                                )
                        else:
                            self.export_names[alias] = local
                continue
            if inner.type == "namespace_export":
                # `export * as ns from 'm'` — the whole export
                # table under one name.
                nname = next(iter(_children(inner)), None)
                if nname is not None and from_exports is not None:
                    self.exports[nname.text.decode()] = (
                        _Composite(dict(from_exports))
                    )
                continue
            name = inner.child_by_field_name("name")
            if is_default:
                if name is not None:
                    self.export_names["default"] = name.text.decode()
                elif inner.type in {
                    "function_declaration",
                    "class_declaration",
                }:
                    self.export_names["default"] = "default"
                else:
                    # `export default <expr>` — evaluate it in
                    # module scope after pass 2.
                    self.default_export_node = inner
            elif name is not None:
                self.export_names[name.text.decode()] = (
                    name.text.decode()
                )
        if (
            has_from
            and from_exports is not None
            and not any(
                c.type in {"export_clause", "namespace_export"}
                for c in node.named_children
            )
        ):
            # `export * from 'm'` — every named export re-exports
            # (the module's `default` does not pass through `*`).
            for ename, value in from_exports.items():
                if ename != "default":
                    self.exports.setdefault(ename, value)

    def _register_enum(self, node, scope_locals=None) -> None:
        """Bind `enum E { A, B = expr, ... }` as a `_Composite`
        in module scope (or `scope_locals` when declared inside a
        function body). Member values are numbers/strings, so a
        bare member is dep-free and an `enum_assignment` carries
        its initializer's deps — no correlation or increment
        tracking is needed."""
        name = node.child_by_field_name("name")
        if name is None:
            raise _Unsupported("unsupported_unit", _span(node))
        target = (
            self.module_locals if scope_locals is None else scope_locals
        )
        fields: dict = {}
        body = next(
            (c for c in node.children if c.type == "enum_body"),
            None,
        )
        # Member initializers can name earlier members
        # (`B = A + 1`) — they read dep-free numbers, so bind
        # each member into the eval scope as it registers.
        scope = dict(target)
        for member in _children(body or node):
            if member.type == "property_identifier":
                fields[member.text.decode()] = frozenset()
                scope[member.text.decode()] = frozenset()
            elif member.type == "enum_assignment":
                kids = [c for c in member.children if c.is_named]
                if len(kids) < 1:
                    continue
                mname = kids[0].text.decode()
                if len(kids) == 2:
                    fields[mname] = self.expression(
                        kids[1],
                        {},
                        scope,
                        [],
                        [0],
                    )
                else:
                    fields[mname] = frozenset()
                scope[mname] = frozenset()
        target[name.text.decode()] = _Composite(fields)

    def _register_namespace(self, node, scope_locals=None):
        """`namespace N { export const v = e; export function
        g() {} }` — binds `N` to a `_Composite` of its member
        bindings in module scope (or `scope_locals` when nested
        inside another namespace): declarators evaluate in order
        into a namespace scope that sees the enclosing bindings,
        exported functions become callable fields (`N.g()`
        invokes through the member-call path), and an inner
        `internal_module` recurses so `A.B.g(x)` works.
        Anything else closes the whole unit."""
        name = node.child_by_field_name("name")
        body = node.child_by_field_name("body")
        if body is None:
            body = next(
                (c for c in node.children if c.type == "statement_block"),
                None,
            )
        if name is None or body is None:
            raise _Unsupported("unsupported_unit", _span(node))
        parent_scope = (
            self.module_locals if scope_locals is None else scope_locals
        )
        ns_locals = dict(parent_scope)
        fields: dict = {}
        for member in _children(body):
            decl = member
            if member.type == "export_statement":
                decl = next(iter(_children(member)), None)
                if decl is None:
                    continue
            if decl.type in {
                "lexical_declaration",
                "variable_declaration",
            }:
                before = dict(ns_locals)
                self.statement(
                    decl,
                    {},
                    ns_locals,
                    [],
                    [0],
                    [frozenset()],
                    [False],
                    False,
                )
                for n, v in ns_locals.items():
                    if n not in before or before[n] is not v:
                        fields[n] = v
            elif decl.type == "function_declaration":
                fname = decl.child_by_field_name("name")
                if fname is None:
                    raise _Unsupported(
                        "unsupported_unit", _span(member)
                    )
                cval = self._callable_value(decl, {}, ns_locals)
                fields[fname.text.decode()] = cval
                ns_locals[fname.text.decode()] = cval
            elif decl.type == "internal_module":
                # `namespace A { namespace B { ... } }` — the
                # inner namespace's members see the outer
                # scope; it binds a nested `_Composite` field.
                iname, icomp = self._register_namespace(
                    decl, ns_locals
                )
                fields[iname] = icomp
            else:
                raise _Unsupported("unsupported_unit", _span(member))
        comp = _Composite(fields)
        parent_scope[name.text.decode()] = comp
        return name.text.decode(), comp

    def _register_import(self, node) -> None:
        """`import {a, b as c} from 'm'` / `import * as ns` /
        `import d` — each bound name is registered as an
        `_External` in `self.imports`: reading it yields a
        dep-free marker, a call through it records a transfer
        and yields the actuals' union. `import type` binds
        nothing (type-level only) and a bare `import 'm'`
        registers no names."""
        clause = next(
            (c for c in node.children if c.type == "import_clause"),
            None,
        )
        if clause is None:
            return
        # `import type {T}` — an anonymous `type` child marks a
        # type-only import; nothing it names is a runtime value.
        if any(
            c.type == "type" and not c.is_named for c in node.children
        ):
            return
        # (local_name, imported_name) pairs — `import * as ns`
        # uses the `*` marker; a default import reads `default`.
        pairs: list = []
        for child in _children(clause):
            if child.type == "named_imports":
                for spec in _children(child):
                    if spec.type != "import_specifier":
                        continue
                    if any(
                        c.type == "type" and not c.is_named
                        for c in spec.children
                    ):
                        continue
                    ids = [c for c in spec.children if c.is_named]
                    if ids:
                        imported = ids[0].text.decode()
                        local = (
                            ids[1].text.decode()
                            if len(ids) > 1
                            else imported
                        )
                        pairs.append((local, imported))
            elif child.type == "namespace_import":
                iname = next(iter(_children(child)), None)
                if iname is not None:
                    pairs.append((iname.text.decode(), "*"))
            elif child.type == "identifier":
                # Default import — the clause's bare name.
                pairs.append((child.text.decode(), "default"))
        exports = self._resolve_module(node)
        for local, imported in pairs:  # noqa: B007
            bound = False
            if exports is not None:
                if imported == "*":
                    self.imported_bindings[local] = _Composite(
                        dict(exports)
                    )
                    bound = True
                elif imported in exports:
                    self.imported_bindings[local] = exports[imported]
                    bound = True
            if not bound:
                self.imports.add(local)

    def _resolve_module(self, node):
        """Resolve this import's specifier to the imported
        module's export table — `dict` or None. A missing
        resolver, unresolvable specifier, cycle, or unreadable
        module all yield None (the names stay `_External` — the
        same over-approximation as before resolution existed).
        ESM `export`s combine with CommonJS `exports.x`/`module.exports`
        fields for interop; a bound `module.exports` value also
        surfaces under `default`."""
        if self.resolver is None:
            return None
        src_node = next(
            (c for c in node.children if c.type == "string"), None
        )
        if src_node is None:
            return None
        spec = src_node.text.decode().strip("'\"")
        builder = self._resolve_builder(spec)
        if builder is None:
            return None
        exports = dict(builder.exports)
        cjs = builder.cjs_exports
        if isinstance(cjs, _Composite):
            for key, val in cjs.fields.items():
                exports.setdefault(key, val)
        elif cjs is not None:
            exports.setdefault("default", cjs)
        return exports

    def _resolve_builder(self, spec):
        """The resolved module's own `_Builder` — cached per
        top-level call; cycles and chains past MAX_MODULE_DEPTH
        yield None."""
        # Cache/resolving keys carry the importer's path: `./c`
        # means a different file from `sub/b.ts` than from the
        # entry file.
        key = (
            str(self.source_path) if self.source_path else "",
            spec,
        )
        if key in self.module_cache:
            return self.module_cache[key]
        builder = None
        if (
            key not in self.resolving
            and len(self.resolving) < MAX_MODULE_DEPTH
        ):
            raw = (
                self.resolver(spec, self.source_path)
                if self._resolver_importer
                else self.resolver(spec)
            )
            # A filesystem resolver returns the resolved Path so
            # the imported module can in turn resolve ITS relative
            # specifiers against its own directory; a bytes/str
            # result stays keyed on the bare specifier.
            module_ref = spec
            child_path = None
            from pathlib import Path

            if isinstance(raw, Path):
                child_path = str(raw)
                module_ref = child_path
                try:
                    raw = raw.read_bytes()
                except OSError:
                    raw = None
            if isinstance(raw, str):
                raw = raw.encode()
            if isinstance(raw, bytes) and len(raw) <= MAX_SOURCE_BYTES:
                self.module_digests[module_ref] = hashlib.sha256(
                    raw
                ).hexdigest()
                root = _syntax(raw)
                if root is not None:
                    builder = _Builder(
                        root,
                        resolver=self.resolver,
                        resolving=self.resolving | {key},
                        module_cache=self.module_cache,
                        module_digests=self.module_digests,
                        source_path=child_path,
                    )
        self.module_cache[key] = builder
        return builder

    def _require_specifier(self, arguments):
        """`require('./b')` — the literal specifier of a CommonJS
        call, or None for a dynamic argument (`require(name)`),
        which stays external."""
        if arguments is None:
            return None
        named = [
            c
            for c in _children(arguments)
            if c.type not in {"comment"}
        ]
        if len(named) == 1 and named[0].type == "string":
            return named[0].text.decode().strip("'\"")
        return None

    def _resolve_require(self, spec):
        """`require(spec)`'s value — the resolved module's
        `module.exports` (a rebound non-object exports yields
        itself, e.g. `module.exports = function`), or a
        `_Composite` of its ESM exports when the module writes
        none. Unresolvable stays None — the caller falls back to
        the external-callee union."""
        builder = self._resolve_builder(spec)
        if builder is None:
            return None
        cjs = builder.cjs_exports
        if cjs is not None and (
            not isinstance(cjs, _Composite) or cjs.fields
        ):
            return cjs
        if builder.exports:
            return _Composite(dict(builder.exports))
        return cjs if cjs is not None else _Composite({})

    @property
    def cjs_exports(self):
        """This unit's CommonJS `module.exports` value — the
        `exports`/`module.exports` seeds share one composite, so
        `exports.f = g` and `module.exports = {...}` both land
        here. `module.exports = <non-object>` (e.g. a bare
        function) rebinds the field to the value itself."""
        whole = self._cjs_whole
        fields = self._cjs_fields
        if whole is None:
            return fields
        if not fields.fields:
            return whole
        if isinstance(whole, _Composite):
            merged = _Composite(
                dict(whole.fields), deleted=whole.deleted
            )
            for key, val in fields.fields.items():
                if key in merged.fields:
                    merged.fields[key] = _merge_vals(
                        merged.fields[key], val
                    )
                else:
                    merged.fields[key] = val
            return merged
        # A non-object whole-table export plus later field
        # writes — keep both: the value under `default`, the
        # fields beside it (over-approximates — extra bindings
        # only sharpen a caller).
        combined = _Composite(
            dict(fields.fields), deleted=fields.deleted
        )
        combined.fields.setdefault("default", whole)
        return combined

    def _cjs_export_store(self, node, count) -> bool:
        """`module.exports = v` / `module.exports.x = v` /
        `exports.x = v` at module level — capture the evaluated
        VALUE (callable/composite preserved) into the CJS export
        table, where the normal member-store model would
        collapse it to scalar deps. Returns True when the
        statement was consumed; deeper paths and any other
        statement fall through to `statement()`."""
        if node.type != "expression_statement" or not node.named_children:
            return False
        stmt = node.named_children[0]
        if stmt.type != "assignment_expression":
            return False
        if any(
            c.type == "augmented_operator" for c in stmt.children
        ):
            return False
        left = stmt.child_by_field_name("left")
        right = stmt.child_by_field_name("right")
        if left is None or right is None:
            return False
        base_node, path = left, []
        while base_node.type == "member_expression":
            prop = base_node.child_by_field_name("property")
            if prop is None or prop.type != "property_identifier":
                return False
            path.append(prop.text.decode())
            base_node = base_node.child_by_field_name("object")
        if base_node.type != "identifier":
            return False
        base = base_node.text.decode()
        path = list(reversed(path))
        if base == "module":
            if not path or path[0] != "exports":
                return False
            path = path[1:]
        elif base != "exports":
            return False
        if len(path) > 1:
            return False
        value = self._eval(
            right, {}, self.module_locals, [], count
        )
        if base == "module":
            if not path:
                # `module.exports = v` — the whole table
                # rebinds: earlier `exports.*` writes die with
                # the old object, and the `exports` name
                # detaches (it still aliases that object).
                # Re-aliasing the LIVE table
                # (`module.exports = exports`) keeps it:
                # `exports.*` writes still reach the export.
                self._cjs_whole = value
                if (
                    value is not self._cjs_fields
                    and value is not self._cjs_seed
                ):
                    self._cjs_fields = _Composite({})
                    self._cjs_exports_detached = True
                return True
            self._cjs_fields.fields[path[0]] = value
            return True
        if self._cjs_exports_detached:
            # `exports` still names the detached object — its
            # writes never reach `module.exports`.
            return True
        if not path:
            # `exports = v` rebinds the local alias only —
            # `module.exports` itself is untouched.
            self._cjs_exports_detached = True
            return True
        self._cjs_fields.fields[path[0]] = value
        return True

    def _register_nested_functions(self, node, params, locals_) -> None:
        """Register every `function inner() {}` declaration under
        `node` in the unit's call table AND bind it in `locals_`
        as a `_Callable` — function declarations hoist within
        their enclosing function, so calls resolve wherever they
        appear and free-variable reads see the call site's
        bindings (closures capture by reference). The call-table
        entry stays so the body is also summarized as a unit
        function."""
        if node.type in {
            "function_declaration",
            "generator_function_declaration",
        }:
            inner_name = node.child_by_field_name("name")
            if inner_name is not None:
                self.functions[inner_name.text.decode()] = node
                try:
                    locals_[inner_name.text.decode()] = (
                        self._callable_value(node, params, locals_)
                    )
                except _Unsupported:
                    # A declaration the callable model can't
                    # represent (destructured/typed-non-scalar
                    # params) stays in the call table only.
                    pass
            return
        for child in _children(node):
            self._register_nested_functions(child, params, locals_)

    def _hoist_var_names(self, body_node):
        """Every `var` declarator name visible anywhere inside a
        function body — `var` hoists to the enclosing function,
        so a use before the declarator still sees the binding.
        Nested function/class scopes are excluded: their `var`s
        hoist inside their own frame, never into this one."""
        names: set = set()
        stack = list(_children(body_node)) if body_node is not None else []
        while stack:
            n = stack.pop()
            if n.type in {
                "arrow_function",
                "function_expression",
                "function_declaration",
                "generator_function_declaration",
                "generator_function",
                "class_declaration",
                "abstract_class_declaration",
                "class",
                "method_definition",
            }:
                continue
            if n.type == "variable_declaration":
                for decl in _children(n):
                    if decl.type != "variable_declarator":
                        continue
                    pname = decl.child_by_field_name("name")
                    if pname is None:
                        continue
                    if pname.type == "identifier":
                        names.add(pname.text.decode())
                    elif pname.type in {
                        "object_pattern",
                        "array_pattern",
                    }:
                        names.update(self._pattern_bound_names(pname))
                continue
            stack.extend(_children(n))
        return names

    def summarize_all(self) -> tuple[TsFunctionSummary, ...]:
        # Summarizing a body can register nested function
        # declarations — walk the table to a fixed point.
        results: list[TsFunctionSummary] = []
        seen: set[int] = set()
        queue = list(self.functions.values())
        i = 0
        while i < len(queue):
            node = queue[i]
            i += 1
            if id(node) in seen:
                continue
            seen.add(id(node))
            # Each top-level function summarizes against a clean
            # module scope: a module-local written inside one
            # function must not carry that function's parameter
            # indices into the next function's summary — `m = a`
            # inside `f` makes `g`'s `m` read external, never
            # `a`. Writes a callee performs DURING one function's
            # analysis still propagate inside that analysis.
            self._scrub_module_deps()
            results.append(self.summarize(node))
            for inner in self.functions.values():
                if id(inner) not in seen:
                    queue.append(inner)
        return tuple(results)

    def _scrub_module_deps(self) -> None:
        """Empty every scalar dep-set reachable from module scope.

        Module-level initializers run with no params, so any
        non-empty frozenset there can only hold a just-finished
        function's parameter indices. Composites keep their shape
        (fields are scrubbed recursively); callables keep their
        identity and captured set (only a def-site can set those,
        and a def-site never sees params)."""

        def scrub(val, memo):
            if isinstance(val, _Composite):
                # Memoized copy — `a`/`b` aliasing one object keep
                # aliasing (and a cyclic table can't recurse
                # forever).
                oid = id(val)
                if oid in memo:
                    return memo[oid]
                out = _Composite({}, val.klass, val.deleted)
                memo[oid] = out
                out.fields.update(
                    {
                        k: scrub(v, memo)
                        for k, v in val.fields.items()
                    }
                )
                return out
            if isinstance(val, frozenset):
                return frozenset()
            return val

        memo: dict = {}
        for name in list(self.module_locals):
            self.module_locals[name] = scrub(
                self.module_locals[name], memo
            )

    def summarize(self, node) -> TsFunctionSummary:
        name_node = node.child_by_field_name("name")
        if name_node is None:
            return TsFunctionSummary(
                "",
                False,
                (),
                None,
                (),
                (TsGap("unsupported_signature", _span(node)),),
                (),
                "unknown",
            )
        name = name_node.text.decode()
        if self.unit_gap is not None:
            return TsFunctionSummary(
                name, False, (), None, (), (self.unit_gap,), (), "unknown"
            )
        try:
            return self.body(node, name)
        except _Unsupported as u:
            return TsFunctionSummary(
                name, False, (), None, (),
                (TsGap(u.reason, u.span, u.callee),), (), "unknown",
            )

    def body(self, node, name: str) -> TsFunctionSummary:
        # Signature gates: named function, every parameter a scalar
        # `identifier: number|boolean`, a declared scalar return type
        # and a statement_block body. `function*` admits: the
        # model has no iterator slot, so each `yield`'s operand deps
        # union into the function's own return deps — the iterated
        # values are exactly what the over-approximation reports.
        # `async` admits since `await` degrades to operand deps in
        # the dep model (a promise resolves to its value).
        params_node = node.child_by_field_name("parameters")
        body = node.child_by_field_name("body")
        if params_node is None or body is None or body.type != "statement_block":
            raise _Unsupported("unsupported_signature", _span(node))
        # Any return annotation — or none — admits: annotations
        # are type-level and recorded deps come from the actual
        # `return` statements regardless.
        params: dict[str, int] = {}
        destructured: list = []
        rest_seen = False
        for param in _children(params_node):
            # `x?: number` and `x: number = 0` admit like a required
            # parameter — the index position is what the summary
            # records; an omitted argument is the caller's concern.
            if param.type not in {"required_parameter", "optional_parameter"}:
                raise _Unsupported("unsupported_signature", _span(param))
            pattern = param.child_by_field_name("pattern")
            if rest_seen:
                raise _Unsupported("unsupported_signature", _span(param))
            if pattern is not None and pattern.type == "rest_pattern":
                # `...rest` occupies the last slot; the index's dep
                # stands for "args at this index and beyond" — the
                # call arm already unions every evaluated argument,
                # so reading `rest` is sound under the index model.
                target = next(iter(_children(pattern)), None)
                if target is None or target.type != "identifier":
                    raise _Unsupported(
                        "unsupported_signature", _span(param)
                    )
                pname = target.text.decode()
                if pname in params:
                    raise _Unsupported(
                        "unsupported_signature", _span(param)
                    )
                params[pname] = len(params)
                rest_seen = True
                continue
            if pattern is not None and pattern.type in {
                "object_pattern",
                "array_pattern",
            }:
                # `f({a, b}, [x])` — the slot still occupies one
                # scalar index; the pattern's sub-names destructure
                # it at body start (each sees the whole slot's deps).
                binders = _pattern_binders(pattern)
                if not binders:
                    raise _Unsupported(
                        "unsupported_signature", _span(param)
                    )
                pname = (
                    "[" if pattern.type == "array_pattern" else "{"
                ) + ", ".join(sorted(binders)) + (
                    "]" if pattern.type == "array_pattern" else "}"
                )
                if pname in params:
                    pname = f"{pname}#{len(params)}"
                if pname in params:
                    raise _Unsupported(
                        "unsupported_signature", _span(param)
                    )
                params[pname] = len(params)
                destructured.append((pattern, params[pname]))
                continue
            if pattern is None or pattern.type != "identifier":
                raise _Unsupported("unsupported_signature", _span(param))
            # The annotation is type-level — `f(o: Foo)` binds the
            # index like `f(x: number)`: actuals scalarize at the
            # call site, so any annotation (or none) admits.
            pname = pattern.text.decode()
            if pname in params:
                raise _Unsupported("unsupported_signature", _span(param))
            params[pname] = len(params)

        locals_: dict[str, object] = {}
        self.function_locals = locals_
        self.var_names = set()
        self.block_stack = []
        self.thrown = [False]
        self.thrown_deps = [frozenset()]
        self.pending_labels = []
        transfers: list[TsCall] = []
        count = [0]
        deps = [frozenset()]
        # A default value evaluates only on a missing argument, but its
        # calls still belong to this function's behavior — evaluate it
        # for transfers with no local scope yet.
        for param in _children(params_node):
            default = param.child_by_field_name("value")
            if default is not None:
                self.expression(
                    default, params, locals_, transfers, count
                )
        # Destructured parameters bind their sub-names to member
        # reads of the slot — a scalar slot unions into every name.
        for pat, idx in destructured:
            self._destructure(
                pat,
                frozenset({idx}),
                params,
                locals_,
                transfers,
                count,
                False,
                False,
                _span(pat),
            )
        if params:
            # `arguments` — every element over-approximates to the
            # whole parameter union.
            arg_union = frozenset(params.values())
            locals_["arguments"] = _Composite(
                {str(i): arg_union for i in range(len(params))}
            )
        # Function declarations hoist to the enclosing function's
        # scope — pre-register every `function inner() {}` in the
        # body subtree so calls resolve wherever they appear.
        for inner_decl in body.children:
            self._register_nested_functions(inner_decl, params, locals_)
        # `var` declarations hoist to function scope — seed the
        # name set and an `undefined` (∅) binding so reads and
        # writes before the declarator see the name. A `var`
        # name that is also a parameter shares its slot —
        # seeding ∅ would shadow the argument's deps.
        for vname in self._hoist_var_names(body):
            self.var_names.add(vname)
            if vname not in params:
                locals_.setdefault(vname, frozenset())
        self.frames = []
        saw_return = [False]
        saved_yields, self.yield_deps = self.yield_deps, []
        self._sequence(
            _children(body), params, locals_, transfers, count, deps,
            saw_return, False,
        )
        result_deps = deps[0] if saw_return[0] else frozenset()
        for ydeps in self.yield_deps:
            result_deps |= ydeps
        self.yield_deps = saved_yields
        return TsFunctionSummary(
            name,
            True,
            tuple(params.keys()),
            result_deps,
            tuple(sorted(transfers, key=lambda c: (c.span.start, c.span.end))),
            (),
            (),
            "unknown" if transfers else "none_in_supported_fragment",
        )

    def _sequence(
        self,
        children,
        params,
        locals_,
        transfers,
        count,
        deps,
        saw_return,
        conditional,
    ) -> None:
        for child in children:
            if (
                any(f["exited"] for f in self.frames)
                or self.thrown[0]
            ):
                conditional = True
            self.statement(
                child, params, locals_, transfers, count, deps,
                saw_return, conditional,
            )

    @staticmethod
    def _store(locals_, params, name, value, conditional) -> None:
        if conditional:
            if name in locals_:
                # The skipped path keeps the binding's CURRENT value.
                value = _merge_vals(locals_[name], value)
            elif name in params:
                # A parameter is a scalar slot — a composite stored
                # into it collapses to the union of its leaf deps.
                value = frozenset({params[name]}) | _scalar_of(value)
        locals_[name] = value

    def _declare_name(
        self, name, value, is_var, conditional, params, locals_
    ) -> None:
        """Bind a declared name honouring `var`'s function scope and
        let/const block-scope restore."""
        if is_var:
            # `var` is function-scoped: it lands in the current
            # scope and the joins carry the name outward — writing
            # the function scope directly would bypass a loop's
            # fixed-point join and lose the zero-trip path's
            # dependencies.
            self.var_names.add(name)
            self._store(locals_, params, name, value, conditional)
        else:
            if self.block_stack:
                saved = self.block_stack[-1]
                if name not in saved:
                    saved[name] = locals_.get(name)
            self._store(locals_, params, name, value, conditional)

    def _bind_target(
        self, name, value, is_var, conditional, params, locals_,
        declare, span,
    ) -> None:
        """Leaf binding of a destructure — a declaration binds via
        `_declare_name`; an assignment destructuring (`({a} = o)`)
        writes the existing binding through `_write_scope`."""
        if declare:
            self._declare_name(
                name, value, is_var, conditional, params, locals_
            )
            return
        scope = self._write_scope(name, locals_, params)
        if scope is None:
            raise _Unsupported("binding_unavailable", span)
        self._store(scope, params, name, value, conditional)

    def _destructure(
        self,
        pattern,
        value,
        params,
        locals_,
        transfers,
        count,
        is_var,
        conditional,
        span,
        declare=True,
    ) -> None:
        """`const {a, b: c = d, ...rest} = o` / `const [x, y] = arr` —
        each sub-name binds the member read at its path; a scalar
        source or a `...rest` binding over-approximates to the whole
        union. A composite member binds as a scalar (member-path
        rule — sub-object writes can't diverge)."""
        positions: dict[int, int] = {}
        if pattern.type == "array_pattern":
            # A hole (`[a, , b]`) emits no named child — walk ALL
            # children: an empty slot is a comma seen while an
            # element is expected.
            pos = 0
            expecting = True
            for c in pattern.children:
                if c.type in {"[", "]"}:
                    continue
                if c.type == ",":
                    if expecting:
                        pos += 1
                    else:
                        expecting = True
                    continue
                positions[c.id] = pos
                pos += 1
                expecting = False
        for child in _children(pattern):
            if child.type == "rest_pattern":
                inner = next(iter(_children(child)), None)
                if inner is None or inner.type != "identifier":
                    raise _Unsupported("binding_unavailable", span)
                # The remaining fields are unknowable — the whole
                # union over-approximates.
                self._bind_target(
                    inner.text.decode(),
                    _scalar_of(value),
                    is_var,
                    conditional,
                    params,
                    locals_,
                    declare,
                    span,
                )
                continue
            if child.type == "pair_pattern":
                if pattern.type != "object_pattern":
                    raise _Unsupported("binding_unavailable", span)
                key = child.child_by_field_name("key")
                target = child.child_by_field_name("value")
                if key is None or target is None or key.type not in {
                    "property_identifier",
                    "string",
                    "number",
                }:
                    raise _Unsupported("binding_unavailable", span)
                kname = (
                    key.text.decode().strip("\"'")
                    if key.type == "string"
                    else key.text.decode()
                )
                fval = self._pattern_read(value, kname)
                self._destructure_target(
                    target, fval, params, locals_, transfers, count,
                    is_var, conditional, span, declare,
                )
                continue
            if pattern.type == "array_pattern":
                key = str(positions[child.id])
                self._destructure_target(
                    child,
                    self._pattern_read(value, key),
                    params,
                    locals_,
                    transfers,
                    count,
                    is_var,
                    conditional,
                    span,
                    declare,
                )
                continue
            if child.type in {
                "shorthand_property_identifier",
                "shorthand_property_identifier_pattern",
                "object_assignment_pattern",
            }:
                if child.type in {
                    "shorthand_property_identifier",
                    "shorthand_property_identifier_pattern",
                }:
                    name = child.text.decode()
                    self._bind_target(
                        name,
                        _scalar_of(self._pattern_read(value, name)),
                        is_var,
                        conditional,
                        params,
                        locals_,
                        declare,
                        span,
                    )
                    continue
                left = child.child_by_field_name("left")
                right = child.child_by_field_name("right")
                if left is None or left.type not in {
                    "identifier",
                    "shorthand_property_identifier_pattern",
                }:
                    raise _Unsupported("binding_unavailable", span)
                name = left.text.decode()
                deps = _scalar_of(self._pattern_read(value, name))
                if right is not None:
                    deps |= self.expression(
                        right, params, locals_, transfers, count
                    )
                self._bind_target(
                    name, deps, is_var, conditional, params, locals_,
                    declare, span,
                )
                continue
            raise _Unsupported("binding_unavailable", span)

    def _destructure_target(
        self,
        target,
        fval,
        params,
        locals_,
        transfers,
        count,
        is_var,
        conditional,
        span,
        declare=True,
    ) -> None:
        if target.type in {"member_expression", "subscript_expression"}:
            # `({a: o.f} = src)` — only legal in assignment
            # destructuring; writes the member like `_member_store`.
            if declare:
                raise _Unsupported("binding_unavailable", span)
            self._member_store(
                target,
                _scalar_of(fval),
                params,
                locals_,
                transfers,
                count,
                conditional,
            )
            return
        if target.type == "identifier":
            self._bind_target(
                target.text.decode(),
                _scalar_of(fval),
                is_var,
                conditional,
                params,
                locals_,
                declare,
                span,
            )
            return
        if target.type in {
            "assignment_pattern",
            "object_assignment_pattern",
        }:
            left = target.child_by_field_name("left")
            right = target.child_by_field_name("right")
            if left is None or left.type != "identifier":
                raise _Unsupported("binding_unavailable", span)
            deps = _scalar_of(fval)
            if right is not None:
                deps |= self.expression(
                    right, params, locals_, transfers, count
                )
            self._bind_target(
                left.text.decode(),
                deps,
                is_var,
                conditional,
                params,
                locals_,
                declare,
                span,
            )
            return
        if target.type in {"object_pattern", "array_pattern"}:
            self._destructure(
                target,
                fval,
                params,
                locals_,
                transfers,
                count,
                is_var,
                conditional,
                span,
                declare,
            )
            return
        raise _Unsupported("binding_unavailable", span)

    @staticmethod
    def _pattern_read(value, key):
        """Field `key` of a destructured composite — a scalar source
        over-approximates every sub-name to the whole union. A
        missing key falls back to the `"*"` bucket — a defaulted
        destructured parameter seeds it with the default's deps."""
        if isinstance(value, _Composite):
            return value.fields.get(
                key, value.fields.get("*", frozenset())
            )
        return value

    @staticmethod
    def _pattern_bound_names(pattern):
        """Every identifier a destructuring pattern binds — used to
        scope-restore `catch ({m})` parameters. Default expressions
        (`{m = d}`) and member/subscript targets contribute no
        names."""
        names: list = []
        stack = [pattern]
        while stack:
            n = stack.pop()
            if n.type in {
                "identifier",
                "shorthand_property_identifier",
                "shorthand_property_identifier_pattern",
            }:
                names.append(n.text.decode())
            elif n.type in {
                "assignment_pattern",
                "object_assignment_pattern",
            }:
                # Only `left` binds — `right` is a default expr.
                left = n.child_by_field_name("left")
                if left is not None:
                    stack.append(left)
            elif n.type == "pair_pattern":
                value = n.child_by_field_name("value")
                if value is not None:
                    stack.append(value)
            elif n.type in {
                "object_pattern",
                "array_pattern",
                "rest_pattern",
            }:
                stack.extend(
                    c for c in n.children if c.is_named
                )
            # Anything else (member/subscript targets, stray
            # expressions) binds no names — declare-mode
            # destructuring rejects them anyway.
        return names

    def statement(
        self,
        node,
        params,
        locals_,
        transfers,
        count,
        deps,
        saw_return,
        conditional,
    ) -> None:
        if conditional:
            self._may_depth += 1
            try:
                self._statement(
                    node, params, locals_, transfers, count, deps,
                    saw_return, conditional,
                )
            finally:
                self._may_depth -= 1
            return
        self._statement(
            node, params, locals_, transfers, count, deps,
            saw_return, conditional,
        )

    def _statement(
        self,
        node,
        params,
        locals_,
        transfers,
        count,
        deps,
        saw_return,
        conditional,
    ) -> None:
        count[0] += 1
        if count[0] > MAX_NODES:
            raise _Unsupported("analysis_limit", _span(node))
        kind = node.type
        if kind == "statement_block":
            # let/const bound in the block are restored on exit — only
            # `var` bindings (function-scoped) and assignments to outer
            # names escape.
            saved: dict[str, frozenset[int] | None] = {}
            self.block_stack.append(saved)
            try:
                self._sequence(
                    _children(node), params, locals_, transfers, count,
                    deps, saw_return, conditional,
                )
            finally:
                for name, prev in saved.items():
                    if prev is None:
                        locals_.pop(name, None)
                    else:
                        locals_[name] = prev
                self.block_stack.pop()
            return
        if kind in {"comment", "empty_statement", "debugger_statement"}:
            return
        if kind == "return_statement":
            exprs = _children(node)
            if len(exprs) == 0:
                # A bare `return` tracks no result dependencies.
                saw_return[0] = True
                return
            if len(exprs) != 1:
                raise _Unsupported("unsupported_return", _span(node))
            deps[0] |= self.expression(
                exprs[0], params, locals_, transfers, count
            )
            saw_return[0] = True
            return
        if kind in {"lexical_declaration", "variable_declaration"}:
            is_var = kind == "variable_declaration"
            declarators = [
                c for c in _children(node) if c.type == "variable_declarator"
            ]
            if not declarators:
                raise _Unsupported("unsupported_statement", _span(node))
            for decl in declarators:
                pname = decl.child_by_field_name("name")
                if pname is None:
                    raise _Unsupported("binding_unavailable", _span(decl))
                # The annotation is type-level — `const o: {…} = v`
                # evaluates `v` the same regardless, so any
                # annotation admits.
                value = decl.child_by_field_name("value")
                if pname.type in {"object_pattern", "array_pattern"}:
                    if value is None:
                        raise _Unsupported(
                            "binding_unavailable", _span(decl)
                        )
                    val_v = self._eval(
                        value, params, locals_, transfers, count
                    )
                    self._destructure(
                        pname,
                        val_v,
                        params,
                        locals_,
                        transfers,
                        count,
                        is_var,
                        conditional,
                        _span(decl),
                    )
                    continue
                if pname.type != "identifier":
                    raise _Unsupported("binding_unavailable", _span(decl))
                deps_v = (
                    self._bindable(
                        value,
                        self._eval(
                            value, params, locals_, transfers, count
                        ),
                    )
                    if value is not None
                    # `let x;` binds `undefined` — no dependencies.
                    else frozenset()
                )
                vname = pname.text.decode()
                if (
                    is_var
                    and value is None
                    and (vname in locals_ or vname in params)
                ):
                    # `var a;` hoists without clearing — an
                    # already-bound name keeps its deps.
                    continue
                self._declare_name(
                    vname,
                    deps_v,
                    is_var,
                    conditional,
                    params,
                    locals_,
                )
            return
        if kind in {
            "class_declaration",
            "abstract_class_declaration",
        }:
            # `class C { ... }` in a body — binds a `_Class` (no
            # hoisting: declaration order applies).
            name_node = node.child_by_field_name("name")
            if name_node is None:
                raise _Unsupported("unsupported_statement", _span(node))
            self._declare_name(
                name_node.text.decode(),
                self._class_value(node, params, locals_),
                False,
                conditional,
                params,
                locals_,
            )
            return
        if kind == "function_declaration":
            # Already registered by the hoisting pass — a declaration
            # statement evaluates to nothing.
            return
        if kind == "enum_declaration":
            # `enum E { ... }` inside a body binds its composite in
            # the local scope (enums are block-scoped values).
            self._register_enum(node, locals_)
            return
        if kind == "expression_statement":
            self._expression_statement(
                node, params, locals_, transfers, count, deps,
                saw_return, conditional,
            )
            return
        if kind == "if_statement":
            condition = node.child_by_field_name("condition")
            consequence = node.child_by_field_name("consequence")
            if condition is None or consequence is None:
                raise _Unsupported("unsupported_statement", _span(node))
            self.expression(condition, params, locals_, transfers, count)
            branch = dict(locals_)
            self.statement(
                consequence, params, branch, transfers, count, deps,
                saw_return, True,
            )
            self._join(locals_, branch, params, self.var_names)
            alternative = node.child_by_field_name("alternative")
            if alternative is not None:
                branch = dict(locals_)
                if alternative.type == "else_clause":
                    inner = _children(alternative)
                    if len(inner) != 1:
                        raise _Unsupported(
                            "unsupported_statement", _span(alternative)
                        )
                    alternative = inner[0]
                self.statement(
                    alternative, params, branch, transfers, count, deps,
                    saw_return, True,
                )
                self._join(locals_, branch, params, self.var_names)
            return
        if kind == "while_statement":
            condition = node.child_by_field_name("condition")
            body = node.child_by_field_name("body")
            if condition is None or body is None:
                raise _Unsupported("unsupported_statement", _span(node))
            self._loop(
                body, None, condition, params, locals_, transfers, count,
                deps, saw_return, conditional, node,
            )
            return
        if kind == "for_statement":
            body = node.child_by_field_name("body")
            if body is None:
                raise _Unsupported("unsupported_statement", _span(node))
            scope = dict(locals_)
            # `let`/`const` in the initializer are scoped to the loop:
            # they register in a for-local restore map, never the
            # enclosing block's — otherwise the block's exit would
            # rewind assignments made after the loop.
            for_saved: dict[str, frozenset[int] | None] = {}
            self.block_stack.append(for_saved)
            try:
                initializer = node.child_by_field_name("initializer")
                if (
                    initializer is not None
                    and initializer.type == "empty_statement"
                ):
                    # `for(;cond;)` — the empty slot parses as an
                    # `empty_statement`; treat it as absent.
                    initializer = None
                if initializer is not None:
                    self._for_part(
                        initializer, params, scope, transfers, count,
                        deps, saw_return, conditional,
                    )
                condition = node.child_by_field_name("condition")
                if (
                    condition is not None
                    and condition.type == "empty_statement"
                ):
                    condition = None
                increment = node.child_by_field_name("increment")
                if (
                    increment is not None
                    and increment.type == "empty_statement"
                ):
                    increment = None
                self._loop(
                    body, increment, condition, params, scope,
                    transfers, count, deps, saw_return, conditional,
                    node,
                )
            finally:
                for name, prev in for_saved.items():
                    if prev is None:
                        scope.pop(name, None)
                    else:
                        scope[name] = prev
                self.block_stack.pop()
            self._join(locals_, scope, params, self.var_names)
            return
        if kind == "for_in_statement":
            # `for (const k in o)` iterates a composite's fields — the
            # key is an opaque string (dep-free); `for (const e of v)`
            # iterates values — the element binds the union of every
            # field's deps, or the scalar's whole dep set when the
            # right side isn't a composite (`Object.entries(o)`,
            # `Object.keys(o)` — over-approximation: no arrays).
            left = node.child_by_field_name("left")
            right = node.child_by_field_name("right")
            kind_node = node.child_by_field_name("kind")
            op = node.child_by_field_name("operator")
            body = node.child_by_field_name("body")
            if (
                left is None
                or right is None
                or op is None
                or body is None
                or left.type not in {
                    "identifier",
                    "object_pattern",
                    "array_pattern",
                }
                or (kind_node is not None and kind_node.type not in {
                    "let", "const", "var",
                })
            ):
                raise _Unsupported("unsupported_statement", _span(node))
            iterated = self._eval(right, params, locals_, transfers, count)
            scope = dict(locals_)
            if op.type == "in":
                element = frozenset()
            else:
                # `for (const e of v)` — a composite's element is
                # the field union; a scalar iterated value (a call
                # result like `Object.entries(o)`) binds its whole
                # dep set, an over-approximation.
                element = _scalar_of(iterated)
            is_var = kind_node is not None and kind_node.type == "var"
            for_saved: dict[str, object] = {}
            self.block_stack.append(for_saved)
            try:
                if left.type in {"object_pattern", "array_pattern"}:
                    # `for (const {a, b} of rows)` — each iteration
                    # destructures the element; declared names land
                    # in the loop scope (`_declare_name` records the
                    # block restore itself), a bare pattern assigns.
                    self._destructure(
                        left,
                        element,
                        params,
                        scope,
                        transfers,
                        count,
                        is_var,
                        True,
                        _span(left),
                        declare=kind_node is not None,
                    )
                elif kind_node is not None:
                    kname = left.text.decode()
                    if is_var:
                        self.var_names.add(kname)
                    else:
                        for_saved[kname] = scope.get(kname)
                    scope[kname] = element
                else:
                    # `for (k in o)` — an assignment target: the loop
                    # may not run, so the bind is a may-write.
                    kname = left.text.decode()
                    target = self._write_scope(kname, scope, params)
                    if target is None:
                        raise _Unsupported(
                            "binding_unavailable", _span(left)
                        )
                    self._store(target, params, kname, element, True)
                self._loop(
                    body, None, None, params, scope, transfers, count,
                    deps, saw_return, conditional, node,
                )
            finally:
                for sname, prev in for_saved.items():
                    if prev is None:
                        scope.pop(sname, None)
                    else:
                        scope[sname] = prev
                self.block_stack.pop()
            self._join(locals_, scope, params, self.var_names)
            return
        if kind == "switch_statement":
            value = node.child_by_field_name("value")
            body = node.child_by_field_name("body")
            if value is None or body is None:
                raise _Unsupported("unsupported_statement", _span(node))
            self.expression(value, params, locals_, transfers, count)
            # Fallthrough: a `break` only ends paths that entered at an
            # earlier clause — each clause can still be entered
            # directly, so every body is processed as a may-write in a
            # shared scope (a clause with no statements simply adds
            # nothing before the next).
            frame = {
                "exited": False, "broke": False,
                "broke_always": False, "loop": False,
                "label": (
                    self.pending_labels.pop()
                    if self.pending_labels
                    else None
                ),
            }
            self.frames.append(frame)
            # `let`/`const` in a clause share the switch's block scope —
            # they restore when the switch ends, not at the enclosing
            # block's exit.
            saved: dict[str, frozenset[int] | None] = {}
            self.block_stack.append(saved)
            try:
                scope = dict(locals_)
                for clause in _children(body):
                    if clause.type not in {"switch_case", "switch_default"}:
                        raise _Unsupported(
                            "unsupported_statement", _span(clause)
                        )
                    if clause.type == "switch_case":
                        case_value = clause.child_by_field_name("value")
                        if case_value is None:
                            raise _Unsupported(
                                "unsupported_statement", _span(clause)
                            )
                        self.expression(
                            case_value, params, scope, transfers, count
                        )
                    frame["exited"] = False
                    self._sequence(
                        [
                            c
                            for i, c in enumerate(clause.children)
                            if clause.field_name_for_child(i) == "body"
                        ],
                        params, scope, transfers, count, deps,
                        saw_return, True,
                    )
                for name, prev in saved.items():
                    if prev is None:
                        scope.pop(name, None)
                    else:
                        scope[name] = prev
                self._join(locals_, scope, params, self.var_names)
            finally:
                self.block_stack.pop()
                self.frames.pop()
            return
        if kind == "do_statement":
            body = node.child_by_field_name("body")
            condition = node.child_by_field_name("condition")
            if body is None or condition is None:
                raise _Unsupported("unsupported_statement", _span(node))
            # The body runs at least once — a distinction the
            # union-joined fixed point does not model, so it shares
            # the `while` loop shape.
            self._loop(
                body, None, condition, params, locals_, transfers, count,
                deps, saw_return, conditional, node,
            )
            return
        if kind == "throw_statement":
            thrown_expr = next(iter(_children(node)), None)
            if thrown_expr is not None:
                self.thrown_deps[0] |= self.expression(
                    thrown_expr, params, locals_, transfers, count
                )
            # The throw unwinds to the nearest `catch` or out of the
            # function — every later statement is a may-write until a
            # `catch` clears the flag.
            self.thrown[0] = True
            return
        if kind == "try_statement":
            body = node.child_by_field_name("body")
            handler = node.child_by_field_name("handler")
            finalizer = node.child_by_field_name("finalizer")
            if body is None or (
                handler is None and finalizer is None
            ):
                raise _Unsupported("unsupported_statement", _span(node))
            catch_body = None
            if handler is not None:
                catch_body = handler.child_by_field_name("body")
                catch_param = handler.child_by_field_name("parameter")
                if catch_body is None or (
                    catch_param is not None
                    and catch_param.type
                    not in {
                        "identifier",
                        "object_pattern",
                        "array_pattern",
                    }
                ):
                    raise _Unsupported(
                        "unsupported_statement", _span(handler)
                    )
            fin_body = None
            if finalizer is not None:
                fin_body = finalizer.child_by_field_name("body")
                if fin_body is None:
                    raise _Unsupported(
                        "unsupported_statement", _span(finalizer)
                    )
            self.statement(
                body, params, locals_, transfers, count, deps,
                saw_return, conditional,
            )
            propagated = self.thrown[0]
            self.thrown[0] = False
            catch_deps = self.thrown_deps[0]
            if catch_body is not None:
                self.thrown_deps[0] = frozenset()
                # The `catch` parameter binds the union of thrown
                # deps (any throw reaching it could produce it —
                # the sound over-approximation). A destructured
                # `catch ({m})`/`catch ([m])` binds every pattern
                # name to that union — the thrown value is
                # scalarized, so each name over-approximates to it.
                # The clause only runs on a thrown path, so its
                # writes are always may-writes; a rethrow inside
                # stays flagged.
                missing = object()
                bound_names = (
                    ()
                    if catch_param is None
                    else (catch_param.text.decode(),)
                    if catch_param.type == "identifier"
                    else tuple(self._pattern_bound_names(catch_param))
                )
                prev = (
                    {n: locals_.get(n, missing) for n in bound_names}
                    if catch_param is not None
                    else {}
                )
                if catch_param is not None:
                    if catch_param.type == "identifier":
                        locals_[catch_param.text.decode()] = catch_deps
                    else:
                        self._destructure(
                            catch_param,
                            catch_deps,
                            params,
                            locals_,
                            transfers,
                            count,
                            False,
                            True,
                            _span(catch_param),
                            True,
                        )
                try:
                    self.statement(
                        catch_body, params, locals_, transfers, count,
                        deps, saw_return, True,
                    )
                finally:
                    for n, p in prev.items():
                        if p is missing:
                            locals_.pop(n, None)
                        else:
                            locals_[n] = p
                propagated = self.thrown[0]
            self.thrown[0] = False
            if fin_body is not None:
                # `finally` always runs — the propagating flag is
                # parked so its statements are not may-writes.
                self.statement(
                    fin_body, params, locals_, transfers, count,
                    deps, saw_return, conditional,
                )
                propagated = propagated or self.thrown[0]
            self.thrown[0] = propagated
            return
        if kind == "labeled_statement":
            label = node.child_by_field_name("label")
            body = node.child_by_field_name("body")
            if label is None or body is None:
                raise _Unsupported("unsupported_statement", _span(node))
            name = label.text.decode()
            if body.type in {
                "while_statement",
                "for_statement",
                "for_in_statement",
                "do_statement",
                "switch_statement",
            }:
                # The loop/switch claims the label on the frame it
                # pushes — a `break L` / `continue L` then finds it.
                self.pending_labels.append(name)
                try:
                    self.statement(
                        body, params, locals_, transfers, count, deps,
                        saw_return, conditional,
                    )
                finally:
                    if name in self.pending_labels:
                        self.pending_labels.remove(name)
                return
            # Any other labeled statement (a block, another label,
            # ...) gets a plain frame — `break L` exits it and a
            # `continue` skips it like it skips a `switch`.
            frame = {
                "exited": False, "broke": False,
                "broke_always": False, "loop": False, "label": name,
            }
            self.frames.append(frame)
            try:
                self.statement(
                    body, params, locals_, transfers, count, deps,
                    saw_return, conditional,
                )
            finally:
                self.frames.pop()
            return
        if kind in {"break_statement", "continue_statement"}:
            label_node = next(
                (
                    c
                    for c in node.named_children
                    if c.type == "statement_identifier"
                ),
                None,
            )
            if len(node.named_children) > (1 if label_node else 0):
                raise _Unsupported("unsupported_statement", _span(node))
            if label_node is not None:
                target = label_node.text.decode()
                frame = next(
                    (
                        f
                        for f in reversed(self.frames)
                        if f.get("label") == target
                        and (
                            kind == "break_statement" or f.get("loop")
                        )
                    ),
                    None,
                )
            elif kind == "continue_statement":
                # A `continue` inside a `switch` or labeled block
                # targets the enclosing loop — skip non-loop frames.
                frame = next(
                    (
                        f for f in reversed(self.frames) if f.get("loop")
                    ),
                    None,
                )
            else:
                frame = self.frames[-1] if self.frames else None
            if frame is None:
                raise _Unsupported("unsupported_statement", _span(node))
            frame["exited"] = True
            # A `break` skips the for-increment on its own exit but
            # leaves the non-breaking exit — the increment's stores
            # then join as may-writes. `continue` never disturbs it.
            if kind == "break_statement":
                frame["broke"] = True
                if not conditional:
                    # Only an unconditional break leaves no exit that
                    # reaches the increment at all.
                    frame["broke_always"] = True
            return
        raise _Unsupported("unsupported_statement", _span(node))

    def _for_part(
        self, node, params, locals_, transfers, count, deps,
        saw_return, conditional,
    ) -> None:
        """A classic-for initializer/increment: a declaration or a
        statement-level expression."""
        if node.type in {"lexical_declaration", "variable_declaration"}:
            self.statement(
                node, params, locals_, transfers, count, deps,
                saw_return, conditional,
            )
            return
        self._expression_statement_inner(
            node, params, locals_, transfers, count, deps,
            saw_return, conditional,
        )

    def _expression_statement(
        self, node, params, locals_, transfers, count, deps,
        saw_return, conditional,
    ) -> None:
        exprs = _children(node)
        if len(exprs) != 1:
            raise _Unsupported("unsupported_statement", _span(node))
        self._expression_statement_inner(
            exprs[0], params, locals_, transfers, count, deps,
            saw_return, conditional,
        )

    def _expression_statement_inner(
        self, node, params, locals_, transfers, count, deps,
        saw_return, conditional,
    ) -> None:
        # `({a} = o)` wraps the assignment in a parenthesized
        # expression at statement position — unwrap for dispatch.
        while node.type == "parenthesized_expression":
            exprs = _children(node)
            if len(exprs) != 1:
                raise _Unsupported("unsupported_statement", _span(node))
            node = exprs[0]
        if node.type == "assignment_expression":
            self._assignment(node, params, locals_, transfers, count,
                             conditional, augmented=False)
            return
        if node.type == "augmented_assignment_expression":
            self._assignment(node, params, locals_, transfers, count,
                             conditional, augmented=True)
            return
        if node.type == "update_expression":
            self._update(node, params, locals_, transfers, count,
                         conditional)
            return
        # Any other statement-level expression evaluates for its calls.
        self.expression(node, params, locals_, transfers, count)

    def _assignment(
        self, node, params, locals_, transfers, count, conditional, augmented
    ) -> None:
        left = node.child_by_field_name("left")
        right = node.child_by_field_name("right")
        op = node.child_by_field_name("operator")
        if (
            left is None
            or right is None
            or (augmented and (op is None or op.type not in _AUGMENTED_OPS))
            or (not augmented and op is not None and op.type != "=")
        ):
            raise _Unsupported("unsupported_statement", _span(node))
        if any(
            c.type == "using" for c in node.children if not c.is_named
        ):
            # `using r = e` / `using {a,b} = e` — a declaration the
            # grammar can't parse (the assignment shape survives
            # with has_error). The disposal protocol is
            # dep-invisible: bind like `const`. `await using`
            # reaches here as the await operand.
            value = self._eval(right, params, locals_, transfers, count)
            if left.type in {"object_pattern", "array_pattern"}:
                self._destructure(
                    left, value, params, locals_, transfers, count,
                    False, conditional, _span(left), True,
                )
                return
            if left.type != "identifier":
                raise _Unsupported("unsupported_statement", _span(left))
            self._bind_target(
                left.text.decode(), value, False, conditional,
                params, locals_, True, _span(left),
            )
            return
        value = self._eval(right, params, locals_, transfers, count)
        if left.type == "identifier":
            name = left.text.decode()
            target = self._write_scope(name, locals_, params)
            if target is None:
                raise _Unsupported("binding_unavailable", _span(left))
            if augmented:
                value = (
                    self._read_name(left, params, locals_, _span(left))
                    | _scalar_of(value)
                )
            else:
                value = self._bindable(right, value)
            self._store(target, params, name, value, conditional)
            return
        if left.type in {"member_expression", "subscript_expression"}:
            if augmented:
                value = (
                    _scalar_of(
                        self._member_read(
                            left, params, locals_, transfers, count
                        )
                    )
                    | _scalar_of(value)
                )
            self._member_store(
                left, value, params, locals_, transfers, count,
                conditional,
            )
            return
        if left.type in {"object_pattern", "array_pattern"}:
            # `({a} = o)` / `[x] = arr` — the slice-11 walk with
            # store semantics: leaves write existing bindings via
            # `_write_scope`, member targets via `_member_store`.
            if augmented:
                raise _Unsupported("unsupported_statement", _span(node))
            self._destructure(
                left,
                value,
                params,
                locals_,
                transfers,
                count,
                False,
                conditional,
                _span(left),
                declare=False,
            )
            return
        raise _Unsupported("unsupported_statement", _span(node))

    def _write_scope(self, name, locals_, params):
        """The scope a store lands in: block first, then the function
        scope a `var` may have escaped into, then a parameter (stored
        in the current scope as a shadow). A module-scope binding
        (`const o = {}` at top level) receives member stores
        directly — its `_Composite` is shared mutable state."""
        if name in locals_:
            return locals_
        if name in self.module_locals:
            return self.module_locals
        if name in params or name in self.var_names:
            # `var` assignments land in the current scope — the joins
            # carry them out to the function scope.
            return locals_
        return None

    def _update(self, node, params, locals_, transfers, count, conditional):
        argument = node.child_by_field_name("argument")
        if argument is None or argument.type not in {
            "identifier",
            "member_expression",
            "subscript_expression",
        }:
            raise _Unsupported("unsupported_statement", _span(node))
        if argument.type == "identifier":
            name = argument.text.decode()
            target = self._write_scope(name, locals_, params)
            if target is None:
                raise _Unsupported("binding_unavailable", _span(argument))
            self._store(
                target, params, name,
                self._read_name(
                    argument, params, locals_, _span(argument)
                ),
                conditional,
            )
            return
        # `o.f++` — dep-preserving member write.
        self._member_store(
            argument,
            _scalar_of(
                self._member_read(
                    argument, params, locals_, transfers, count
                )
            ),
            params,
            locals_,
            transfers,
            count,
            conditional,
        )

    def _loop(
        self, body, increment, condition, params, scope, transfers,
        count, deps, saw_return, conditional, node,
    ) -> None:
        """Iterate a loop body to a dependency fixed point — a join, not
        an unroll; trip counts are never modelled."""
        passes = 0
        frame = {
            "exited": False, "broke": False, "broke_always": False,
            "loop": True,
            "label": (
                self.pending_labels.pop()
                if self.pending_labels
                else None
            ),
        }
        self.frames.append(frame)
        try:
            while True:
                mark = len(transfers)
                frame["exited"] = False
                frame["broke"] = False
                frame["broke_always"] = False
                inner = dict(scope)
                if condition is not None:
                    # The condition re-evaluates each pass so a call's
                    # recorded arguments reflect widened bindings.
                    self.expression(
                        condition, params, inner, transfers, count
                    )
                snap = {}
                for sname, sval in inner.items():
                    if isinstance(sval, _Composite):
                        # Deep-copy nested composites — a may-write
                        # into a nested field mutates the shared
                        # inner object in place, and a shallow
                        # snapshot would see the mutation and end
                        # the fixed point a pass early.
                        snap[sname] = (
                            "fields",
                            _deep_fields(sval.fields),
                            frozenset(sval.deleted),
                        )
                    elif isinstance(sval, _Callable):
                        # `captured` is a dep frozenset, not a
                        # dict — compare it as a set.
                        snap[sname] = ("captured", sval.captured)
                # The body and increment may run zero times, so
                # writes they make into shared composites must union
                # with the pre-loop value rather than replace it.
                self._may_depth += 1
                try:
                    self.statement(
                        body, params, inner, transfers, count, deps,
                        saw_return, conditional,
                    )
                    if increment is not None and not frame["broke_always"]:
                        # The increment runs after each pass so its
                        # writes seed the next iteration — a `break`
                        # skips it only when no exit reaches the
                        # increment at all, and a conditional break
                        # keeps it a may-write.
                        self._for_part(
                            increment, params, inner, transfers, count,
                            deps, saw_return,
                            conditional or frame["broke"],
                        )
                finally:
                    self._may_depth -= 1
                changed = False
                for sname, sentry in snap.items():
                    skind, before = sentry[0], sentry[1]
                    cur = inner.get(sname)
                    if skind == "captured":
                        caps = getattr(cur, "captured", None)
                        if (
                            not isinstance(caps, frozenset)
                            or not caps <= before
                        ):
                            changed = True
                        continue
                    table = getattr(cur, skind, None)
                    if not isinstance(table, dict):
                        changed = True
                        continue
                    # A `delete` grows the composite's `deleted`
                    # set — monotone, so it marks the pass changed
                    # exactly once per field, then converges.
                    if not getattr(cur, "deleted", frozenset()) <= sentry[2]:
                        changed = True
                    # A narrowed field carries no new dep
                    # information — the merged frontier already
                    # holds it — so only widened fields count.
                    for k, v in table.items():
                        # A pass introduces new information when a
                        # mutated field isn't leq its snapshot —
                        # rewrites inside the merged frontier don't
                        # count (they stay below it).
                        if not _val_leq(
                            v, before.get(k, frozenset())
                        ):
                            changed = True
                for name, ndeps in inner.items():
                    if name in scope:
                        if not _val_leq(ndeps, scope[name]):
                            scope[name] = _merge_vals(scope[name], ndeps)
                            changed = True
                    elif name in params:
                        scope[name] = (
                            frozenset({params[name]}) | _scalar_of(ndeps)
                        )
                        changed = True
                    elif name in self.var_names:
                        # `var` is function-scoped: a declaration or
                        # assignment inside the body escapes the loop
                        # like any may-write.
                        scope[name] = _merge_vals(
                            scope.get(name, frozenset()), ndeps
                        )
                        changed = True
                if not changed:
                    break
                # Keep only the last pass's transfers: earlier copies
                # carry narrower argument sets.
                del transfers[mark:]
                passes += 1
                if passes > len(scope) * (len(params) + 1) + 1:
                    raise _Unsupported("analysis_limit", _span(node))
        finally:
            self.frames.pop()

    @staticmethod
    def _join(scope, branch, params, var_names) -> None:
        # Branch-local bindings (names absent from `scope`) never
        # escape — only existing, parameter and `var` names merge.
        for name, value in branch.items():
            if name in scope:
                scope[name] = _merge_vals(scope[name], value)
            elif name in params:
                scope[name] = (
                    frozenset({params[name]}) | _scalar_of(value)
                )
            elif name in var_names:
                # `var` is function-scoped: a declaration inside a
                # branch escapes it like any may-write.
                scope[name] = value

    @staticmethod
    def _bindable(node, value):
        """A composite may only bind via an object literal, a
        whole-name alias (`p = o` shares the instance — writes
        propagate to every holder), `new`, or a call result (a
        fresh shape — e.g. `a.map(...)` — can't alias anything
        else). A member-path result bound to a name would let
        writes through either side diverge, so it collapses to its
        leaf deps. A callable binds via its literal or a name
        alias; anything else (a member path, a call result)
        collapses to the captured deps."""
        if isinstance(value, _Composite) and (
            node.type
            not in {
                "object",
                "array",
                "identifier",
                "new_expression",
                "call_expression",
            }
        ):
            return _scalar_of(value)
        if isinstance(value, _Callable) and (
            node.type
            not in {
                "object",
                "array",
                "identifier",
                "arrow_function",
                "function_expression",
                "generator_function",
                # A call result (`require`, a factory/curry) —
                # the callable carries its own origin/scope, so
                # binding it can't alias anything else.
                "call_expression",
            }
        ):
            return _scalar_of(value)
        if isinstance(value, _Class) and (
            node.type
            not in {"identifier", "class", "class_declaration"}
        ):
            return _scalar_of(value)
        if isinstance(value, _External) and node.type != "identifier":
            return _scalar_of(value)
        return value

    def _lookup(self, name, params, locals_, span):
        """The raw binding for `name` — a scalar dep set or a
        `_Composite`."""
        if name in locals_:
            return locals_[name]
        if name in self.function_locals:
            return self.function_locals[name]
        if name in params:
            return frozenset({params[name]})
        if name in self.module_locals:
            return self.module_locals[name]
        if name in self.classes:
            if name not in self._class_cache:
                self._class_cache[name] = self._class_value(
                    self.classes[name], params, locals_
                )
            return self._class_cache[name]
        if name in self.functions:
            # A function declaration used as a VALUE (`let h =
            # g`, `{f: g}`, `[g]`, `h(g)`) materializes its
            # `_Callable`. The cache unions `captured` across
            # materialization sites so a name visible under
            # several scopes always keeps an over-approximation
            # of every scope it captured.
            if name not in self._fn_cache:
                self._fn_cache[name] = self._callable_value(
                    self.functions[name], params, locals_
                )
            else:
                cval = self._fn_cache[name]
                extra = frozenset(params.values())
                for val in locals_.values():
                    extra |= _scalar_of(val)
                if extra - cval.captured:
                    widened = _Callable(
                        cval.node,
                        cval.params,
                        cval.defaults,
                        cval.captured | extra,
                        cval.rest,
                        cval.is_method,
                    )
                    widened.param_props = cval.param_props
                    widened.origin = cval.origin
                    widened.patterns = cval.patterns
                    widened.bound = cval.bound
                    widened.alts = cval.alts
                    widened.extra = cval.extra
                    self._fn_cache[name] = widened
            return self._fn_cache[name]
        if name in self.imported_bindings:
            return self.imported_bindings[name]
        if name in self.imports:
            return _External()
        if name in _GLOBALS:
            return _External()
        raise _Unsupported("binding_unavailable", span)

    def _read_name(self, node, params, locals_, span) -> frozenset[int]:
        return _scalar_of(
            self._lookup(node.text.decode(), params, locals_, span)
        )

    def _member_target(
        self, node, params, locals_, transfers, count
    ):
        """Walk a `obj.f` / `obj[k]` / parenthesized chain down to its
        base identifier — returns `(base name, field path,
        index deps)`. A `None` path step marks a dynamic key, whose
        index still evaluates for deps and calls."""
        path: list = []
        index_deps = frozenset()
        cur = node
        while cur.type in {
            "member_expression",
            "subscript_expression",
            "parenthesized_expression",
            "non_null_expression",
        }:
            if cur.type in {
                "parenthesized_expression",
                "non_null_expression",
            }:
                inner = next(iter(_children(cur)), None)
                if inner is None:
                    raise _Unsupported(
                        "unsupported_expression", _span(cur)
                    )
                cur = inner
                continue
            if cur.type == "member_expression":
                prop = cur.child_by_field_name("property")
                if prop is None:
                    raise _Unsupported(
                        "unsupported_expression", _span(cur)
                    )
                path.append(prop.text.decode())
            else:
                index = cur.child_by_field_name("index")
                if index is None:
                    raise _Unsupported(
                        "unsupported_expression", _span(cur)
                    )
                # Literal keys carry no deps or calls; a dynamic
                # index evaluates for both.
                if index.type == "string":
                    path.append(index.text.decode().strip("\"'"))
                elif index.type == "number":
                    path.append(index.text.decode())
                else:
                    index_deps |= self.expression(
                        index, params, locals_, transfers, count
                    )
                    path.append(None)
            obj = cur.child_by_field_name("object")
            if obj is None:
                raise _Unsupported(
                    "unsupported_expression", _span(cur)
                )
            cur = obj
        if cur.type in {"this", "super"}:
            path.reverse()
            return cur.type, path, index_deps
        if cur.type != "identifier":
            # A non-name base (`a.slice()[0]`, `f().m`,
            # `new C().f`) — return the node itself; readers
            # evaluate it, writers close (a computed base can't
            # be rebound).
            path.reverse()
            return cur, path, index_deps
        path.reverse()
        return cur.text.decode(), path, index_deps

    def _member_read(self, node, params, locals_, transfers, count):
        """`o.f` / `o.a.b` — descend the base's `_Composite` to the
        field's raw value. A missing field is `undefined` (no deps);
        a dynamic key step over-approximates to every field at that
        level plus the index's deps."""
        base, path, index_deps = self._member_target(
            node, params, locals_, transfers, count
        )
        if base == "super":
            # `super.m` resolves through the parent prototype's
            # method table, but `super.f` on a data field reads
            # the field off `this` — the instance carries the
            # data, the parent only the methods.
            this = self._lookup("this", params, locals_, _span(node))
            klass = this.klass if isinstance(this, _Composite) else None
            parent = klass.parent if klass is not None else None
            if parent is None:
                raise _Unsupported(
                    "unsupported_expression", _span(node)
                )
            key0 = path[0] if path else None
            if isinstance(key0, str) and key0 in parent.getters:
                # `super.p` invokes the PARENT's `get p()` on
                # `this` — the home object's accessor, not a
                # possible child override.
                result = self._invoke_callable(
                    parent.getters[key0],
                    (),
                    params,
                    locals_,
                    transfers,
                    count,
                    _span(node),
                    this_val=this,
                    may=_has_optional_chain(node),
                )
                transfers.append(
                    TsCall(_span(node), key0, (), result)
                )
                val = result
                path = path[1:]
            elif (
                isinstance(key0, str)
                and key0 not in parent.methods
                and key0 not in parent.setters
            ):
                val = this
            else:
                val = parent
        elif not isinstance(base, str):
            # `a.slice()[0]` / `f().m` — evaluate the computed
            # base, then descend the remaining path.
            val = self._eval(base, params, locals_, transfers, count)
        else:
            val = self._lookup(base, params, locals_, _span(node))
        for idx, key in enumerate(path):
            if isinstance(val, _External):
                # Any member of an imported name stays external
                # (`ns.f`, `ns.a.b`) — the callee lives outside.
                return val
            if isinstance(val, _Class):
                # `C.sm` / `C.sf` — statics and methods on the
                # class object itself.
                if key is None:
                    return _scalar_of(val) | index_deps
                if key in val.sgetters and key not in val.statics:
                    # `C.p` invokes `static get p()` like a
                    # no-arg method on the class object.
                    result = self._invoke_callable(
                        val.sgetters[key],
                        (),
                        params,
                        locals_,
                        transfers,
                        count,
                        _span(node),
                        this_val=val,
                        may=_has_optional_chain(node),
                    )
                    transfers.append(
                        TsCall(_span(node), key, (), result)
                    )
                    return result
                if key in val.statics:
                    val = val.statics[key]
                elif key in val.methods:
                    val = val.methods[key]
                else:
                    return frozenset()
                continue
            if not isinstance(val, _Composite):
                # A scalar's member read over-approximates to
                # the scalar's deps (`x.f`, `s.length`).
                return _scalar_of(val) | index_deps
            if key is None:
                # `o[k]` — every field is a candidate, and every
                # getter up the class chain may run: invoke them
                # all and union the results.
                read_union = _scalar_of(val) | index_deps
                klass = val.klass
                seen_getters: set = set()
                while klass is not None:
                    for gkey, gval in klass.getters.items():
                        if (
                            gkey in val.fields
                            or id(gval) in seen_getters
                        ):
                            continue
                        seen_getters.add(id(gval))
                        result = self._invoke_callable(
                            gval,
                            (),
                            params,
                            locals_,
                            transfers,
                            count,
                            _span(node),
                            this_val=val,
                            may=_has_optional_chain(node),
                        )
                        transfers.append(
                            TsCall(
                                _span(node),
                                _callee_name(node),
                                (),
                                result,
                            )
                        )
                        read_union |= result
                    klass = klass.parent
                return read_union
            if key in val.fields and key not in val.deleted:
                val = val.fields[key]
                continue
            fval = val.fields.get(key)
            # Missing or maybe-deleted fields on an instance fall
            # through to the class's accessors/methods (the
            # prototype). A maybe-deleted field keeps BOTH
            # candidates — the join can't tell which ran.
            if val.klass is not None:
                if key in val.klass.getters:
                    # `o.p` invokes `get p()` like a no-arg
                    # method call on the instance.
                    result = self._invoke_callable(
                        val.klass.getters[key],
                        (),
                        params,
                        locals_,
                        transfers,
                        count,
                        _span(node),
                        this_val=val,
                        may=_has_optional_chain(node),
                    )
                    transfers.append(
                        TsCall(_span(node), key, (), result)
                    )
                    if isinstance(fval, _Callable):
                        # Reads see the getter; calls may still
                        # reach the field — carry both.
                        widened = _Callable(
                            fval.node,
                            fval.params,
                            fval.defaults,
                            fval.captured | result,
                            fval.rest,
                            fval.is_method,
                        )
                        widened.param_props = fval.param_props
                        widened.origin = fval.origin
                        widened.patterns = fval.patterns
                        widened.bound = fval.bound
                        widened.alts = fval.alts
                        # The getter's own call deps stay on the
                        # call path too — `o.f(x)` still reaches
                        # the function the getter may return.
                        widened.extra = fval.extra | result
                        val = widened
                        continue
                    return result | (
                        _scalar_of(fval)
                        if fval is not None
                        else frozenset()
                    )
                if key in val.klass.methods:
                    mval = val.klass.methods[key]
                    if isinstance(fval, _Callable):
                        # The own field may still be the callee —
                        # chain the prototype method as an
                        # alternate so `o.m(x)` invokes both.
                        widened = _Callable(
                            fval.node,
                            fval.params,
                            fval.defaults,
                            fval.captured,
                            fval.rest,
                            fval.is_method,
                        )
                        widened.param_props = fval.param_props
                        widened.origin = fval.origin
                        widened.patterns = fval.patterns
                        widened.bound = fval.bound
                        widened.alts = fval.alts + (mval,)
                        widened.extra = fval.extra
                        val = widened
                        continue
                    if fval is None:
                        val = mval
                        continue
                    # A scalar field can't be called — the method
                    # is the callee; the field's deps still join
                    # a plain read via `captured`.
                    widened = _Callable(
                        mval.node,
                        mval.params,
                        mval.defaults,
                        mval.captured | _scalar_of(fval),
                        mval.rest,
                        mval.is_method,
                    )
                    widened.param_props = mval.param_props
                    widened.origin = mval.origin
                    widened.patterns = mval.patterns
                    widened.bound = mval.bound
                    widened.alts = mval.alts
                    widened.extra = mval.extra
                    val = widened
                    continue
            if val.klass is _MAP_SET_KLASS:
                # `m.size` — a Map/Set pseudo-member carries
                # the whole entry union.
                return _scalar_of(val) | index_deps
            if fval is not None:
                # Maybe-deleted with no class member — the read
                # sees the field or `undefined` (dep-free).
                val = fval
                continue
            # An opaque call may have ADDED fields the
            # table never named — `"*"` carries their deps
            # (still dep-free when no opaque call ran).
            return val.fields.get("*", frozenset())
        return val

    def _member_delete(
        self, node, params, locals_, transfers, count
    ) -> None:
        """`delete o.f` — copy-on-write removal of a literal-key
        field, propagated to every alias in scope. A dynamic key
        (`delete o[k]`) may remove ANY field, so every field's deps
        stay (the model can't represent absence — keeping the deps
        is the over-approximation)."""
        base, path, _ = self._member_target(
            node, params, locals_, transfers, count
        )
        if any(key is None for key in path):
            return
        target = self._write_scope(base, locals_, params)
        if target is None:
            raise _Unsupported("binding_unavailable", _span(node))
        old = target.get(base)
        if not isinstance(old, _Composite):
            raise _Unsupported("unsupported_expression", _span(node))
        new = _composite_delete(old, path, _span(node))
        if old in self._aliased_objs:
            # Shared with an unseen scope — mutate in place so
            # the delete reaches it. Under `_may_depth` (or an
            # `?.`-guarded target) the delete may not have run —
            # union so the kept-path fields and deps survive.
            if self._may_depth or _has_optional_chain(node):
                _merge_into(old, new)
            else:
                old.fields.clear()
                old.fields.update(new.fields)
                old.deleted = new.deleted
        for name, val in locals_.items():
            if val is old:
                locals_[name] = new

    def _member_store(
        self, node, value, params, locals_, transfers, count,
        conditional,
    ) -> None:
        """`o.f = v` — copy-on-write the field into the base binding.
        The base must bind a `_Composite` in a writable scope. A
        dynamic subscript key can't pick the field, so every field
        at that level takes the write as a may-write and every
        setter up the class chain is invoked.
        Composite bindings alias (`p = o` shares the instance), so
        the write propagates to every name holding it."""
        base, path, _ = self._member_target(
            node, params, locals_, transfers, count
        )
        has_dynamic = any(key is None for key in path)
        if has_dynamic and base == "super":
            raise _Unsupported("unsupported_expression", _span(node))
        if base == "super":
            # `super.f = v` stores on `this`: an inherited
            # setter runs, otherwise the field lands on the
            # instance (JS [[Set]] always owns the property).
            this = locals_.get("this")
            klass = this.klass if isinstance(this, _Composite) else None
            parent = klass.parent if klass is not None else None
            if (
                len(path) == 1
                and isinstance(path[0], str)
                and parent is not None
                and path[0] in parent.setters
            ):
                actual = _scalar_of(value)
                result = self._invoke_callable(
                    parent.setters[path[0]],
                    (actual,),
                    params,
                    locals_,
                    transfers,
                    count,
                    _span(node),
                    this_val=this,
                )
                transfers.append(
                    TsCall(_span(node), path[0], (actual,), result)
                )
                return
            base = "this"
        target = self._write_scope(base, locals_, params)
        if target is None:
            if base in self.classes:
                # `C.s = v` / `C.p = v` on a class name — the
                # binding is immutable but the `_Class` value is
                # mutable (statics table, static setters).
                old = self._lookup(
                    base, params, locals_, _span(node)
                )
            else:
                raise _Unsupported("binding_unavailable", _span(node))
        else:
            old = target.get(base)
        if isinstance(old, _Class) and has_dynamic:
            # `C[k] = v` — every static field is a may-write and
            # every static setter may run.
            vdeps = _scalar_of(value)
            for sname, sval in list(old.statics.items()):
                old.statics[sname] = _scalar_of(sval) | vdeps
            for sset in old.ssetters.values():
                result = self._invoke_callable(
                    sset,
                    (vdeps,),
                    params,
                    locals_,
                    transfers,
                    count,
                    _span(node),
                    this_val=old,
                )
                transfers.append(
                    TsCall(_span(node), _callee_name(node), (vdeps,), result)
                )
            return
        if isinstance(old, _Class) and len(path) == 1:
            if (
                path[0] in old.ssetters
                and path[0] not in old.statics
            ):
                # `C.p = v` invokes `static set p(v)` — an own
                # static data field shadows the accessor.
                actual = _scalar_of(value)
                result = self._invoke_callable(
                    old.ssetters[path[0]],
                    (actual,),
                    params,
                    locals_,
                    transfers,
                    count,
                    _span(node),
                    this_val=old,
                )
                transfers.append(
                    TsCall(_span(node), path[0], (actual,), result)
                )
                return
            # `C.s = v` — a static write updates the shared class
            # table; `C` aliases see it. A deeper path would need
            # a composite static we don't descend.
            sdeps = _scalar_of(value)
            if conditional:
                # `if (k) C.s = v` — the skipped path keeps the
                # old static binding (a static METHOD flattens to
                # its captured deps).
                sdeps = _scalar_of(
                    old.statics.get(path[0], frozenset())
                ) | sdeps
            old.statics[path[0]] = sdeps
            return
        if isinstance(old, _Callable):
            # `g.extra = v` — an own property on a function
            # object. There are no tracked fields, so the deps
            # widen the callable's captured set: every later
            # `g.anything` read over-approximates to it (member
            # reads on a callable already fall back to
            # `captured`).
            vdeps = _scalar_of(value)
            widened = _Callable(
                old.node,
                old.params,
                old.defaults,
                old.captured | vdeps,
                old.rest,
                old.is_method,
            )
            widened.param_props = old.param_props
            widened.origin = old.origin
            widened.bound = old.bound
            widened.alts = old.alts
            widened.extra = old.extra
            widened.patterns = old.patterns
            for name, val in locals_.items():
                if val is old:
                    locals_[name] = widened
            for name, val in self.module_locals.items():
                if val is old:
                    self.module_locals[name] = widened
            return
        if not isinstance(old, _Composite):
            raise _Unsupported("unsupported_expression", _span(node))
        if has_dynamic:
            # `o[k] = v` — the written field is unknown, so every
            # field at that level is a may-write and every setter
            # up the class chain may run.
            vdeps = _scalar_of(value)
            klass = old.klass
            seen_setters: set = set()
            while klass is not None:
                for skey, sset in klass.setters.items():
                    if skey in old.fields or id(sset) in seen_setters:
                        continue
                    seen_setters.add(id(sset))
                    result = self._invoke_callable(
                        sset,
                        (vdeps,),
                        params,
                        locals_,
                        transfers,
                        count,
                        _span(node),
                        this_val=old,
                    )
                    transfers.append(
                        TsCall(
                            _span(node),
                            _callee_name(node),
                            (vdeps,),
                            result,
                        )
                    )
                klass = klass.parent
            new = _composite_dyn_set(old, path, value, _span(node))
            if self._may_depth:
                # May-write: union into the shared object so every
                # alias keeps the skipped-path value and the write,
                # and identity survives for later propagation.
                _merge_into(old, new)
                return
            if old in self._aliased_objs:
                old.fields.clear()
                old.fields.update(new.fields)
                old.deleted = new.deleted
            for name, val in locals_.items():
                if val is old:
                    locals_[name] = new
            for name, val in self.module_locals.items():
                if val is old:
                    self.module_locals[name] = new
            return
        if (
            len(path) == 1
            and old.klass is not None
            and path[0] in old.klass.setters
            and path[0] not in old.fields
        ):
            # `o.p = v` invokes `set p(v)` — the write's deps
            # become the setter's actual.
            actual = _scalar_of(value)
            result = self._invoke_callable(
                old.klass.setters[path[0]],
                (actual,),
                params,
                locals_,
                transfers,
                count,
                _span(node),
                this_val=old,
            )
            transfers.append(
                TsCall(_span(node), path[0], (actual,), result)
            )
            return
        if isinstance(value, _Composite):
            # `o.f = o2` would alias `o2` at field level — writes
            # would diverge, so a composite field value collapses.
            value = _scalar_of(value)
        new = _composite_set(
            old, path, value, conditional, _span(node)
        )
        if self._may_depth:
            # May-write: union the write into the shared object —
            # every alias (other names here, module scope or an
            # unseen scope) keeps both the skipped-path value and
            # the write, and identity survives so later writes
            # still propagate. Rebinding under may semantics is
            # unsound: per-name `_merge_vals` copies would split
            # one alias into two objects.
            _merge_into(old, new)
            return
        if old in self._aliased_objs:
            # Shared with an UNSEEN scope (the caller's receiver
            # `a` when `this.f = v` ran inside `a.set(...)`, or
            # a composite passed as an argument): mutating its
            # field table propagates the write where rebinding
            # can't reach. The name still rebinds to `new` — a
            # marked object takes an in-place write at most once,
            # so later writes compose on the copy and a loop join
            # keeps its pre-write snapshot.
            old.fields.clear()
            old.fields.update(new.fields)
            old.deleted = new.deleted
        # Every binding IN THIS SCOPE sharing the instance is an
        # alias — the write reaches all of them. Only `locals_` is
        # scanned: eagerly rewriting the enclosing scope would
        # defeat a loop's fixed-point join (the join itself carries
        # the update outward, over-approximating skipped paths).
        for name, val in locals_.items():
            if val is old:
                locals_[name] = new
        # Module scope is the other writable scope — a composite
        # aliased across scopes (`let p = o` where `o` is module
        # scope) needs the copy-on-write result in both, or the
        # store is lost on the module side.
        for name, val in self.module_locals.items():
            if val is old:
                self.module_locals[name] = new

    def expression(self, node, params, locals_, transfers, count):
        """Evaluate a node to scalar dependencies — a composite
        flattens to the union of its leaf deps."""
        return _scalar_of(
            self._eval(node, params, locals_, transfers, count)
        )

    def _callable_value(self, node, params, locals_, is_method=False):
        """`const g = (v) => v + x` — the arrow/function value.
        `captured` is the union of every visible binding's deps at
        the definition site, so the closure's free reads are
        over-approximated even when the callable escapes (returned
        or passed as an argument)."""
        names, defaults, rest, patterns = self._callable_params(node)
        captured = frozenset(params.values())
        for val in locals_.values():
            captured |= _scalar_of(val)
        value = _Callable(
            node, names, defaults, captured, rest, is_method
        )
        value.patterns = patterns
        value.origin = self
        return value

    def _callable_params(self, node):
        """`(a, b = d, ...rest)` / `x =>` — the formal parameter
        names plus any default expressions (evaluated at the call
        site) and the rest index (-1 when absent). A rest
        parameter must come last. An `object_pattern`/
        `array_pattern` parameter gets a synthetic `@i` slot name
        and its node in `patterns` — the invoke destructures the
        bound actual into the pattern's sub-names.
        Annotations are type-level and ignored — `a: Foo` binds
        positionally like `a`."""
        params_node = node.child_by_field_name("parameters")
        if params_node is None:
            p = node.child_by_field_name("parameter")
            if p is None or p.type != "identifier":
                raise _Unsupported(
                    "unsupported_expression", _span(node)
                )
            return (p.text.decode(),), {}, -1, {}
        names: list[str] = []
        defaults: dict[int, object] = {}
        patterns: dict[int, object] = {}
        rest = -1
        for param in _children(params_node):
            if rest >= 0:
                # A parameter after `...rest` is unreachable —
                # closed rather than analyzed wrongly.
                raise _Unsupported(
                    "unsupported_expression", _span(param)
                )
            if param.type not in {
                "required_parameter",
                "optional_parameter",
            }:
                raise _Unsupported(
                    "unsupported_expression", _span(param)
                )
            pattern = param.child_by_field_name("pattern")
            if pattern is not None and pattern.type == "rest_pattern":
                target = next(
                    iter(_children(pattern)), None
                )
                if target is None or target.type != "identifier":
                    raise _Unsupported(
                        "unsupported_expression", _span(param)
                    )
                names.append(target.text.decode())
                rest = len(names) - 1
                continue
            if pattern is None:
                raise _Unsupported(
                    "unsupported_expression", _span(param)
                )
            if pattern.type == "identifier":
                names.append(pattern.text.decode())
                dflt = param.child_by_field_name("value")
                if dflt is not None:
                    defaults[len(names) - 1] = dflt
            elif pattern.type == "assignment_pattern":
                left = pattern.child_by_field_name("left")
                right = pattern.child_by_field_name("right")
                if left is None or left.type not in {
                    "identifier",
                    "object_pattern",
                    "array_pattern",
                }:
                    raise _Unsupported(
                        "unsupported_expression", _span(param)
                    )
                if left.type == "identifier":
                    names.append(left.text.decode())
                else:
                    # `({a} = {a: 1})` — the pattern binds via
                    # `_destructure`; the synthetic slot name is
                    # never user-visible.
                    names.append(f"@{len(names)}")
                    patterns[len(names) - 1] = left
                if right is not None:
                    defaults[len(names) - 1] = right
            elif pattern.type in {"object_pattern", "array_pattern"}:
                # `g = ({a, b}, [x, y]) => ...` — the slot keeps
                # one positional index; `_invoke_callable_body`
                # destructures the bound actual into its
                # sub-names. A `= d` default on the parameter
                # evaluates like an identifier default.
                names.append(f"@{len(names)}")
                patterns[len(names) - 1] = pattern
                dflt = param.child_by_field_name("value")
                if dflt is not None:
                    defaults[len(names) - 1] = dflt
            else:
                raise _Unsupported(
                    "unsupported_expression", _span(param)
                )
        return tuple(names), defaults, rest, patterns

    def _invoke_callable(
        self,
        cval,
        actual,
        params,
        locals_,
        transfers,
        count,
        span,
        this_val=None,
        construct=False,
        actual_values=None,
        alt_this=None,
        may=False,
    ) -> frozenset[int]:
        """`g(args)` where `g` binds an arrow/function value —
        evaluate the body inline. Captured names read the CALL
        site's bindings (closures capture by reference — the
        latest value over-approximates); writes inside the body
        merge back as may-writes so member stores aren't lost;
        the body's own frames/scope state is isolated and
        restored. A callable imported from another module
        invokes under its OWN builder (`cval.origin`) — its free
        names resolve in the imported module's scope, not the
        importer's (an importer-local binding of the same name
        must never capture them). The shared `transfers`/`count`
        accumulators keep call records and the node budget
        global across the chain."""
        if self._invoke_depth >= MAX_INVOKE_DEPTH:
            # Recursive or deeply nested call chains — beyond
            # the bound the result over-approximates to the
            # callee's captured deps plus every actual (the
            # same shape an opaque callee would produce), so
            # a self-recursive function value terminates
            # instead of exhausting the interpreter stack.
            # The opaque shape also may-writes every field of
            # a composite actual — dropping those writes would
            # under-approximate the callee's effects.
            result = _scalar_of(cval)
            for a in actual:
                result |= a
            self._opaque_call_writes(actual_values, result)
            return result
        self._invoke_depth += 1
        widened_may = may or bool(cval.extra)
        if widened_may:
            # `o?.f(x)` / `f?.(x)` — the callee may be absent, so
            # its writes to shared composites are may-writes. A
            # non-empty `extra` means a scalar (un-invocable)
            # candidate was joined into the value — the invoked
            # function may not be any analyzed body, so the
            # analyzed writes are may-writes too.
            self._may_depth += 1
        try:
            saved_frame = dict(locals_) if cval.alts else None
            snap_memo = None
            saved_snap = None
            if saved_frame is not None:
                # Deep-snapshot eagerly: the primary invoke may
                # mutate shared objects in place (`_aliased_objs`),
                # so clones taken after it would read post-call
                # state — each alternate candidate is an exclusive
                # world and must read the PRE-call values.
                snap_memo = {}
                saved_snap = {
                    name: _clone_value(val, snap_memo)
                    for name, val in saved_frame.items()
                }
                if actual_values is not None:
                    for val in actual_values:
                        _clone_value(val, snap_memo)
                if alt_this is not None:
                    _clone_value(alt_this, snap_memo)
            result = self._invoke_callable_body(
                cval,
                actual,
                params,
                locals_,
                transfers,
                count,
                span,
                this_val=this_val,
                construct=construct,
                actual_values=actual_values,
            )
            for alt in cval.alts:
                # A maybe-deleted member slot may resolve to the
                # prototype method — invoke it too. Each candidate
                # is exclusive, so it runs on a clone of the
                # pre-call frame: the primary's writes must not
                # reach the alternate's reads (and vice versa),
                # then both worlds' writes union back in.
                if cval.bound is not None and alt.bound is None:
                    # `bind()` applied to the primary carries the
                    # same partial application onto each
                    # candidate — bound actuals and a bound
                    # `this` must reach the alternate too. An alt
                    # carrying its OWN bound (`f.bind(t, b)` kept
                    # as a distinct candidate) keeps it instead.
                    bound_alt = _Callable(
                        alt.node,
                        alt.params,
                        alt.defaults,
                        alt.captured,
                        alt.rest,
                        alt.is_method,
                    )
                    bound_alt.param_props = alt.param_props
                    bound_alt.origin = alt.origin
                    bound_alt.patterns = alt.patterns
                    bound_alt.bound = cval.bound
                    bound_alt.alts = alt.alts
                    bound_alt.extra = alt.extra
                    alt = bound_alt
                memo = {}
                alt_locals = {
                    name: _clone_value(val, memo)
                    for name, val in saved_snap.items()
                }
                # The snapshot memo holds a snap for the actuals and
                # `this` too — clone them into this world so every
                # snapshot object maps to a clone.
                if actual_values is not None:
                    for val in actual_values:
                        snap = snap_memo.get(id(val))
                        if snap is not None:
                            _clone_value(snap, memo)
                if alt_this is not None:
                    snap = snap_memo.get(id(alt_this))
                    if snap is not None:
                        _clone_value(snap, memo)
                # Re-key by ORIGINAL ids — the `this`/actual lookups
                # and the merge-back reference caller objects, not
                # the snapshot copies.
                for oid, snap in snap_memo.items():
                    if id(snap) in memo:
                        memo[oid] = memo[id(snap)]
                alt_actuals = (
                    [_clone_value(v, memo) for v in actual_values]
                    if actual_values is not None
                    else None
                )
                try:
                    result |= self._invoke_callable(
                        alt,
                        actual,
                        params,
                        alt_locals,
                        transfers,
                        count,
                        span,
                        this_val=(
                            _clone_value(alt_this, memo)
                            if alt.is_method and alt_this is not None
                            else None
                        ),
                        actual_values=alt_actuals,
                    )
                except _Unsupported:
                    # A callee that closes keeps the actuals'
                    # union (the opaque shape) — writes to the
                    # actuals fold in the same way, but stay inside
                    # this candidate's clone world until the
                    # merge-back joins them.
                    opaque = _scalar_of(alt)
                    for a in actual:
                        opaque |= a
                    result |= opaque
                    self._opaque_call_writes(alt_actuals, opaque)
                for name, aval in alt_locals.items():
                    if name not in locals_:
                        continue
                    old = locals_[name]
                    if isinstance(old, _Composite) and isinstance(
                        aval, _Composite
                    ):
                        if aval is memo.get(id(old)):
                            # In-place field writes on the shared
                            # object — merging preserves identity
                            # so every alias (an outer caller
                            # holding the same object through a
                            # wrapper's parameter) sees the writes.
                            _merge_into(old, aval)
                        else:
                            # The name was rebound to a different
                            # object — but in-place writes the
                            # candidate made to the shared clone
                            # before the rebind still belong to
                            # the shared object, so harvest them
                            # into `old` first.
                            clone = memo.get(id(old))
                            if isinstance(clone, _Composite):
                                _merge_into(old, clone)
                            # The old binding and every alias keep
                            # their value; the name may hold either
                            # object afterwards.
                            locals_[name] = _merge_vals(old, aval)
                    elif isinstance(old, _Callable) and isinstance(
                        aval, _Callable
                    ):
                        if aval.node is old.node:
                            # Unchanged clone — keep the original
                            # callable (scalarizing here would
                            # kill a later `name()` analysis).
                            continue
                        # The name may hold either function —
                        # model it as the original plus the
                        # alternate as an extra candidate.
                        merged_c = _Callable(
                            old.node,
                            old.params,
                            old.defaults,
                            old.captured | aval.captured,
                            old.rest,
                            old.is_method,
                        )
                        merged_c.param_props = old.param_props
                        merged_c.origin = old.origin
                        merged_c.patterns = old.patterns
                        merged_c.bound = old.bound
                        merged_c.alts = old.alts + (aval,)
                        merged_c.extra = old.extra | aval.extra
                        locals_[name] = merged_c
                    elif isinstance(old, _Callable) and isinstance(
                        aval, frozenset
                    ):
                        # Function-or-scalar — keep the callable
                        # invocable and union the scalar deps.
                        widened_c = _Callable(
                            old.node,
                            old.params,
                            old.defaults,
                            old.captured | aval,
                            old.rest,
                            old.is_method,
                        )
                        widened_c.param_props = old.param_props
                        widened_c.origin = old.origin
                        widened_c.patterns = old.patterns
                        widened_c.bound = old.bound
                        widened_c.alts = old.alts
                        widened_c.extra = old.extra | aval
                        locals_[name] = widened_c
                    else:
                        locals_[name] = _merge_vals(old, aval)
            if cval.extra:
                # The scalar candidate's call is opaque — it may
                # write arbitrary fields of composite actuals and
                # of the `this` object, so fold the union of its
                # deps plus every actual in as a may-write.
                opaque = frozenset(cval.extra)
                for a in actual:
                    opaque |= a
                wvals = (
                    list(actual_values) if actual_values else []
                )
                if isinstance(this_val, _Composite):
                    wvals.append(this_val)
                if (
                    cval.bound is not None
                    and isinstance(cval.bound[2], _Composite)
                ):
                    wvals.append(cval.bound[2])
                self._opaque_call_writes(wvals, opaque)
                if isinstance(result, frozenset):
                    result = result | cval.extra
                elif isinstance(result, _Composite):
                    # A composite return keeps its shape — the
                    # slot's fallback deps fold into the
                    # unknown-field bucket instead.
                    widened = _Composite(
                        dict(result.fields),
                        result.klass,
                        result.deleted,
                    )
                    widened.fields["*"] = _merge_vals(
                        widened.fields.get("*", frozenset()),
                        cval.extra,
                    )
                    result = widened
            return result
        finally:
            if widened_may:
                self._may_depth -= 1
            self._invoke_depth -= 1

    def _invoke_callable_body(
        self,
        cval,
        actual,
        params,
        locals_,
        transfers,
        count,
        span,
        this_val=None,
        construct=False,
        actual_values=None,
    ) -> frozenset[int]:
        if cval.origin is not None and cval.origin is not self:
            return cval.origin._invoke_callable(
                cval,
                actual,
                {},
                {},
                transfers,
                count,
                span,
                this_val=this_val,
                construct=construct,
                actual_values=actual_values,
                may=self._may_depth > 0,
            )
        if cval.bound is not None:
            # `bind(t, a...)` — prepend the recorded partial
            # application to this invocation's actuals; a bound
            # `this` applies when the call supplies none.
            bdeps, bvals, bthis = cval.bound
            actual = list(bdeps) + list(actual)
            if actual_values is not None:
                actual_values = list(bvals) + list(actual_values)
            else:
                actual_values = list(bvals) + [None] * (
                    len(actual) - len(bvals)
                )
            if bthis is not None:
                # A bound `this` wins over the call site's
                # receiver — `g.bind(o).call(p)` still sees `o`.
                this_val = bthis
        # `this`/composite-actual marks last only for THIS call —
        # in-place mutation propagates the callee's writes, but a
        # mark that outlived the call would let a later caller-side
        # conditional write corrupt the pre-branch snapshot.
        saved_aliased = self._aliased_objs
        self._aliased_objs = set(saved_aliased)
        inner = dict(locals_)
        for frame_val in inner.values():
            if isinstance(frame_val, _Composite):
                # A captured composite is shared with the caller
                # the same way a composite actual or `this` is:
                # a member write through the callee's name must
                # mutate the shared object so every alias sees
                # it — copy-on-write would strand the write on a
                # rebind before the callee-join can carry it back.
                self._aliased_objs.add(frame_val)
        destructured_params: list = []
        if this_val is not None:
            inner["this"] = this_val
            if isinstance(this_val, _Composite):
                # `this` IS the caller's object — field writes
                # must reach it (see `_member_store`).
                self._aliased_objs.add(this_val)
        for i, pname in enumerate(cval.params):
            aval = (
                actual_values[i]
                if actual_values is not None and i < len(actual_values)
                else None
            )
            if isinstance(aval, _Composite):
                self._aliased_objs.add(aval)
            if i == cval.rest:
                # `...rest` collects every remaining argument —
                # dep-wise the union of them all.
                deps = frozenset()
                for extra in actual[i:]:
                    deps |= extra
            else:
                deps = actual[i] if i < len(actual) else frozenset()
            dnode = cval.defaults.get(i)
            if dnode is not None:
                deps |= self.expression(
                    dnode, params, inner, transfers, count
                )
            pnode = cval.patterns.get(i)
            if pnode is not None:
                # `g = ({a}, [b]) => ...` — the sub-names bind via
                # `_destructure` once `inner` becomes the live
                # frame; a scalar actual over-approximates each
                # sub-name to the whole union.
                psrc = aval if aval is not None else deps
                if (
                    dnode is not None
                    and isinstance(psrc, _Composite)
                ):
                    # `({a} = {a: x})` on a composite actual — a
                    # property the actual lacks falls back to the
                    # default's deps. Seed a copy's `"*"` bucket so
                    # `_pattern_read` carries them without
                    # mutating the caller's object.
                    seeded = _Composite(
                        dict(psrc.fields), psrc.klass, psrc.deleted
                    )
                    seeded.fields["*"] = _merge_vals(
                        seeded.fields.get("*", frozenset()), deps
                    )
                    psrc = seeded
                destructured_params.append((pnode, psrc))
                continue
            if aval is not None and not isinstance(aval, frozenset):
                # A value-typed actual (a `_Callable`/`_Composite`
                # passed as an argument) binds its identity — a
                # body calling `param(x)` invokes the real
                # callback; scalar actuals keep dep binding.
                inner[pname] = aval
            else:
                inner[pname] = deps
            if (
                construct
                and pname in cval.param_props
                and isinstance(this_val, _Composite)
            ):
                # `constructor(private a)` — the field takes the
                # bound actual before the body runs (a body write
                # to `this.a` merges over it normally).
                this_val.fields[pname] = deps
        if actual:
            # `arguments` inside an invoked function value — every
            # element over-approximates to the actuals' union.
            actual_union = frozenset().union(*actual)
            inner["arguments"] = _Composite(
                {str(i): actual_union for i in range(len(actual))}
            )
        body_node = cval.node.child_by_field_name("body")
        if body_node is None:
            raise _Unsupported("unsupported_expression", span)
        saved_frames, self.frames = self.frames, []
        saved_thrown, self.thrown = self.thrown, [False]
        saved_tdeps, self.thrown_deps = (
            self.thrown_deps, [frozenset()]
        )
        saved_block, self.block_stack = self.block_stack, []
        saved_var, self.var_names = self.var_names, set()
        saved_flocals, self.function_locals = self.function_locals, inner
        saved_yields, self.yield_deps = self.yield_deps, []
        # `var` declarations hoist to this invocation's frame.
        for vname in self._hoist_var_names(body_node):
            self.var_names.add(vname)
            inner.setdefault(vname, frozenset())
        for pnode, psource in destructured_params:
            self._destructure(
                pnode,
                psource,
                params,
                inner,
                transfers,
                count,
                False,
                False,
                span,
            )
        try:
            if body_node.type == "statement_block":
                # Nested `function inner() {}` declarations hoist
                # into the callable's own frame.
                for inner_decl in body_node.children:
                    self._register_nested_functions(
                        inner_decl, params, inner
                    )
                adeps = [frozenset()]
                saw = [False]
                self._sequence(
                    _children(body_node),
                    params,
                    inner,
                    transfers,
                    count,
                    adeps,
                    saw,
                    False,
                )
                result = adeps[0] if saw[0] else frozenset()
            else:
                result = _scalar_of(
                    self._eval(
                        body_node, params, inner, transfers, count
                    )
                )
        finally:
            self.frames = saved_frames
            self.thrown = saved_thrown
            self.thrown_deps = saved_tdeps
            self.block_stack = saved_block
            self.var_names = saved_var
            self.function_locals = saved_flocals
            self._aliased_objs = saved_aliased
        if construct:
            # `new f()` — the value is the evolved `this`, not
            # the body's return.
            result = inner.get("this", result)
        # A callable's own `yield`s stay inside its iterator —
        # union them into the call's result, then restore the
        # outer list so they never leak to the caller's summary.
        for ydeps in self.yield_deps:
            result = _scalar_of(result) | ydeps
        self.yield_deps = saved_yields
        # Writes inside the body are may-writes on the caller's
        # scope — member stores rebase shared `_Composite`
        # instances on `inner`, so join them back.
        shadowed = set(cval.params)
        for name, ival in inner.items():
            if name in shadowed or name not in locals_:
                continue
            if not _val_leq(ival, locals_[name]):
                locals_[name] = _merge_vals(locals_[name], ival)
        return result

    def _class_value(self, node, params, locals_):
        """`class C { f = e; m(v){...} }` — a `_Class` whose methods
        are `_Callable`s (`is_method`) sharing the class body's
        capture. Private `#` members behave like named ones keyed
        by their `#` text; `static { ... }` blocks evaluate once
        at class build with `C` bound to the class itself, their
        deps joining `captured` (static writes update the shared
        `statics` table). Instance `get`/`set` accessors collect
        into `getters`/`setters` — invoked on member read/store
        like a no-arg/one-arg method. `extends`/`implements`,
        computed names and `abstract`/ambient members all close —
        `static get/set` accessors collect into
        `sgetters`/`ssetters` like their instance siblings.
        Decorators evaluate after `captured`
        is known: `@dec` is the call `dec(C)` and `@dec(y)` a
        factory call — either way the class's `captured` (every
        local's union) already covers the resulting deps."""
        parent = None
        heritage_deps = frozenset()
        decorators: list = []
        for child in node.children:
            if child.type == "class_heritage":
                for clause in _children(child):
                    if clause.type == "implements_clause":
                        # Type-level only — `implements` never
                        # produces a runtime value.
                        continue
                    if clause.type != "extends_clause":
                        raise _Unsupported(
                            "unsupported_expression", _span(clause)
                        )
                    expr = next(iter(_children(clause)), None)
                    if expr is None:
                        raise _Unsupported(
                            "unsupported_expression", _span(clause)
                        )
                    pval = self._eval(
                        expr, params, locals_, [], [0]
                    )
                    if isinstance(pval, _Class):
                        parent = pval
                    else:
                        # `extends Object`/an opaque expression —
                        # the inherited shape is unknown, so the
                        # parent chain ends but the expression's
                        # deps still flow into the class value.
                        heritage_deps |= _scalar_of(pval)
                continue
            if not child.is_named and child.type == "declare":
                # `declare class` — ambient, no runtime binding.
                raise _Unsupported("unsupported_expression", _span(child))
            if child.type == "decorator":
                decorators.extend(_children(child))
                continue
        body_node = node.child_by_field_name("body")
        if body_node is None:
            raise _Unsupported("unsupported_expression", _span(node))
        captured = frozenset(params.values())
        captured |= heritage_deps
        for val in locals_.values():
            captured |= _scalar_of(val)
        ctor = None
        methods: dict = {}
        statics: dict = {}
        field_inits: dict = {}
        dyn_field_deps = frozenset()
        getters: dict = {}
        setters: dict = {}
        sgetters: dict = {}
        ssetters: dict = {}
        static_blocks: list = []
        for member in _children(body_node):
            if member.type == "method_definition":
                markers = {
                    c.type for c in member.children if not c.is_named
                }
                if markers & {"abstract", "declare"}:
                    # `abstract m(): T` / `declare m()` — a
                    # bodyless signature; skipping is safe since
                    # the member simply never registers.
                    continue
                mname = member.child_by_field_name("name")
                if mname is not None and (
                    mname.type == "computed_property_name"
                ):
                    # `[k]() {}` — the member can't be keyed, so it
                    # registers under a synthetic name a static
                    # lookup can never produce: a dynamic `o[k]()`
                    # still finds it among the invoke candidates.
                    # The name expression evaluates in class scope.
                    for inner in _children(mname):
                        self.expression(inner, params, locals_, [], [0])
                    try:
                        cnames, cdefaults, crest, cpat = (
                            self._callable_params(member)
                        )
                        _mc = _Callable(
                            member,
                            cnames,
                            cdefaults,
                            captured,
                            crest,
                            is_method=True,
                        )
                        _mc.patterns = cpat
                        _mc.origin = self
                        key_node = next(iter(_children(mname)), None)
                        lit = (
                            _computed_key(key_node)
                            if key_node is not None
                            else None
                        )
                        if lit is not None:
                            # `['m']() {}` — a literal computed
                            # name keys like a named member.
                            if "static" in markers:
                                statics[lit] = _mc
                            else:
                                methods[lit] = _mc
                        else:
                            methods[f"[computed:{member.start_byte}]"] = (
                                _mc
                            )
                    except _Unsupported:
                        pass
                    continue
                if mname is None or mname.type not in {
                    "property_identifier",
                    "private_property_identifier",
                }:
                    raise _Unsupported(
                        "unsupported_expression", _span(member)
                    )
                key = mname.text.decode()
                names, defaults, rest, mpat = (
                    self._callable_params(member)
                )
                mval = _Callable(
                    member,
                    names,
                    defaults,
                    captured,
                    rest,
                    is_method=True,
                )
                mval.patterns = mpat
                mval.origin = self
                if key == "constructor":
                    # `constructor(private a, readonly b)` —
                    # accessibility/readonly markers turn a
                    # parameter into a field initializer.
                    props = set()
                    ctor_params = member.child_by_field_name(
                        "parameters"
                    )
                    for prm in _children(ctor_params):
                        if prm.type not in {
                            "required_parameter",
                            "optional_parameter",
                        }:
                            continue
                        if any(
                            c.type in {"accessibility_modifier", "readonly"}
                            for c in prm.children
                        ):
                            pat = prm.child_by_field_name("pattern")
                            if pat is not None and (
                                pat.type == "identifier"
                            ):
                                props.add(pat.text.decode())
                    mval.param_props = frozenset(props)
                if markers & {"get", "set"}:
                    if "static" in markers:
                        # `static get/set p` — the class-object
                        # analog of an instance accessor.
                        if "get" in markers:
                            sgetters[key] = mval
                        else:
                            ssetters[key] = mval
                    elif "get" in markers:
                        getters[key] = mval
                    else:
                        setters[key] = mval
                elif key == "constructor":
                    ctor = mval
                elif "static" in markers:
                    statics[key] = mval
                else:
                    methods[key] = mval
                continue
            if member.type in {
                "public_field_definition",
                "field_definition",
                "property_definition",
            }:
                markers = {
                    c.type for c in member.children if not c.is_named
                }
                if markers & {"abstract", "declare"}:
                    # `declare f: T` / `abstract f: T` —
                    # signature-only field, never initialized.
                    continue
                fname = member.child_by_field_name("name")
                if fname is None:
                    raise _Unsupported(
                        "unsupported_expression", _span(member)
                    )
                if fname.type == "computed_property_name":
                    # `[k] = e` — the name expression evaluates
                    # in class scope for transfers; a literal
                    # name keys the field precisely, anything
                    # else folds its deps into the `"*"`
                    # may-write bucket (instance) or `captured`
                    # (static).
                    key_node = next(iter(_children(fname)), None)
                    if key_node is None:
                        raise _Unsupported(
                            "unsupported_expression", _span(member)
                        )
                    key_deps = self.expression(
                        key_node, params, locals_, [], [0]
                    )
                    init = member.child_by_field_name("value")
                    lit = _computed_key(key_node)
                    if "static" in markers:
                        deps = (
                            _scalar_of(
                                self._eval(
                                    init, params, locals_, [], [0]
                                )
                            )
                            if init is not None
                            else frozenset()
                        )
                        if lit is not None:
                            statics[lit] = deps
                        else:
                            captured |= key_deps | deps
                    elif lit is not None:
                        field_inits[lit] = init
                    elif init is not None:
                        dyn_field_deps |= key_deps | _scalar_of(
                            self._eval(
                                init, params, locals_, [], [0]
                            )
                        )
                    else:
                        dyn_field_deps |= key_deps
                    continue
                if fname.type not in {
                    "property_identifier",
                    "private_property_identifier",
                }:
                    raise _Unsupported(
                        "unsupported_expression", _span(member)
                    )
                init = member.child_by_field_name("value")
                if "static" in markers:
                    # `static s = e` evaluates eagerly — the class
                    # value itself carries the deps.
                    deps = (
                        self._eval(init, params, locals_, [], [0])
                        if init is not None
                        else frozenset()
                    )
                    statics[fname.text.decode()] = _scalar_of(deps)
                elif init is not None:
                    field_inits[fname.text.decode()] = init
                else:
                    field_inits[fname.text.decode()] = None
                continue
            if member.type == "class_static_block":
                # Evaluated after the tables are built — a block
                # may reference `C` itself.
                static_blocks.append(member)
                continue
            if member.type == "decorator":
                # Precedes the member it annotates; evaluated
                # like a class decorator once `captured` exists.
                decorators.extend(_children(member))
                continue
            if member.type in {
                "abstract_method_signature",
                "method_signature",
                "abstract_public_field_definition",
                "index_signature",
            }:
                # Bodyless signatures — abstract members and
                # index signatures declare shape only; skipping
                # them is safe because a call through a member
                # that never registered simply misses the table.
                continue
            raise _Unsupported("unsupported_expression", _span(member))
        for dec_expr in decorators:
            self._eval_decorator(
                dec_expr, params, locals_, captured
            )
        for member in static_blocks:
            # `static { ... }` runs once at class evaluation —
            # the deps it computes join the class's captured
            # set; its writes stay inside a scope copy (the
            # model doesn't track static writes). `C` resolves
            # to the class being built.
            inner_node = next(iter(_children(member)), None)
            if inner_node is None:
                raise _Unsupported(
                    "unsupported_expression", _span(member)
                )
            block_locals = dict(locals_)
            cname = node.child_by_field_name("name")
            if cname is not None:
                block_locals[cname.text.decode()] = _Class(
                    ctor, methods, statics, field_inits, captured,
                    parent, getters, setters,
                    dyn_field_deps=dyn_field_deps,
                    opaque_extends=heritage_deps,
                )
            block_deps = [frozenset()]
            block_saw = [False]
            saved_frames, self.frames = self.frames, []
            saved_thrown, self.thrown = self.thrown, [False]
            saved_tdeps, self.thrown_deps = (
                self.thrown_deps, [frozenset()]
            )
            saved_block, self.block_stack = self.block_stack, []
            saved_var, self.var_names = self.var_names, set()
            saved_flocals, self.function_locals = (
                self.function_locals,
                block_locals,
            )
            try:
                self._sequence(
                    _children(inner_node),
                    params,
                    block_locals,
                    [],
                    [0],
                    block_deps,
                    block_saw,
                    False,
                )
            finally:
                self.frames = saved_frames
                self.thrown = saved_thrown
                self.thrown_deps = saved_tdeps
                self.block_stack = saved_block
                self.var_names = saved_var
                self.function_locals = saved_flocals
            captured |= block_deps[0]
            for v in block_locals.values():
                captured |= _scalar_of(v)
        all_deps = captured
        for s in statics.values():
            all_deps |= _scalar_of(s)
        if parent is not None:
            # Inherit the tables the class didn't redeclare: own
            # members shadow same-named parent members.
            imethods = dict(parent.methods)
            imethods.update(methods)
            methods = imethods
            istatics = dict(parent.statics)
            istatics.update(statics)
            statics = istatics
            isgetters = dict(parent.sgetters)
            isgetters.update(sgetters)
            sgetters = isgetters
            issetters = dict(parent.ssetters)
            issetters.update(ssetters)
            ssetters = issetters
            ifields = dict(parent.field_inits)
            ifields.update(field_inits)
            field_inits = ifields
            igetters = dict(parent.getters)
            igetters.update(getters)
            getters = igetters
            isetters = dict(parent.setters)
            isetters.update(setters)
            setters = isetters
            # Dynamic/computed fields and an opaque heritage
            # chain propagate to derived instances — a read of
            # a never-named field on `new D()` must still carry
            # the parent's seed deps.
            dyn_field_deps |= (
                parent.dyn_field_deps | parent.opaque_extends
            )
            if ctor is None:
                # A derived class without a ctor defaults to one
                # that runs the parent's.
                ctor = parent.ctor
            all_deps |= parent.captured
        return _Class(
            ctor, methods, statics, field_inits, all_deps, parent,
            getters, setters, sgetters, ssetters,
            dyn_field_deps, heritage_deps,
        )

    def _eval_decorator(self, node, params, locals_, captured):
        """Evaluate one decorator expression (`@dec`, `@dec(y)`,
        `@ns.dec(y)`) at class-definition time. The decorated
        class's `captured` already unions every local, so the
        decorator's result deps need no pin — the evaluation is
        for its calls/writes only (records dropped, same as
        `extends`). A bare `@dec` applies `dec(C)`; a bound
        `_Callable` decorates by invocation, an `_External` or a
        same-unit function is a recorded-but-dropped call, and a
        factory `@dec(y)` evaluates its call expression. A name
        resolving to nothing closes — the decorator cannot be
        modeled."""
        if node.type == "identifier":
            name = node.text.decode()
            bound = (
                name in locals_
                or name in self.function_locals
                or name in params
                or name in self.imports
                or name in self.imported_bindings
                or name in _GLOBALS
            )
            if bound:
                raw = self._lookup(
                    name, params, locals_, _span(node)
                )
                if isinstance(raw, _Callable):
                    # `dec(C)` — the class's captured deps are the
                    # argument.
                    self._invoke_callable(
                        raw,
                        (captured,),
                        params,
                        locals_,
                        [],
                        [0],
                        _span(node),
                    )
                return
            if name in self.functions:
                return
            raise _Unsupported(
                "binding_unavailable", _span(node), name
            )
        # A call/member/subscript expression (`@dec(y)`,
        # `@ns.dec`) evaluates like any other expression —
        # call_expression invokes the factory where resolvable.
        self.expression(node, params, locals_, [], [0])

    def _jsx(self, node, params, locals_, transfers, count):
        """A JSX element/fragment — `<Comp a={x}>{y}</Comp>`
        means `Comp({a: x, children: y})`: an uppercase or
        member tag resolving to a `_Callable` is invoked with a
        props composite (children deps land on the `children`
        field); a lowercase identifier is a host element with no
        value of its own; anything else contributes its scalar
        deps. The element's value is the call result plus the
        child-expression deps (the element still holds them)."""
        children_deps = frozenset()
        opening = None
        for child in _children(node):
            if child.type == "jsx_opening_element":
                opening = child
            elif child.type == "jsx_closing_element":
                continue
            elif node.type == "jsx_self_closing_element":
                # The self-closing node is its own opening tag.
                opening = node
                break
            else:
                children_deps |= _scalar_of(
                    self._eval(child, params, locals_, transfers, count)
                )
        if opening is None:
            # `<></>` fragment — children only.
            return children_deps
        tag = None
        props: dict = {}
        extras = children_deps
        for child in _children(opening):
            if tag is None:
                tag = child
                continue
            if child.type == "jsx_attribute":
                name = None
                for inner in _children(child):
                    if inner.type == "property_identifier":
                        name = inner.text.decode()
                    else:
                        deps = _scalar_of(
                            self._eval(
                                inner, params, locals_, transfers, count
                            )
                        )
                        if name is not None:
                            props[name] = deps
                        else:
                            extras |= deps
            else:
                # `{...spread}` and any other attribute-ish child.
                extras |= _scalar_of(
                    self._eval(child, params, locals_, transfers, count)
                )
        if children_deps:
            props["children"] = children_deps
        if tag is None or (
            tag.type == "identifier"
            and tag.text.decode()[:1].islower()
        ):
            # Host element (`<div>`, `<br/>`) — no callable.
            return extras
        # Actuals are scalar dep sets — the props composite
        # flattens into one argument, so `p.a` inside the
        # component reads the union of all attribute deps.
        actual = (_scalar_of(_Composite(props)),)
        if tag.type == "identifier" and tag.text.decode() in (
            self.functions
        ) and not (
            tag.text.decode() in locals_
            or tag.text.decode() in self.function_locals
            or tag.text.decode() in params
        ):
            # `<Comp .../>` where Comp is a same-unit function
            # declaration — recorded like `Comp(props)`, not
            # invoked (the function is analyzed on its own).
            result = extras | actual[0]
            transfers.append(
                TsCall(
                    _span(node),
                    tag.text.decode(),
                    actual,
                    result,
                )
            )
            return result
        raw = self._eval(tag, params, locals_, transfers, count)
        if isinstance(raw, _Callable):
            result = self._invoke_callable(
                raw,
                actual,
                params,
                locals_,
                transfers,
                count,
                _span(node),
            )
            transfers.append(
                TsCall(
                    _span(node),
                    tag.text.decode(),
                    actual,
                    result,
                )
            )
            return result | extras
        return _scalar_of(raw) | extras

    def _construct(
        self,
        cls,
        actual,
        params,
        locals_,
        transfers,
        count,
        span,
        actual_values=None,
    ):
        """`new C(args)` — seed `this` to a fresh `_Composite` of
        the class, run field initializers (which see `this` and
        the captured scope, not ctor params), then the ctor body;
        the value is the evolved instance."""
        inner = dict(locals_)
        inner["this"] = _Composite({}, klass=cls)
        saved_frames, self.frames = self.frames, []
        saved_thrown, self.thrown = self.thrown, [False]
        saved_tdeps, self.thrown_deps = (
            self.thrown_deps, [frozenset()]
        )
        saved_block, self.block_stack = self.block_stack, []
        saved_var, self.var_names = self.var_names, set()
        saved_flocals, self.function_locals = self.function_locals, inner
        try:
            for fname, init in cls.field_inits.items():
                deps = (
                    _scalar_of(
                        self._eval(
                            init, params, inner, transfers, count
                        )
                    )
                    if init is not None
                    else frozenset()
                )
                inner["this"] = _composite_set(
                    inner["this"], [fname], deps, False, span
                )
            dyn_seed = cls.dyn_field_deps | cls.opaque_extends
            if cls.opaque_extends:
                # An opaque parent ctor may write any `this`
                # field from the subclass's actuals (`super(x)`).
                for a in actual:
                    dyn_seed |= a
            if dyn_seed:
                inner["this"] = _composite_set(
                    inner["this"], ["*"], dyn_seed, False, span
                )
            if cls.ctor is not None:
                instance = self._invoke_callable(
                    cls.ctor,
                    actual,
                    params,
                    inner,
                    transfers,
                    count,
                    span,
                    this_val=inner["this"],
                    construct=True,
                    actual_values=actual_values,
                )
                inner["this"] = instance
        finally:
            self.frames = saved_frames
            self.thrown = saved_thrown
            self.thrown_deps = saved_tdeps
            self.block_stack = saved_block
            self.var_names = saved_var
            self.function_locals = saved_flocals
        # Member stores inside the ctor are may-writes on the
        # caller's scope — merge back non-shadowed names.
        shadowed = set(cls.ctor.params) if cls.ctor is not None else set()
        shadowed.add("this")
        for name, ival in inner.items():
            if name in shadowed or name not in locals_:
                continue
            if not _val_leq(ival, locals_[name]):
                locals_[name] = _merge_vals(locals_[name], ival)
        return inner["this"]

    def _call_actuals(
        self,
        arguments,
        params,
        locals_,
        transfers,
        count,
        node,
        values_out=None,
    ):
        """`f(a, b)` actuals, or `tag`...${x}...`` — a tagged
        template calls the tag with the cooked-strings array
        (dep-free) then each substitution's value. When
        `values_out` is a list it also collects each argument's
        evaluated VALUE (a `_Callable` argument keeps its
        identity — `_invoke_callable` binds it to the param so
        `h(cb){ cb(x) }` invokes the real callback)."""
        def add(arg_node):
            value = self._eval(
                arg_node, params, locals_, transfers, count
            )
            if values_out is not None:
                values_out.append(value)
            return _scalar_of(value)

        if arguments.type == "template_string":
            actuals: list = [frozenset()]
            if values_out is not None:
                values_out.append(frozenset())
            for child in _children(arguments):
                if child.type == "template_substitution":
                    for inner in _children(child):
                        actuals.append(add(inner))
            return tuple(actuals)
        if arguments.type != "arguments":
            raise _Unsupported("unsupported_expression", _span(node))
        actuals = []
        for arg in _children(arguments):
            if arg.type == "spread_element":
                # `f(...a)` — a composite operand contributes one
                # actual per element (index order); an opaque or
                # empty one contributes its dep union once.
                operand = next(iter(_children(arg)), None)
                if operand is None:
                    raise _Unsupported(
                        "unsupported_expression", _span(arg)
                    )
                sval = self._eval(
                    operand, params, locals_, transfers, count
                )
                if isinstance(sval, _Composite):
                    spread_items = [
                        (int(k), v)
                        for k, v in sval.fields.items()
                        if k.isdigit()
                    ]
                    spread_items.sort()
                    star = sval.fields.get("*")
                    if not spread_items and star is None:
                        if values_out is not None:
                            values_out.append(sval)
                        actuals.append(_scalar_of(sval))
                    else:
                        for _, fval in spread_items:
                            if values_out is not None:
                                values_out.append(fval)
                            actuals.append(_scalar_of(fval))
                        if star is not None:
                            if values_out is not None:
                                values_out.append(star)
                            actuals.append(_scalar_of(star))
                else:
                    if values_out is not None:
                        values_out.append(sval)
                    actuals.append(_scalar_of(sval))
                continue
            actuals.append(add(arg))
        return tuple(actuals)

    def _array_base(
        self, obj_node, params, locals_, transfers, count, span
    ):
        """The composite an array method mutates: the top binding,
        the member path, and the array sub-composite itself."""
        tbase, tpath, _ = self._member_target(
            obj_node, params, locals_, transfers, count
        )
        if tpath and any(k is None for k in tpath):
            raise _Unsupported("unsupported_expression", span)
        target = self._write_scope(tbase, locals_, params)
        if target is None:
            raise _Unsupported("binding_unavailable", span)
        old = target.get(tbase)
        arr = old
        for step in tpath:
            arr = (
                arr.fields.get(step)
                if isinstance(arr, _Composite)
                else None
            )
        if not isinstance(old, _Composite) or not isinstance(
            arr, _Composite
        ):
            raise _Unsupported("unsupported_expression", span)
        return old, tpath, arr

    def _rebind_composite(self, locals_, old, tpath, new_arr, span):
        """Rebind every same-scope alias of `old` to a copy whose
        `tpath` field table is `new_arr`'s (copy-on-write like
        `_member_store`)."""
        new = (
            _composite_set(old, tpath, new_arr, True, span)
            if tpath
            else new_arr
        )
        if self._may_depth:
            # May-write (short-circuit RHS, optional chain): union
            # into the shared object — rebinding would drop the
            # skipped path's fields and split one alias into two
            # objects (same rule as `_member_store`).
            _merge_into(old, new)
            return new
        for name, val in locals_.items():
            if val is old:
                locals_[name] = new
        return new

    @staticmethod
    def _opaque_call_writes(values, deps):
        """`e(o, x)` through an opaque callee — a declared
        function's dep-union call, an `_External`, a dynamic
        `import()`. The callee may write ANY field of a
        composite actual (its body isn't modelled here), so
        every field takes the call's dep union as a may-write;
        a composite/callable field collapses, which is the
        sound over-approximation. The callee may also ADD
        fields the table doesn't have — `"*"` records the
        deps of every never-named write so a later read of
        a missing key still carries them."""
        if not deps or not values:
            return
        for val in values:
            if not isinstance(val, _Composite):
                continue
            for key in list(val.fields):
                val.fields[key] = _merge_vals(
                    val.fields[key], deps
                )
            val.fields["*"] = _merge_vals(
                val.fields.get("*", frozenset()), deps
            )

    def _funproto_call(
        self,
        prop,
        base,
        vals,
        deps,
        params,
        locals_,
        transfers,
        count,
        node,
        callee_text,
        may=False,
    ):
        """`Function.prototype.call/apply/bind` where the receiver
        is a known `_Callable` value (`g.call(t, a)`,
        `g.apply(t, [a])`, `g.bind(t, a)`). `call`/`apply` invoke
        the callee with `this` bound to the first actual —
        `apply`'s array actual supplies its elements when the
        value is a `_Composite`, otherwise its scalar dep covers
        every parameter (an over-approximation of the unknown
        arity). `bind` returns a `_Callable` carrying the bound
        actuals in its `bound` slot — invocations prepend them so
        the params stay full-length — while the bound scalars
        also fold into `captured`; `origin` carries over so an
        imported callee still invokes under its own module's
        scope."""
        this_arg = vals[0] if vals else None
        this_val = (
            this_arg if isinstance(this_arg, _Composite) else None
        )
        if prop == "bind":
            bound = vals[1:]
            bound_deps = (
                _scalar_of(this_arg)
                if this_arg is not None
                else frozenset()
            )
            for val in bound:
                bound_deps |= _scalar_of(val)
            out = _Callable(
                base.node,
                base.params,
                base.defaults,
                base.captured | bound_deps,
                base.rest,
                base.is_method,
            )
            prev_deps, prev_vals, prev_this = (
                base.bound if base.bound is not None
                else ((), (), None)
            )
            out.bound = (
                tuple(prev_deps)
                + tuple(_scalar_of(v) for v in bound),
                tuple(prev_vals) + tuple(bound),
                prev_this if prev_this is not None else this_val,
            )
            out.origin = base.origin
            out.patterns = base.patterns
            out.alts = base.alts
            out.extra = base.extra
            transfers.append(
                TsCall(
                    _span(node),
                    callee_text,
                    deps,
                    out.captured,
                )
            )
            return out
        if prop == "call":
            call_vals = vals[1:]
            call_deps = deps[1:]
        else:  # apply
            arr = vals[1] if len(vals) > 1 else None
            if isinstance(arr, _Composite):
                # Array actuals bind positionally — digit keys
                # sort numerically (`a[1]`/`a[0]` insertion order
                # is not argument order); other keys follow.
                digit_keys = sorted(
                    (k for k in arr.fields if k.isdigit()),
                    key=int,
                )
                call_vals = [arr.fields[k] for k in digit_keys]
                call_vals += [
                    arr.fields[k]
                    for k in arr.fields
                    if not k.isdigit()
                ]
                call_deps = [_scalar_of(v) for v in call_vals]
            elif arr is None:
                call_vals = []
                call_deps = []
            else:
                arr_deps = _scalar_of(arr)
                call_vals = None
                call_deps = [arr_deps] * max(len(base.params), 1)
        result = self._invoke_callable(
            base,
            call_deps,
            params,
            locals_,
            transfers,
            count,
            _span(node),
            this_val=this_val,
            actual_values=call_vals,
            may=may,
        )
        transfers.append(
            TsCall(_span(node), callee_text, deps, result)
        )
        return result

    def _collection_call(
        self,
        prop,
        base_val,
        obj_node,
        actual,
        arguments,
        params,
        locals_,
        transfers,
        count,
        node,
        may=False,
    ):
        """`a.map(cb)` / `a.push(x)` / `a.join(s)` — built-in
        container methods on a `_Composite`. `elem` is the union
        of every leaf dep (the model doesn't correlate indexes);
        a function-literal or bound-callable first arg invokes
        with `elem` bound to its first parameter."""
        span = _span(node)
        callee = (
            _callee_name(obj_node) + "." + prop
            if obj_node is not None
            else prop
        )
        elem = _scalar_of(base_val)
        # Evaluate the callback raw — `actual` already holds its
        # scalarized deps; invoke it on the element union when a
        # callable is bound.
        cb_node = next(iter(_children(arguments)), None)
        cb_result = None
        # Every callback formal binds `elem | actuals` —
        # map's (v, i, arr) and reduce's (acc, v) differ in
        # position, and the model can't correlate them, so
        # each parameter takes the union (over-approximation).
        cb_actual = elem
        for a in actual:
            cb_actual |= a
        if cb_node is not None and cb_node.type in {
            "arrow_function",
            "function_expression",
            "generator_function",
        }:
            cval = self._callable_value(
                cb_node,
                params,
                locals_,
                is_method=cb_node.type != "arrow_function",
            )
            cb_result = _scalar_of(
                self._invoke_callable(
                    cval,
                    tuple(cb_actual for _ in cval.params),
                    params,
                    locals_,
                    transfers,
                    count,
                    span,
                    may=may,
                )
            )
        elif cb_node is not None and cb_node.type == "identifier":
            raw_cb = self._lookup(
                cb_node.text.decode(), params, locals_,
                _span(cb_node),
            )
            if isinstance(raw_cb, _Callable):
                cb_result = _scalar_of(
                    self._invoke_callable(
                        raw_cb,
                        tuple(cb_actual for _ in raw_cb.params),
                        params,
                        locals_,
                        transfers,
                        count,
                        span,
                        may=may,
                    )
                )
        actual_union = frozenset()
        for a in actual:
            actual_union |= a

        def record(result):
            transfers.append(
                TsCall(span, callee, actual, _scalar_of(result))
            )
            return result

        if base_val.klass is _MAP_SET_KLASS:
            # Map/Set — `set`/`add`/`delete`/`clear` may-write the
            # entry table (a literal key writes precisely, any
            # other key lands in the `"*"` bucket and every
            # existing entry takes the may-write union); reads
            # (`get`/`has`/`size`, iteration views) carry the
            # whole entry union.
            arg_nodes = _children(arguments)
            first = arg_nodes[0] if arg_nodes else None
            lit_key = (
                first.text.decode().strip("\"'")
                if first is not None and first.type == "string"
                else None
            )
            if prop in {"set", "add", "delete", "clear"}:
                tbase, tpath, _ = self._member_target(
                    obj_node, params, locals_, transfers, count
                )
                if tpath and any(k is None for k in tpath):
                    raise _Unsupported("unsupported_expression", span)
                if isinstance(tbase, str):
                    target = self._write_scope(tbase, locals_, params)
                    if target is None:
                        raise _Unsupported("binding_unavailable", span)
                else:
                    target = None
                if target is None or not isinstance(tbase, str):
                    # A non-name base (`m.set(a, x).set(b, y)`) —
                    # the result composite IS the live object;
                    # mutating it in place propagates the write
                    # through every alias, matching reference
                    # semantics for a container value.
                    old = base_val
                    if not isinstance(old, _Composite):
                        raise _Unsupported(
                            "unsupported_expression", span
                        )
                    added = dict(old.fields)
                    for key in list(added):
                        added[key] = _merge_vals(
                            added[key], actual_union
                        )
                    if prop in {"set", "add"}:
                        stored = (
                            actual[1]
                            if len(actual) > 1
                            else actual_union
                        )
                        if lit_key is not None:
                            added[lit_key] = _merge_vals(
                                added.get(lit_key, frozenset()),
                                stored,
                            )
                        else:
                            added["*"] = _merge_vals(
                                added.get("*", frozenset()), stored
                            )
                    old.fields.clear()
                    old.fields.update(added)
                    new = old
                else:
                    old = target.get(tbase)
                    if not isinstance(old, _Composite):
                        raise _Unsupported(
                            "unsupported_expression", span
                        )
                    added = dict(old.fields)
                    for key in list(added):
                        added[key] = _merge_vals(
                            added[key], actual_union
                        )
                    if prop in {"set", "add"}:
                        stored = (
                            actual[1]
                            if len(actual) > 1
                            else actual_union
                        )
                        if lit_key is not None:
                            added[lit_key] = _merge_vals(
                                added.get(lit_key, frozenset()),
                                stored,
                            )
                        else:
                            added["*"] = _merge_vals(
                                added.get("*", frozenset()), stored
                            )
                    new = (
                        _composite_set(
                            old, tpath + ["*"], actual_union, True, span
                        )
                        if tpath
                        else _Composite(added, klass=old.klass, deleted=old.deleted)
                    )
                    for name, val in locals_.items():
                        if val is old:
                            locals_[name] = new
                if prop in {"set", "add"}:
                    # `m.set(k, v)`/`s.add(v)` return the
                    # collection itself — chaining must keep
                    # the updated entry table.
                    return record(new)
                if prop == "delete":
                    # The boolean result observes the key and
                    # the entry that may leave the table.
                    return record(elem | actual_union)
                return record(frozenset())
            if prop in {"keys", "values", "entries"}:
                return record(
                    _Composite({str(0): elem, "*": elem})
                )
            if prop == "get" and lit_key is not None and (
                lit_key in base_val.fields
            ):
                return record(
                    base_val.fields[lit_key] | actual_union
                )
            # `get`/`has`/`size`/`forEach`/dynamic-key `get` —
            # the entry union over-approximates the result.
            return record(elem | actual_union)

        if prop == "forEach":
            # Undefined result — the callback's effects are the
            # transfers it recorded.
            return record(frozenset())
        if prop in {"push", "unshift"}:
            # Mutating append/prepend — copy-on-write like
            # `_member_store`: rebind every same-scope alias to
            # the grown instance. `push` appends ONE slot per
            # actual; `unshift` shifts every existing element
            # right by the argument count.
            old, tpath, arr = self._array_base(
                obj_node, params, locals_, transfers, count, span
            )
            added = dict(arr.fields)
            if prop == "push":
                next_idx = 0
                for k in added:
                    if k.isdigit() and int(k) >= next_idx:
                        next_idx = int(k) + 1
                for j, adeps in enumerate(actual):
                    added[str(next_idx + j)] = adeps
            else:
                n_args = len(actual)
                added = {
                    (str(int(k) + n_args) if k.isdigit() else k): v
                    for k, v in added.items()
                }
                for j, adeps in enumerate(actual):
                    added[str(j)] = adeps
            added["*"] = added.get("*", frozenset()) | actual_union
            self._rebind_composite(
                locals_,
                old,
                tpath,
                _Composite(
                    added, klass=arr.klass, deleted=arr.deleted
                ),
                span,
            )
            return record(actual_union)
        if prop == "fill":
            # `a.fill(v)` mutates in place — every element takes
            # the actual union (COW rebind like `push`).
            tbase, tpath, _ = self._member_target(
                obj_node, params, locals_, transfers, count
            )
            if tpath and any(k is None for k in tpath):
                raise _Unsupported("unsupported_expression", span)
            target = self._write_scope(tbase, locals_, params)
            if target is None:
                raise _Unsupported("binding_unavailable", span)
            old = target.get(tbase)
            if not isinstance(old, _Composite):
                raise _Unsupported("unsupported_expression", span)
            added = {
                k: _scalar_of(v) | actual_union
                for k, v in old.fields.items()
            }
            new = (
                _Composite(
                    added, klass=old.klass, deleted=old.deleted
                )
                if not tpath
                else _composite_set(
                    old, tpath,
                    _Composite(
                        added, klass=old.klass, deleted=old.deleted
                    ),
                    True, span,
                )
            )
            if self._may_depth:
                _merge_into(old, new)
            else:
                for name, val in locals_.items():
                    if val is old:
                        locals_[name] = new
            return record(actual_union)
        if prop in {"map", "flatMap"}:
            result = cb_result if cb_result is not None else elem
            return record(_Composite({str(0): result, "*": result}))
        if prop == "filter":
            filt = elem | (cb_result or frozenset())
            return record(_Composite({str(0): filt, "*": filt}))
        if prop in {
            "slice",
            "concat",
            "flat",
            "sort",
            "reverse",
        }:
            permuted = elem | actual_union
            return record(
                _Composite({str(0): permuted, "*": permuted})
            )
        if prop in {"keys", "values", "entries"}:
            return record(_Composite({str(0): elem, "*": elem}))
        if prop in {"pop", "shift"}:
            # Mutating removal — `pop` drops the highest index,
            # `shift` drops index 0 and moves every element down.
            old, tpath, arr = self._array_base(
                obj_node, params, locals_, transfers, count, span
            )
            added = dict(arr.fields)
            if prop == "pop":
                idxs = [int(k) for k in added if k.isdigit()]
                if idxs:
                    added.pop(str(max(idxs)), None)
            else:
                added.pop("0", None)
                added = {
                    (str(int(k) - 1) if k.isdigit() else k): v
                    for k, v in added.items()
                }
            self._rebind_composite(
                locals_,
                old,
                tpath,
                _Composite(
                    added, klass=arr.klass, deleted=arr.deleted
                ),
                span,
            )
            return record(elem | (cb_result or frozenset()))
        if prop in {"at", "find"}:
            # The found element over-approximates to the whole
            # element union.
            return record(elem | (cb_result or frozenset()))
        # some/every/findIndex/includes/indexOf/lastIndexOf/join/
        # reduce/reduceRight/toString — a scalar over the elements
        # and actuals (reduce adds the callback's accumulated
        # deps through `cb_result`).
        result = elem | actual_union
        if cb_result is not None:
            result |= cb_result
        return record(result)

    def _eval(self, node, params, locals_, transfers, count):
        """Evaluate a node to its raw value: a scalar dependency set
        or a `_Composite` for object shapes."""
        count[0] += 1
        if count[0] > MAX_NODES:
            raise _Unsupported("analysis_limit", _span(node))
        kind = node.type
        if kind == "this":
            # `this` binds only inside a method/ctor invoked
            # through a member path or `new` — anywhere else the
            # read is unbound.
            return self._lookup("this", params, locals_, _span(node))
        if kind == "identifier":
            return self._lookup(
                node.text.decode(), params, locals_, _span(node)
            )
        if kind == "object":
            # `{a: x, b: {c: y}, short}` — a composite tracking deps
            # per field. `{...o}` copies the source composite's
            # fields (later members override); a scalar spread or a
            # computed `{[k]: v}` key adds unknown fields the model
            # can't name, so the whole literal collapses to a scalar
            # union. `get`/`set` members collect into a synthetic
            # accessor class on the composite.
            fields: dict = {}
            spilled = frozenset()
            ogetters: dict = {}
            osetters: dict = {}
            for child in _children(node):
                if child.type == "pair":
                    key = child.child_by_field_name("key")
                    fval = child.child_by_field_name("value")
                    if key is None or fval is None:
                        raise _Unsupported(
                            "unsupported_expression", _span(child)
                        )
                    fdeps = self._eval(
                        fval, params, locals_, transfers, count
                    )
                    if isinstance(fdeps, _Composite) and (
                        fval.type != "object"
                    ):
                        # `{a: o2}` aliases `o2` at field level —
                        # writes would diverge, so collapse.
                        fdeps = _scalar_of(fdeps)
                    if key.type == "computed_property_name":
                        # `{[k]: v}` — the key isn't nameable; the
                        # field it adds can't be tracked, so the
                        # literal collapses.
                        spilled |= _scalar_of(fdeps)
                        for inner in _children(key):
                            spilled |= self.expression(
                                inner, params, locals_, transfers,
                                count,
                            )
                        continue
                    if key.type not in {
                        "property_identifier",
                        "string",
                        "number",
                    }:
                        raise _Unsupported(
                            "unsupported_expression", _span(child)
                        )
                    fields[
                        key.text.decode().strip("\"'")
                        if key.type == "string"
                        else key.text.decode()
                    ] = fdeps
                elif child.type == "shorthand_property_identifier":
                    # `{o}` — a whole-name composite alias
                    # collapses like a non-literal field value;
                    # function/class values keep their shape so
                    # `{e}` + `m.e(x)` invokes through the field
                    # (same as the explicit `{e: e}` pair form).
                    fval = self._lookup(
                        child.text.decode(),
                        params,
                        locals_,
                        _span(child),
                    )
                    fields[child.text.decode()] = (
                        _scalar_of(fval)
                        if isinstance(fval, _Composite)
                        else fval
                    )
                elif child.type == "spread_element":
                    src = self._eval(
                        next(iter(_children(child))),
                        params,
                        locals_,
                        transfers,
                        count,
                    )
                    if isinstance(src, _Composite):
                        fields.update(src.fields)
                    else:
                        # `{...scalar}` adds unknowable fields.
                        spilled |= src
                elif child.type == "method_definition":
                    # `{m(v) { ... }}` — a callable field value;
                    # `o.m(x)` invokes like a slice-13 member call.
                    # `get`/`set` collect into a synthetic class's
                    # accessor tables so `o.p`/`o.p = v` route
                    # through the same invoke paths classes use
                    # (the literal instance is `this`). `static`
                    # markers stay closed; `*` (generator) and
                    # `async` admit like their free-function forms.
                    # `this` inside closes at invoke.
                    markers = {
                        c.type
                        for c in child.children
                        if not c.is_named
                    }
                    if markers & {"static"}:
                        raise _Unsupported(
                            "unsupported_expression", _span(child)
                        )
                    mname = child.child_by_field_name("name")
                    if mname is not None and (
                        mname.type == "computed_property_name"
                    ):
                        # `{[k]() {}}` — unnameable member; like a
                        # class's computed member it registers
                        # under a synthetic name so a dynamic
                        # `o[k]()` finds it among the candidates.
                        for inner in _children(mname):
                            spilled |= self.expression(
                                inner, params, locals_, transfers,
                                count,
                            )
                        try:
                            fields[f"[computed:{child.start_byte}]"] = (
                                self._callable_value(
                                    child, params, locals_,
                                    is_method=True,
                                )
                            )
                        except _Unsupported:
                            pass
                        continue
                    if mname is None or mname.type != "property_identifier":
                        raise _Unsupported(
                            "unsupported_expression", _span(child)
                        )
                    if "get" in markers:
                        ogetters[mname.text.decode()] = (
                            self._callable_value(
                                child, params, locals_, is_method=True
                            )
                        )
                    elif "set" in markers:
                        osetters[mname.text.decode()] = (
                            self._callable_value(
                                child, params, locals_, is_method=True
                            )
                        )
                    else:
                        fields[mname.text.decode()] = (
                            self._callable_value(
                                child, params, locals_, is_method=True
                            )
                        )
                else:
                    raise _Unsupported(
                        "unsupported_expression", _span(child)
                    )
            oklass = None
            if ogetters or osetters:
                # Accessors aren't own fields — the synthetic class
                # carries them so `o.p`/`o.p = v` take the same
                # getter/setter paths instances take. Its captured
                # flattens the accessors' captured deps.
                ocaptured = frozenset()
                for fn in (*ogetters.values(), *osetters.values()):
                    ocaptured |= fn.captured
                oklass = _Class(
                    None, {}, {}, {}, ocaptured, None,
                    ogetters, osetters,
                )
            if spilled:
                return spilled | _scalar_of(
                    _Composite(fields, klass=oklass)
                )
            return _Composite(fields, klass=oklass)
        if kind == "array":
            # `[e0, e1]` — a composite with positional keys; `a[0]`
            # reads field "0", a dynamic `a[i]` unions the elements,
            # and `a.length` reads a missing field (dep-free).
            # `[...a]` appends the source's positional fields in
            # numeric order; a scalar spread or a composite holding
            # non-positional fields can't enumerate, so the literal
            # collapses to a scalar union.
            afields: dict = {}
            spilled = frozenset()
            i = 0
            expecting = True
            for child in node.children:
                if child.type in {"[", "]"}:
                    continue
                if child.type == ",":
                    # A comma while an element is expected is a
                    # hole — `[ ,x]` puts `x` at index 1.
                    if expecting:
                        i += 1
                    else:
                        expecting = True
                    continue
                if not child.is_named:
                    continue
                if child.type == "spread_element":
                    inner = next(iter(_children(child)), None)
                    if inner is None:
                        raise _Unsupported(
                            "unsupported_expression", _span(child)
                        )
                    src = self._eval(
                        inner, params, locals_, transfers, count
                    )
                    if isinstance(src, _Composite) and all(
                        k.isdigit() for k in src.fields
                    ):
                        for k in sorted(src.fields, key=int):
                            afields[str(i)] = src.fields[k]
                            i += 1
                    else:
                        spilled |= _scalar_of(src)
                        i += 1
                    expecting = False
                    continue
                fdeps = self._eval(
                    child, params, locals_, transfers, count
                )
                if isinstance(fdeps, _Composite) and child.type not in {
                    "object",
                    "array",
                }:
                    # `[o]` aliases `o` at field level — collapse.
                    fdeps = _scalar_of(fdeps)
                afields[str(i)] = fdeps
                i += 1
                expecting = False
            if spilled:
                return spilled | _scalar_of(_Composite(afields))
            return _Composite(afields)
        if kind in {"member_expression", "subscript_expression"}:
            return self._member_read(
                node, params, locals_, transfers, count
            )
        if kind in {
            "number",
            "true",
            "false",
            "string",
            "undefined",
            "null",
            "regex",
        }:
            return frozenset()
        if kind == "template_string":
            # Interpolations evaluate for deps/calls — the string
            # result carries the union of their deps.
            result = frozenset()
            for child in _children(node):
                # `string_fragment` is literal text; only the
                # substitutions evaluate.
                if child.type == "template_substitution":
                    for inner in _children(child):
                        result |= self.expression(
                            inner, params, locals_, transfers, count
                        )
            return result
        if kind == "parenthesized_expression":
            exprs = _children(node)
            if len(exprs) != 1:
                raise _Unsupported("unsupported_expression", _span(node))
            # Preserve the value — a parenthesized callable or
            # composite must keep its shape for `(() => x)()`
            # and `(o).f` to work; callers flatten as needed.
            return self._eval(exprs[0], params, locals_, transfers, count)
        if kind == "sequence_expression":
            # The comma operator: each operand evaluates for its
            # writes/calls. A scalar result over-approximates to
            # the union of every operand's deps; a composite or
            # callable keeps the LAST element's shape so
            # `(o, f)(x)` can still invoke `f`.
            exprs = _children(node)
            if not exprs:
                raise _Unsupported("unsupported_expression", _span(node))
            vals = [
                self._eval(child, params, locals_, transfers, count)
                for child in exprs
            ]
            last = vals[-1]
            if not isinstance(last, frozenset):
                return last
            result = last
            for val in vals[:-1]:
                result |= _scalar_of(val)
            return result
        if kind == "meta_property":
            # `import.meta`, `new.target` — meta reads carry no
            # dependencies in this model.
            return frozenset()
        if kind in {
            "jsx_element",
            "jsx_self_closing_element",
            "jsx_fragment",
        }:
            return self._jsx(node, params, locals_, transfers, count)
        if kind.startswith("jsx_"):
            # Wrappers (`jsx_expression`, `jsx_attribute`,
            # `jsx_opening/closing_element`, `jsx_text`) — the
            # value is the union of their named children.
            result = frozenset()
            for child in _children(node):
                if child.type == "spread_element":
                    # `{...props}` — a bare `spread_element` only
                    # appears inside JSX; eval its operand.
                    inner = next(iter(_children(child)), None)
                    if inner is not None:
                        result |= _scalar_of(
                            self._eval(
                                inner, params, locals_, transfers,
                                count,
                            )
                        )
                    continue
                result |= _scalar_of(
                    self._eval(child, params, locals_, transfers, count)
                )
            return result
        if kind == "await_expression":
            # `await` yields the operand's value — for the dep model
            # that's a pass-through. `for await (...)` iterates the
            # same way the plain `of` loop does.
            operand = next(
                (c for c in node.children if c.is_named), None
            )
            if operand is None:
                raise _Unsupported("unsupported_expression", _span(node))
            return self.expression(operand, params, locals_, transfers, count)
        if kind == "unary_expression":
            op = node.child_by_field_name("operator")
            argument = node.child_by_field_name("argument")
            if op is None or argument is None or (
                op.type not in _UNARY_OPS
                and op.type not in {"void", "typeof", "delete"}
            ):
                raise _Unsupported("unsupported_expression", _span(node))
            if op.type == "delete":
                # `delete o.f` removes the field copy-on-write; a
                # dynamic key may hit any field, so it keeps them all
                # (the surviving deps over-approximate); `delete x`
                # on a name is a runtime no-op. Yields a boolean —
                # no deps.
                if argument.type in {
                    "member_expression",
                    "subscript_expression",
                }:
                    self._member_delete(
                        argument, params, locals_, transfers, count
                    )
                elif argument.type == "identifier":
                    self._read_name(
                        argument, params, locals_, _span(argument)
                    )
                else:
                    self.expression(
                        argument, params, locals_, transfers, count
                    )
                return frozenset()
            deps_a = self.expression(
                argument, params, locals_, transfers, count
            )
            # `void` discards to `undefined`; `typeof`'s string has no
            # dependency shape, so the operand's deps are the
            # over-approximation.
            return frozenset() if op.type == "void" else deps_a
        if kind in {
            "as_expression",
            "satisfies_expression",
            "non_null_expression",
        }:
            # Type assertions and `!` don't change the value — the
            # operand's deps pass through.
            operand = next(iter(_children(node)), None)
            if operand is None:
                raise _Unsupported("unsupported_expression", _span(node))
            return self.expression(
                operand, params, locals_, transfers, count
            )
        if kind == "binary_expression":
            op = node.child_by_field_name("operator")
            left = node.child_by_field_name("left")
            right = node.child_by_field_name("right")
            if (
                op is None
                or left is None
                or right is None
                or op.type not in _BINARY_OPS
            ):
                raise _Unsupported("unsupported_expression", _span(node))
            left_deps = self.expression(
                left, params, locals_, transfers, count
            )
            if op.type in {"&&", "||", "??"}:
                # Short-circuit: the RHS may not run — its writes
                # to shared composites are may-writes.
                self._may_depth += 1
                try:
                    right_deps = self.expression(
                        right, params, locals_, transfers, count
                    )
                finally:
                    self._may_depth -= 1
            else:
                right_deps = self.expression(
                    right, params, locals_, transfers, count
                )
            return left_deps | right_deps
        if kind == "yield_expression":
            # `yield e` / `yield* e` — the operand's deps are the
            # iterator's element deps; the sent-back value is
            # unknown (dep-free).
            operand = next(iter(_children(node)), None)
            if operand is not None:
                self.yield_deps.append(
                    _scalar_of(
                        self._eval(
                            operand, params, locals_, transfers, count
                        )
                    )
                )
            return frozenset()
        if kind in {
            "arrow_function",
            "function_expression",
            "generator_function",
        }:
            return self._callable_value(
                node,
                params,
                locals_,
                is_method=kind != "arrow_function",
            )
        if kind in {
            "class",
            "class_declaration",
            "abstract_class_declaration",
        }:
            return self._class_value(node, params, locals_)
        if kind == "new_expression":
            # `new C(args)` — the callee resolves to a `_Class`
            # (constructed) or a function-expression ctor; `new`
            # on anything else closes.
            ctor_node = node.child_by_field_name("constructor")
            args_node = node.child_by_field_name("arguments")
            if ctor_node is None:
                raise _Unsupported(
                    "unsupported_expression", _span(node)
                )
            # `new C` without parentheses constructs with no args.
            vals_n: list = []
            actual_n = (
                self._call_actuals(
                    args_node,
                    params,
                    locals_,
                    transfers,
                    count,
                    node,
                    values_out=vals_n,
                )
                if args_node is not None
                else ()
            )
            if ctor_node.type == "identifier":
                raw_n = self._lookup(
                    ctor_node.text.decode(), params, locals_,
                    _span(ctor_node),
                )
            elif ctor_node.type in {
                "member_expression",
                "subscript_expression",
            }:
                raw_n = self._member_read(
                    ctor_node, params, locals_, transfers, count
                )
            elif ctor_node.type in {
                "class",
                "parenthesized_expression",
            }:
                raw_n = self._eval(
                    ctor_node, params, locals_, transfers, count
                )
            else:
                raise _Unsupported(
                    "unsupported_expression", _span(node)
                )
            if isinstance(raw_n, _Class):
                result_n = self._construct(
                    raw_n,
                    actual_n,
                    params,
                    locals_,
                    transfers,
                    count,
                    _span(node),
                    actual_values=vals_n,
                )
                transfers.append(
                    TsCall(
                        _span(node),
                        "new " + _callee_name(ctor_node),
                        actual_n,
                        _scalar_of(result_n),
                    )
                )
                return result_n
            if (
                ctor_node.type == "identifier"
                and ctor_node.text.decode()
                in {"Map", "Set", "WeakMap", "WeakSet"}
                and isinstance(raw_n, _External)
            ):
                # `new Map([[k, v], ...])` / `new Set([v])` — a
                # container instance; constructor entries seed
                # the unknown-key `"*"` bucket.
                seed = frozenset()
                for a in actual_n:
                    seed |= a
                return _Composite(
                    {"*": seed} if seed else {},
                    klass=_MAP_SET_KLASS,
                )
            if isinstance(raw_n, _External):
                # `new` on an imported ctor — the instance shape
                # is unknown; the value conservatively carries
                # every actual's deps.
                result_n = frozenset()
                for a in actual_n:
                    result_n |= a
                self._opaque_call_writes(vals_n, result_n)
                transfers.append(
                    TsCall(
                        _span(node),
                        "new " + _callee_name(ctor_node),
                        actual_n,
                        result_n,
                    )
                )
                return result_n
            if isinstance(raw_n, _Callable) and raw_n.is_method:
                # `new f()` on a `function` value — `this` is a
                # fresh composite; the instance is the value.
                result_n = self._invoke_callable(
                    raw_n,
                    actual_n,
                    params,
                    locals_,
                    transfers,
                    count,
                    _span(node),
                    this_val=_Composite({}),
                    construct=True,
                    actual_values=vals_n,
                )
                transfers.append(
                    TsCall(
                        _span(node),
                        "new " + _callee_name(ctor_node),
                        actual_n,
                        _scalar_of(result_n),
                    )
                )
                return result_n
            if isinstance(raw_n, frozenset) or raw_n is None:
                # `new (cond ? C : D)()` — the ctor joined to a
                # scalar; the instance over-approximates to the
                # callee scalar plus the actuals (opaque ctor).
                result_n = _scalar_of(raw_n)
                for a in actual_n:
                    result_n |= a
                self._opaque_call_writes(vals_n, result_n)
                transfers.append(
                    TsCall(
                        _span(node),
                        "new " + _callee_name(ctor_node),
                        actual_n,
                        result_n,
                    )
                )
                return result_n
            raise _Unsupported(
                "unsupported_expression", _span(node)
            )
        if kind == "call_expression":
            function = node.child_by_field_name("function")
            arguments = node.child_by_field_name("arguments")
            if function is None or arguments is None:
                raise _Unsupported("unsupported_expression", _span(node))
            # `f?.(x)` carries a `?.` marker between callee and
            # arguments; `o?.f(x)`/`o?.[k](x)` carry an
            # `optional_chain` inside the callee. On a scalar
            # (unmodellable) callee an optional call evaluates to
            # its args' dep union — treating a maybe-absent callee
            # as run is the sound over-approximation.
            optional_call = any(
                c.type == "?." for c in node.children
            ) or _has_optional_chain(function)
            if function.type in {
                "member_expression",
                "subscript_expression",
            }:
                # `o.f(x)` — the field may hold a `_Callable`
                # (`{f: v => v}`). There is no `this` binding —
                # a body reading `this` closes inside.
                vals_m: list = []
                actual_m = self._call_actuals(
                    arguments,
                    params,
                    locals_,
                    transfers,
                    count,
                    node,
                    values_out=vals_m,
                )
                try:
                    raw = self._member_read(
                        function, params, locals_, transfers, count
                    )
                except _Unsupported:
                    # A call-expression base (`a.slice().concat`)
                    # has no member path — let the builtin/optional
                    # fallbacks below decide before closing.
                    raw = frozenset()
                if isinstance(raw, _External):
                    result_m = frozenset()
                    for a in actual_m:
                        result_m |= a
                    self._opaque_call_writes(vals_m, result_m)
                    transfers.append(
                        TsCall(
                            _span(node),
                            _callee_name(function),
                            actual_m,
                            result_m,
                        )
                    )
                    return result_m
                if not isinstance(raw, _Callable):
                    prop_node = function.child_by_field_name("property")
                    prop = (
                        prop_node.text.decode()
                        if prop_node is not None
                        and prop_node.type == "property_identifier"
                        else None
                    )
                    obj_node2 = function.child_by_field_name("object")
                    base_val2 = (
                        self._eval(
                            obj_node2, params, locals_, transfers,
                            count,
                        )
                        if obj_node2 is not None
                        else None
                    )
                    if (
                        isinstance(base_val2, _Composite)
                        and (
                            (
                                base_val2.klass is _MAP_SET_KLASS
                                and prop in _MAP_SET_METHODS
                            )
                            or (
                                prop not in base_val2.fields
                                and prop in _COLLECTION_METHODS
                            )
                        )
                    ):
                        return self._collection_call(
                            prop,
                            base_val2,
                            obj_node2,
                            actual_m,
                            arguments,
                            params,
                            locals_,
                            transfers,
                            count,
                            node,
                            may=optional_call,
                        )
                    if isinstance(base_val2, frozenset):
                        # A member call on a scalar base
                        # (`s.indexOf(x)`, `m.f(x)` on an opaque
                        # `require` result) — the result carries
                        # the base's deps plus the actuals' union
                        # (same over-approximation as an
                        # `_External` callee).
                        result_m = base_val2
                        for a in actual_m:
                            result_m |= a
                        self._opaque_call_writes(vals_m, result_m)
                        transfers.append(
                            TsCall(
                                _span(node),
                                _callee_name(function),
                                actual_m,
                                result_m,
                            )
                        )
                        return result_m
                    if isinstance(base_val2, _Callable) and prop in {
                        "call",
                        "apply",
                        "bind",
                    }:
                        # `g.call(t, a)`, `g.apply(t, [a])`,
                        # `g.bind(t, a)` — Function.prototype
                        # plumbing on a known callable value.
                        return self._funproto_call(
                            prop,
                            base_val2,
                            vals_m,
                            actual_m,
                            params,
                            locals_,
                            transfers,
                            count,
                            node,
                            _callee_name(function),
                            may=optional_call,
                        )
                    if (
                        isinstance(base_val2, _Composite)
                        and prop is None
                    ):
                        # `o[k](x)` — a dynamic key can't pick the
                        # field, so every callable field is invoked
                        # and the results union (an
                        # over-approximation: non-callable fields
                        # contribute their scalar through `raw`).
                        result_m = _scalar_of(raw)
                        for a in actual_m:
                            result_m |= a
                        cands = list(base_val2.fields.values())
                        if base_val2.klass is not None:
                            # An instance's methods live on the
                            # class, not its fields.
                            cands += base_val2.klass.methods.values()
                        for fval in cands:
                            if isinstance(fval, _Callable):
                                result_m |= self._invoke_callable(
                                    fval,
                                    actual_m,
                                    params,
                                    locals_,
                                    transfers,
                                    count,
                                    _span(node),
                                    actual_values=vals_m,
                                    this_val=(
                                        base_val2
                                        if fval.is_method
                                        else None
                                    ),
                                    may=optional_call,
                                )
                        transfers.append(
                            TsCall(
                                _span(node),
                                _callee_name(function),
                                actual_m,
                                result_m,
                            )
                        )
                        return result_m
                    if not optional_call:
                        raise _Unsupported(
                            "unsupported_expression", _span(node)
                        )
                    result_m = _scalar_of(raw)
                    for a in actual_m:
                        result_m |= a
                    self._opaque_call_writes(vals_m, result_m)
                    transfers.append(
                        TsCall(
                            _span(node),
                            _callee_name(function),
                            actual_m,
                            result_m,
                        )
                    )
                    return result_m
                # A `function`/shorthand method invoked through a
                # member path receives `this` = the object; an
                # arrow never does. A maybe-deleted slot's
                # alternate callee may still want the receiver.
                this_val = None
                alt_this = None
                if raw.is_method or any(
                    alt.is_method for alt in raw.alts
                ):
                    obj_node = function.child_by_field_name("object")
                    if obj_node is not None and obj_node.type == "super":
                        # `super.m(x)` — `this` stays the instance.
                        base_val = self._lookup(
                            "this", params, locals_, _span(obj_node)
                        )
                    else:
                        base_val = (
                            None
                            if obj_node is None
                            else self._eval(
                                obj_node, params, locals_,
                                transfers, count,
                            )
                        )
                    if isinstance(base_val, _Composite):
                        # The primary binds `this` only when it is
                        # method-shaped; alternates take their own.
                        this_val = base_val if raw.is_method else None
                        alt_this = base_val
                result = self._invoke_callable(
                    raw,
                    actual_m,
                    params,
                    locals_,
                    transfers,
                    count,
                    _span(node),
                    this_val=this_val,
                    actual_values=vals_m,
                    alt_this=alt_this,
                    may=optional_call,
                )
                transfers.append(
                    TsCall(
                        _span(node),
                        _callee_name(function),
                        actual_m,
                        result,
                    )
                )
                return result
            if function.type == "super":
                # `super(args)` in a derived ctor — run the
                # parent constructor on the same `this`.
                this_v = self._lookup(
                    "this", params, locals_, _span(node)
                )
                klass = (
                    this_v.klass
                    if isinstance(this_v, _Composite)
                    else None
                )
                parent = klass.parent if klass is not None else None
                if parent is None or parent.ctor is None:
                    raise _Unsupported(
                        "unsupported_expression", _span(node)
                    )
                vals_s: list = []
                actual_s = self._call_actuals(
                    arguments,
                    params,
                    locals_,
                    transfers,
                    count,
                    node,
                    values_out=vals_s,
                )
                inst = self._invoke_callable(
                    parent.ctor,
                    actual_s,
                    params,
                    locals_,
                    transfers,
                    count,
                    _span(node),
                    this_val=this_v,
                    construct=True,
                    actual_values=vals_s,
                    may=optional_call,
                )
                locals_["this"] = inst
                transfers.append(
                    TsCall(
                        _span(node), "super", actual_s,
                        _scalar_of(inst),
                    )
                )
                return _scalar_of(inst)
            if function.type == "import":
                # `import('m')` — a dynamic import promise; the
                # callee is opaque, so it yields the actuals'
                # union like an `_External` call.
                vals_i: list = []
                actual_i = self._call_actuals(
                    arguments,
                    params,
                    locals_,
                    transfers,
                    count,
                    node,
                    values_out=vals_i,
                )
                result_i = frozenset()
                for a in actual_i:
                    result_i |= a
                self._opaque_call_writes(vals_i, result_i)
                transfers.append(
                    TsCall(_span(node), "import", actual_i, result_i)
                )
                return result_i
            if function.type != "identifier":
                # `(() => x)()`, `(g)(x)`, `(x > 0 ? g : h)(x)` —
                # the callee is an expression: evaluate it. A
                # `_Callable` invokes inline; an `_External`
                # yields the actuals' union; anything else is a
                # scalar (possibly a collapsed callable, e.g. a
                # conditional pick) whose captured deps plus the
                # actuals' union over-approximate the result —
                # the same bound the optional-call fallback uses.
                vals_e: list = []
                actual_e = self._call_actuals(
                    arguments,
                    params,
                    locals_,
                    transfers,
                    count,
                    node,
                    values_out=vals_e,
                )
                raw = self._eval(
                    function, params, locals_, transfers, count
                )
                if isinstance(raw, _Callable):
                    result_e = self._invoke_callable(
                        raw,
                        actual_e,
                        params,
                        locals_,
                        transfers,
                        count,
                        _span(node),
                        actual_values=vals_e,
                        may=optional_call,
                    )
                    transfers.append(
                        TsCall(
                            _span(node),
                            _callee_name(function),
                            actual_e,
                            result_e,
                        )
                    )
                    return result_e
                result_e = frozenset() if isinstance(raw, _External) else _scalar_of(raw)
                for a in actual_e:
                    result_e |= a
                self._opaque_call_writes(vals_e, result_e)
                transfers.append(
                    TsCall(
                        _span(node),
                        _callee_name(function),
                        actual_e,
                        result_e,
                    )
                )
                return result_e
            callee = _callee_name(function)
            bound = (
                callee in locals_
                or callee in self.function_locals
                or callee in params
                or callee in self.imports
                or callee in self.imported_bindings
                or callee in self.module_locals
                or callee in _GLOBALS
            )
            if not bound and callee not in self.functions:
                raise _Unsupported(
                    "call_unresolved", _span(node), callee
                )
            vals: list = []
            actual = self._call_actuals(
                arguments,
                params,
                locals_,
                transfers,
                count,
                node,
                values_out=vals,
            )
            if bound:
                # A local binding shadows a same-named function
                # declaration — JS resolution order.
                if callee == "require" and self.resolver is not None:
                    spec = self._require_specifier(arguments)
                    if spec is not None:
                        cval = self._resolve_require(spec)
                        if cval is not None:
                            transfers.append(
                                TsCall(
                                    _span(node),
                                    callee,
                                    actual,
                                    _scalar_of(cval),
                                )
                            )
                            return cval
                raw = self._lookup(
                    callee, params, locals_, _span(function)
                )
                if isinstance(raw, _External):
                    result_i = frozenset()
                    for a in actual:
                        result_i |= a
                    self._opaque_call_writes(vals, result_i)
                    transfers.append(
                        TsCall(
                            _span(node), callee, actual, result_i
                        )
                    )
                    return result_i
                if not isinstance(raw, _Callable):
                    # Scalar callee — a joined callable
                    # (`b ? g : h`), a value that isn't
                    # provably callable: the result carries
                    # the callee's scalar plus the actuals'
                    # union (an over-approximation — the same
                    # shape the optional-call path uses).
                    result_i = _scalar_of(raw)
                    for a in actual:
                        result_i |= a
                    self._opaque_call_writes(vals, result_i)
                    transfers.append(
                        TsCall(
                            _span(node), callee, actual, result_i
                        )
                    )
                    return result_i
                result = self._invoke_callable(
                    raw,
                    actual,
                    params,
                    locals_,
                    transfers,
                    count,
                    _span(node),
                    actual_values=vals,
                    may=optional_call,
                )
                transfers.append(
                    TsCall(_span(node), callee, actual, result)
                )
                return result
            result = frozenset().union(*actual) if actual else frozenset()
            self._opaque_call_writes(vals, result)
            transfers.append(
                TsCall(_span(node), callee, actual, result)
            )
            return result
        if kind == "update_expression":
            # `x++` / `o.f++` inside an expression (`return x++`) —
            # a dep-preserving read of the bound name; the store is
            # statement-level only.
            argument = node.child_by_field_name("argument")
            if argument is None or argument.type not in {
                "identifier",
                "member_expression",
                "subscript_expression",
            }:
                raise _Unsupported("unsupported_expression", _span(node))
            deps = _scalar_of(
                self._eval(argument, params, locals_, transfers, count)
            )
            # The expression still writes: `o.p++` runs the setter
            # path and `x++` rebinds the name — each a may-write
            # carrying the pre-increment deps.
            if argument.type == "identifier":
                aname = argument.text.decode()
                scope = self._write_scope(aname, locals_, params)
                if scope is not None:
                    self._store(
                        scope, params, aname, deps, True
                    )
            else:
                self._member_store(
                    argument,
                    deps,
                    params,
                    locals_,
                    transfers,
                    count,
                    True,
                )
            return deps
        if kind in {
            "assignment_expression",
            "augmented_assignment_expression",
        }:
            # An assignment inside an expression writes like the
            # statement form and yields the assigned dependencies.
            # Stores inside an expression are always may-writes.
            try:
                self._assignment(
                    node, params, locals_, transfers, count, True,
                    augmented=kind == "augmented_assignment_expression",
                )
            except _Unsupported as u:
                raise _Unsupported(
                    "unsupported_expression"
                    if u.reason == "unsupported_statement"
                    else u.reason,
                    u.span,
                ) from u
            left = node.child_by_field_name("left")
            return _scalar_of(
                self._eval(left, params, locals_, transfers, count)
            )
        if kind == "ternary_expression":
            condition = node.child_by_field_name("condition")
            consequence = node.child_by_field_name("consequence")
            alternative = node.child_by_field_name("alternative")
            if (
                condition is None
                or consequence is None
                or alternative is None
            ):
                raise _Unsupported("unsupported_expression", _span(node))
            deps = self.expression(
                condition, params, locals_, transfers, count
            )
            # Each arm may not run — writes inside are may-writes.
            self._may_depth += 1
            try:
                deps |= self.expression(
                    consequence, params, locals_, transfers, count
                )
                deps |= self.expression(
                    alternative, params, locals_, transfers, count
                )
            finally:
                self._may_depth -= 1
            return deps
        raise _Unsupported("unsupported_expression", _span(node))


def summarize_typescript(
    source: "str | bytes", resolver=None, source_path=None
) -> TsSummarySet:
    """Compose conservative dependencies only; never infer equality or
    safety.

    A nonempty dependency set can overapproximate dependence (`x*0`
    still includes `x`). `None` means unavailable, never a
    parameter-independent or effect-free result.

    `resolver` is optional: a callable mapping an import specifier
    (e.g. `./b`) to that module's source text, or `None` when the
    specifier can't be resolved. Resolved modules are parsed and
    summarized like any unit — imported names bind to the imported
    module's exported values (functions/classes/const bindings),
    and an imported callable invokes under its own module's scope.
    Anything unresolvable stays `_External`: a call through it
    records a transfer and yields the actuals' union, the same
    over-approximation as before resolution existed, so resolution
    can only ever sharpen a summary, never weaken it.
    """
    raw = source.encode() if isinstance(source, str) else source
    root = _syntax(raw)
    if root is None:
        return TsSummarySet(
            hashlib.sha256(raw).hexdigest(),
            (),
        )
    module_digests: dict[str, str] = {}
    builder = _Builder(
        root,
        resolver=resolver,
        module_digests=module_digests,
        source_path=source_path,
    )
    functions = builder.summarize_all()
    context = hashlib.sha256(raw)
    for spec, digest in sorted(module_digests.items()):
        # The unit's identity covers every resolved module's bytes —
        # an imported source change must invalidate reuse, not just
        # the primary file's.
        context.update(spec.encode())
        context.update(b"\x00")
        context.update(digest.encode())
        context.update(b"\x00")
    return TsSummarySet(
        context.hexdigest(),
        functions,
    )


# Opt-in CLI routes — `python -m agent ts-summaries <file>` prints the
# summary set as deterministic JSON on stdout, and
# `python -m agent ts-summaries-accept <file> --manifest <PATH>
# --function <NAME>` accepts one function's declared summary under the
# strict whole-context gate (context key match + the function still
# present in the fresh derivation). These change no default
# audit/CLI/MCP route: the analysis stays a conservative dependency
# report, not a proof, verdict or trust gate, and a host must invoke
# the subcommands explicitly. Inputs are bounded — an oversized source
# or manifest is an error, never a silently truncated analysis.
MAX_SOURCE_BYTES = 64 * 1024
ACCEPT_PROFILE = "mumei.ts-summary-accept/v1"
# A manifest derives from bounded sources (64 KiB each, at most
# MAX_MODULE_DEPTH modules), so 8 MiB bounds a declared manifest
# file the accept route reads.
MAX_MANIFEST_BYTES = 8 * 1024 * 1024


def build_parser(parser=None):
    import argparse

    if parser is None:
        parser = argparse.ArgumentParser(
            prog="python -m agent ts-summaries",
            description=(
                "Emit opt-in TypeScript interprocedural dependency "
                "summaries as JSON — a conservative report, not a "
                "proof or verdict."
            ),
        )
    parser.add_argument(
        "source",
        help="Path to a single TypeScript/JavaScript source file "
        "(at most 64 KiB).",
    )
    parser.add_argument(
        "--resolve-modules",
        action="store_true",
        help="Resolve relative './'/'../' import specifiers to "
        "source files under the source file's directory "
        "(each at most 64 KiB; unresolvable names stay external).",
    )
    return parser


def build_accept_parser(parser=None):
    """Parser for ``ts-summaries-accept``: the produce route's
    declared inputs plus ``--manifest`` and ``--function`` naming the
    declared manifest and the function whose summary is accepted."""
    parser = build_parser(parser)
    parser.description = (
        "Re-derive the TypeScript summary set for one declared source "
        "and accept one function's summary under the strict "
        "whole-context gate."
    )
    parser.add_argument(
        "--manifest",
        required=True,
        metavar="<PATH>",
        help=(
            "Summary manifest (mumei.ts-scalar-parameter-deps/v1) "
            "to accept from."
        ),
    )
    parser.add_argument(
        "--function",
        required=True,
        metavar="<NAME>",
        help=(
            "Name of the function whose summary to accept — accepted "
            "only when the manifest's context key still matches the "
            "fresh derivation and the function survives in it."
        ),
    )
    return parser


def _emit(payload, code):
    import json
    import sys

    print(json.dumps(payload, sort_keys=True))
    sys.exit(code)


ATTEMPT_REQUEST_PROFILE = "mumei.ts-summaries-attempt-request/v1"
ATTEMPT_REPORT_PROFILE = "mumei.ts-summaries-attempt-report/v1"


def build_attempt_parser(parser=None):
    """Parser for ``ts-summaries-attempt``: the produce route's
    declared inputs plus the attempt's own declared timeout and an
    optional memory bound. ``--resolve-modules`` is rejected — the
    request fingerprint cannot bind files resolved implicitly."""
    parser = build_parser(parser)
    parser.description = (
        "Run the ts-summaries produce route as one declared attempt "
        "and emit the reconciled lineage descriptors."
    )
    parser.add_argument(
        "--attempt-timeout",
        type=int,
        required=True,
        metavar="<MS>",
        help="Declared attempt bound in milliseconds (required).",
    )
    parser.add_argument(
        "--memory-bound-mb",
        type=int,
        default=None,
        metavar="<MB>",
        help=(
            "Optional declared POSIX RLIMIT_AS ceiling applied to the "
            "attempt child's whole address space."
        ),
    )
    parser.add_argument(
        "--output",
        metavar="<PATH>",
        help="Write the attempt report JSON here instead of stdout.",
    )
    return parser


def _attempt_fingerprint(source_path: str, raw: bytes) -> str:
    """Bind the request's declared input into one request identity."""
    import hashlib
    import json

    request_doc = {
        "schema_version": ATTEMPT_REQUEST_PROFILE,
        "source": {
            "path": source_path,
            "sha256": hashlib.sha256(raw).hexdigest(),
        },
    }
    return hashlib.sha256(
        json.dumps(
            request_doc, sort_keys=True, separators=(",", ":")
        ).encode()
    ).hexdigest()


def main_attempt(args=None) -> None:
    """Run the produce route as one declared attempt.

    Spawns ``python -m agent ts-summaries <source>`` through the
    C11 dispatch lifecycle: a fresh ``AttemptSequence`` keyed to the
    request fingerprint (the declared source's bytes), one reserved
    attempt observed by ``dispatch_attempt`` under
    ``--attempt-timeout``, reconcile and compare-and-set
    publication — an ``exited`` run's captured stdout becomes the
    selected result only when every declared input byte is unchanged
    after the observed run. ``--resolve-modules`` is refused:
    implicit module resolution names files the request identity
    cannot cover. Emits ``mumei.ts-summaries-attempt-report/v1`` —
    the canonical lineage, the normalized run-result descriptor and,
    only when a result was selected, the
    ``mumei.verifier-evidence-candidate/v1`` descriptor.
    """
    import json
    import sys
    from pathlib import Path

    if args is None:
        args = build_attempt_parser().parse_args()
    if args.output is not None:
        try:
            same = (
                Path(args.output).resolve() == Path(args.source).resolve()
            )
        except RuntimeError:
            same = True
        if not same:
            try:
                import os

                same = os.path.samefile(args.output, args.source)
            except OSError:
                same = False
        if same:
            _emit(
                {
                    "schema_version": ATTEMPT_REPORT_PROFILE,
                    "error": {
                        "reason": "output_overwrites_source",
                        "detail": (
                            "declared output path would overwrite a "
                            "declared source"
                        ),
                    },
                },
                2,
            )
    if args.resolve_modules:
        _emit(
            {
                "schema_version": ATTEMPT_REPORT_PROFILE,
                "error": {
                    "reason": "unsupported_option",
                    "detail": (
                        "--resolve-modules resolves files implicitly; "
                        "the attempt request fingerprint cannot bind "
                        "undeclared bytes"
                    ),
                },
            },
            2,
        )
    raw = _read_declared_source(args.source, ATTEMPT_REPORT_PROFILE)
    from agent.attempt_runner import dispatch_attempt
    from agent.verification_attempt import (
        AttemptSequence,
        AttemptSequenceStore,
    )

    fingerprint = _attempt_fingerprint(args.source, raw)
    argv = (
        sys.executable,
        "-m",
        "agent",
        "ts-summaries",
        args.source,
    )
    try:
        sequence = AttemptSequence(fingerprint, args.attempt_timeout)
        store = AttemptSequenceStore()
        store.publish(sequence)
        current = store.current
        dispatch = dispatch_attempt(
            current.begin_attempt(),
            argv,
            memory_bound_mb=args.memory_bound_mb,
        )
        try:
            drifted = (
                _attempt_fingerprint(
                    args.source, Path(args.source).read_bytes()
                )
                != fingerprint
            )
        except OSError:
            drifted = True
        if dispatch.run.record.state == "exited" and not drifted:
            updated = dispatch.sequence.select_result(
                dispatch.captured_output()
            )
        else:
            updated = dispatch.sequence
        published = store.compare_and_set(current, updated)
    except ValueError as exc:
        _emit(
            {
                "schema_version": ATTEMPT_REPORT_PROFILE,
                "error": {"reason": "attempt_failed", "detail": str(exc)},
            },
            2,
        )
    report = {
        "schema_version": ATTEMPT_REPORT_PROFILE,
        "sequence": published.to_dict(),
        "normalized": dispatch.run.normalized().to_dict(),
    }
    if published.selected_result is not None:
        report["candidate"] = published.evidence_candidate().to_dict()
    document = json.dumps(report, indent=2, sort_keys=True) + "\n"
    if args.output:
        with open(args.output, "w", encoding="utf-8") as handle:
            handle.write(document)
    else:
        sys.stdout.write(document)

def _read_declared_source(path, schema):
    try:
        with open(path, "rb") as handle:
            raw = handle.read(MAX_SOURCE_BYTES + 1)
    except OSError as exc:
        _emit(
            {
                "schema_version": schema,
                "error": {
                    "reason": "source_unreadable",
                    "detail": exc.strerror or str(exc),
                },
            },
            2,
        )
    if len(raw) > MAX_SOURCE_BYTES:
        _emit(
            {
                "schema_version": schema,
                "error": {
                    "reason": "source_too_large",
                    "limit_bytes": MAX_SOURCE_BYTES,
                },
            },
            2,
        )
    return raw


CHECK_PROFILE = "mumei.ts-summary-check/v1"


def build_check_parser(parser=None):
    """Parser for ``ts-summaries-check``: the produce route's
    declared inputs plus ``--manifest`` naming the summary manifest
    to check and ``--output`` for the check report."""
    parser = build_parser(parser)
    parser.description = (
        "Re-derive the TypeScript summary set for one declared "
        "source and check a declared manifest's functions against "
        "it."
    )
    parser.add_argument(
        "--manifest",
        required=True,
        metavar="<PATH>",
        help=(
            "Summary manifest (mumei.ts-scalar-parameter-deps/v1) "
            "to check."
        ),
    )
    parser.add_argument(
        "--output",
        metavar="<PATH>",
        help="Write the check report JSON here instead of stdout.",
    )
    return parser


def build_reuse_parser(parser=None):
    """Parser for ``ts-summaries-reuse``: the produce route's
    declared inputs plus ``--manifest`` naming the manifest to reuse
    from and ``--output`` for the merged manifest."""
    parser = build_check_parser(parser)
    parser.description = (
        "Re-derive the TypeScript summary set for one declared "
        "source and emit a manifest that reuses a declared "
        "manifest's unchanged summaries."
    )
    for action in parser._actions:
        if action.dest == "manifest":
            action.help = (
                "Summary manifest (mumei.ts-scalar-parameter-deps/v1) "
                "to reuse unchanged summaries from."
            )
        elif action.dest == "output":
            action.help = (
                "Write the merged manifest JSON here instead of "
                "stdout."
            )
    return parser


def _read_declared_manifest(path, schema=ACCEPT_PROFILE):
    import json

    try:
        with open(path, "rb") as handle:
            blob = handle.read(MAX_MANIFEST_BYTES + 1)
    except OSError as exc:
        _emit(
            {
                "schema_version": schema,
                "error": {
                    "reason": "manifest_unreadable",
                    "detail": exc.strerror or str(exc),
                },
            },
            2,
        )
    if len(blob) > MAX_MANIFEST_BYTES:
        _emit(
            {
                "schema_version": schema,
                "error": {
                    "reason": "manifest_too_large",
                    "limit_bytes": MAX_MANIFEST_BYTES,
                },
            },
            2,
        )
    try:
        return TsSummarySet.from_dict(json.loads(blob))
    except (TypeError, UnicodeDecodeError):
        _emit(
            {
                "schema_version": schema,
                "error": {
                    "reason": "manifest_malformed",
                    "detail": "declared summary manifest is malformed",
                },
            },
            2,
        )
    except ValueError as exc:
        _emit(
            {
                "schema_version": schema,
                "error": {
                    "reason": "manifest_malformed",
                    "detail": str(exc),
                },
            },
            2,
        )


def _resolver_for(args):
    if getattr(args, "resolve_modules", False):
        return _fs_resolver(args.source)
    return None


def main(args=None) -> None:
    import json

    if args is None:
        args = build_parser().parse_args()
    raw = _read_declared_source(args.source, PROFILE)
    live = summarize_typescript(
        raw, resolver=_resolver_for(args), source_path=args.source
    )
    print(json.dumps(live.to_dict(), sort_keys=True))


def main_accept(args=None) -> None:
    if args is None:
        args = build_accept_parser().parse_args()
    declared = _read_declared_manifest(args.manifest)
    raw = _read_declared_source(args.source, ACCEPT_PROFILE)
    live = summarize_typescript(
        raw, resolver=_resolver_for(args), source_path=args.source
    )
    report = {
        "schema_version": ACCEPT_PROFILE,
        "accepted": False,
        "function": args.function,
        "context_match": declared.context_key == live.context_key,
    }
    if not report["context_match"]:
        report["reason"] = "context_mismatch"
    else:
        # Emit the freshly derived record, never the declared one —
        # identical for honest manifests, and removes the manifest-
        # forgery channel entirely.
        matches = [
            f for f in live.functions if f.name == args.function
        ]
        declared_names = {f.name for f in declared.functions}
        if not matches:
            report["reason"] = "unknown_function"
        elif len(matches) > 1:
            # Nested + top-level declarations can share a plain
            # name — an ambiguous target must never adopt one
            # function's summary for another's.
            report["reason"] = "ambiguous_function"
        elif matches[0].name not in declared_names:
            report["reason"] = "undeclared_function"
        else:
            report["accepted"] = True
            report["summary"] = matches[0].to_dict()
    _emit(report, 0)


def _fs_resolver(source_path):
    """Filesystem module resolver for `--resolve-modules`:
    relative `./`/`../` specifiers only, confined to the source
    file's own directory tree, each candidate read bounded by
    MAX_SOURCE_BYTES. Anything else — bare specifiers (`react`),
    escaping paths, missing or oversized files — returns None so
    the import stays external."""
    from pathlib import Path

    try:
        base = Path(source_path).resolve().parent
    except OSError:
        return lambda spec: None

    def resolve(spec, importer=None):
        if not spec.startswith(("./", "../")):
            return None
        try:
            # `./`/`../` resolve against the IMPORTING module's
            # directory — an imported file's own imports are
            # relative to it, not to the entry file.
            ibase = (
                Path(importer).resolve().parent
                if importer is not None
                else base
            )
            target = (ibase / spec).resolve()
        except OSError:
            return None
        candidates = [target]
        if target.suffix == "":
            candidates += [
                target.with_suffix(".ts"),
                target.with_suffix(".js"),
                target / "index.ts",
            ]
        for cand in candidates:
            try:
                # Resolve each CANDIDATE too — `cand.is_file()`
                # follows links, so a symlinked candidate or
                # index file could otherwise escape `base`.
                rcand = cand.resolve()
                if base not in rcand.parents and rcand != base:
                    continue
                if not rcand.is_file():
                    continue
                if rcand.stat().st_size > MAX_SOURCE_BYTES:
                    continue
                # Return the Path: the builder reads the bytes
                # and chains the importer for nested specifiers.
                return rcand
            except OSError:
                continue
        return None

    return resolve


def _reject_overwrite(output, declared_paths, schema):
    """`--output` may not overwrite a declared input — writing
    the report would destroy the bytes the report describes."""
    import os
    from pathlib import Path

    if output is None:
        return
    for declared in declared_paths:
        try:
            same = Path(output).resolve() == Path(declared).resolve()
        except RuntimeError:
            same = True
        if not same:
            try:
                same = os.path.samefile(output, declared)
            except OSError:
                same = False
        if same:
            _emit(
                {
                    "schema_version": schema,
                    "error": {
                        "reason": "output_overwrites_source",
                        "detail": (
                            "declared output path would overwrite a "
                            "declared input"
                        ),
                    },
                },
                2,
            )


def _reuse_partition(declared, live):
    """Partition the manifest's functions against the fresh set.

    `reusable` — the name survives and the record is identical
    (derivation is deterministic, so an unchanged function derives
    the same record); `stale` — the name survives but the record
    differs; `missing` — the fresh set no longer produces the name.
    Detection only.
    """
    live_by_name = {}
    for f in live.functions:
        live_by_name.setdefault(f.name, []).append(f)
    declared_counts = {}
    for entry in declared.functions:
        declared_counts[entry.name] = (
            declared_counts.get(entry.name, 0) + 1
        )
    reusable, stale, missing = [], [], []
    seen_stale, seen_missing = set(), set()
    for entry in declared.functions:
        group = live_by_name.get(entry.name)
        if group is None:
            if entry.name not in seen_missing:
                seen_missing.add(entry.name)
                missing.append(entry.name)
            continue
        if len(group) != 1 or declared_counts[entry.name] != 1:
            # Nested + top-level declarations can share a plain
            # name — an ambiguous name must never adopt a record:
            # comparing the first match while emitting the last
            # would swap one function's summary for another's.
            if entry.name not in seen_stale:
                seen_stale.add(entry.name)
                stale.append(entry.name)
            continue
        fresh = group[0]
        if fresh == entry:
            reusable.append(entry.name)
        elif entry.name not in seen_stale:
            seen_stale.add(entry.name)
            stale.append(entry.name)
    return reusable, stale, missing


def main_check(args=None) -> None:
    """Check a declared manifest against a fresh summary set.

    Emits ``mumei.ts-summary-check/v1``: whether the declared context
    key still matches (the strict whole-context gate) and a name-level
    partition of the manifest's functions — `reusable` (identical
    record survives), `stale` (same name, different record) and
    `missing` (the fresh set no longer produces the name). Detection
    only — what to recompute is the host's call.
    """
    import json

    if args is None:
        args = build_check_parser().parse_args()
    _reject_overwrite(
        getattr(args, "output", None),
        [args.manifest, args.source],
        CHECK_PROFILE,
    )
    declared = _read_declared_manifest(args.manifest, CHECK_PROFILE)
    raw = _read_declared_source(args.source, CHECK_PROFILE)
    live = summarize_typescript(
        raw, resolver=_resolver_for(args), source_path=args.source
    )
    reusable, stale, missing = _reuse_partition(declared, live)
    document = json.dumps(
        {
            "schema_version": CHECK_PROFILE,
            "context_match": declared.context_key == live.context_key,
            "reusable": sorted(reusable),
            "stale": sorted(stale),
            "missing": sorted(missing),
        },
        sort_keys=True,
    )
    if getattr(args, "output", None):
        with open(args.output, "w") as handle:
            handle.write(document + "\n")
    else:
        print(document)


def main_reuse(args=None) -> None:
    """Emit a manifest reusing a declared manifest's unchanged
    summaries.

    Same partition as ``ts-summaries-check``: a declared function
    whose record is identical under the fresh derivation is reused
    verbatim, every other live function is freshly derived and a
    `missing` entry is dropped. The emitted set is keyed to the fresh
    context — per-function reuse stays the host's weaker freshness
    choice, never the strict whole-context gate.
    """
    import json

    if args is None:
        args = build_reuse_parser().parse_args()
    _reject_overwrite(
        getattr(args, "output", None),
        [args.manifest, args.source],
        CHECK_PROFILE,
    )
    declared = _read_declared_manifest(args.manifest, CHECK_PROFILE)
    raw = _read_declared_source(args.source, CHECK_PROFILE)
    live = summarize_typescript(
        raw, resolver=_resolver_for(args), source_path=args.source
    )
    reusable, _, _ = _reuse_partition(declared, live)
    declared_by_name = {f.name: f for f in declared.functions}
    merged = [
        declared_by_name.get(f.name, f) if f.name in reusable else f
        for f in live.functions
    ]
    document = json.dumps(
        TsSummarySet(live.context_key, merged).to_dict(),
        sort_keys=True,
    )
    if getattr(args, "output", None):
        with open(args.output, "w") as handle:
            handle.write(document + "\n")
    else:
        print(document)
