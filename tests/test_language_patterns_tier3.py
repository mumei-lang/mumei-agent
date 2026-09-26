"""Unit tests for the Tier-3-lite detectors in
``agent/language_patterns.py`` — taint-lite sinks (Python/TypeScript/Go)
and Go shared-state writes outside a declared mutex."""

from __future__ import annotations

from agent.language_patterns import language_pattern_issues


def _issues(source: str, language: str):
    return language_pattern_issues(source, language)


# ---------------------------------------------------------------------------
# Taint-lite — Python
# ---------------------------------------------------------------------------


def test_python_sql_concat_tainted_flags() -> None:
    source = (
        "def find(request, cur):\n"
        "    name = request.args.get('name')\n"
        "    cur.execute('SELECT * FROM users WHERE name = %s' % name)\n"
    )
    issues = _issues(source, "python")
    assert any("query/command" in i.message and "`find`" in i.message for i in issues)


def test_python_sql_fstring_source_flags() -> None:
    source = (
        "def find(request, cur):\n"
        "    cur.execute(f\"SELECT * FROM users WHERE name = "
        "{request.args['name']}\")\n"
    )
    issues = _issues(source, "python")
    assert any("query/command" in i.message for i in issues)


def test_python_parameterized_execute_skipped() -> None:
    source = (
        "def find(request, cur):\n"
        "    name = request.args.get('name')\n"
        "    cur.execute('SELECT * FROM users WHERE name = %s', (name,))\n"
    )
    issues = _issues(source, "python")
    assert not any("query/command" in i.message for i in issues)


def test_python_html_escape_does_not_sanitize_sql() -> None:
    """``escape()`` is an HTML sanitizer — it does not parameterize SQL, so
    the concatenated query must still flag."""
    source = (
        "def find(request, cur):\n"
        "    name = request.args.get('name')\n"
        "    name = escape(name)\n"
        "    cur.execute('SELECT * FROM users WHERE name = ' + name)\n"
    )
    issues = _issues(source, "python")
    assert any("query/command" in i.message for i in issues)


def test_python_numeric_coercion_sanitizes_sql() -> None:
    """``int(name)`` makes the value numeric — safe to embed in SQL."""
    source = (
        "def find(request, cur):\n"
        "    name = request.args.get('name')\n"
        "    name = int(name)\n"
        "    cur.execute('SELECT * FROM users WHERE id = ' + str(name))\n"
    )
    issues = _issues(source, "python")
    assert not any("query/command" in i.message for i in issues)


def test_python_untainted_query_skipped() -> None:
    source = (
        "def all(cur):\n"
        "    cur.execute('SELECT * FROM users')\n"
    )
    issues = _issues(source, "python")
    assert not any("query/command" in i.message for i in issues)


# ---------------------------------------------------------------------------
# Taint-lite — TypeScript / Go
# ---------------------------------------------------------------------------


def test_typescript_inner_html_tainted_flags() -> None:
    source = (
        "function render(req: Request, el: Element) {\n"
        "    const name = req.query.name;\n"
        "    el.innerHTML = name;\n"
        "}\n"
    )
    issues = _issues(source, "typescript")
    assert any("DOM" in i.message and "`render`" in i.message for i in issues)


def test_typescript_query_tainted_flags() -> None:
    source = (
        "async function find(db: any, req: any) {\n"
        "    const id = req.params.id;\n"
        "    return db.query(`SELECT * FROM t WHERE id = ${id}`);\n"
        "}\n"
    )
    issues = _issues(source, "typescript")
    assert any("query/command" in i.message for i in issues)


def test_typescript_parameterized_query_skipped() -> None:
    source = (
        "async function find(db: any, req: any) {\n"
        "    const id = req.params.id;\n"
        "    return db.query('SELECT * FROM t WHERE id = $1', [id]);\n"
        "}\n"
    )
    issues = _issues(source, "typescript")
    assert not any("query/command" in i.message for i in issues)


def test_go_query_concat_tainted_flags() -> None:
    source = """func find(db *sql.DB, req *http.Request) {
    id := req.URL.Query().Get("id")
    db.Query("SELECT * FROM t WHERE id = " + id)
}"""
    issues = _issues(source, "go")
    assert any("query/command" in i.message for i in issues)


def test_go_parameterized_query_skipped() -> None:
    source = """func find(db *sql.DB, req *http.Request) {
    id := req.URL.Query().Get("id")
    db.Query("SELECT * FROM t WHERE id = ?", id)
}"""
    issues = _issues(source, "go")
    assert not any("query/command" in i.message for i in issues)


def test_go_query_context_skips_ctx_arg() -> None:
    source = """func find(ctx context.Context, db *sql.DB, req *http.Request) {
    id := req.URL.Query().Get("id")
    db.QueryContext(ctx, "SELECT * FROM t WHERE id = ?", id)
}"""
    issues = _issues(source, "go")
    assert not any("query/command" in i.message for i in issues)


# ---------------------------------------------------------------------------
# Go shared state outside the lock
# ---------------------------------------------------------------------------

_GO_COUNTER_FIXTURE = """var mu sync.Mutex
var counter int

%s
"""


def test_go_shared_var_write_without_lock_flags() -> None:
    source = _GO_COUNTER_FIXTURE % (
        "func bump() {\n    counter++\n}"
    )
    issues = _issues(source, "go")
    assert any("package-level `counter`" in i.message for i in issues)


def test_go_shared_var_write_under_lock_skipped() -> None:
    source = _GO_COUNTER_FIXTURE % (
        "func bump() {\n    mu.Lock()\n    defer mu.Unlock()\n    counter++\n}"
    )
    issues = _issues(source, "go")
    assert not any("package-level" in i.message for i in issues)


def test_go_shared_var_atomic_skipped() -> None:
    source = """var mu sync.Mutex
var counter int64

func bump() {
    atomic.AddInt64(&counter, 1)
}"""
    issues = _issues(source, "go")
    assert not any("`counter`" in i.message for i in issues)


def test_go_receiver_field_write_without_lock_flags() -> None:
    source = """type Server struct {
    mu sync.Mutex
    hits int
}

func (s *Server) bump() {
    s.hits++
}"""
    issues = _issues(source, "go")
    assert any("`s.hits`" in i.message for i in issues)


def test_go_receiver_field_write_under_lock_skipped() -> None:
    source = """type Server struct {
    mu sync.Mutex
    hits int
}

func (s *Server) bump() {
    s.mu.Lock()
    defer s.mu.Unlock()
    s.hits++
}"""
    issues = _issues(source, "go")
    assert not any("`s.hits`" in i.message for i in issues)


def test_go_mutex_field_write_itself_skipped() -> None:
    source = """type Server struct {
    mu sync.Mutex
    hits int
}

func (s *Server) bump() {
    s.hits = 0
    s.mu.Lock()
}"""
    issues = _issues(source, "go")
    assert not any("`s.mu`" in i.message for i in issues)


def test_go_no_mutex_in_file_skipped() -> None:
    source = """var counter int

func bump() {
    counter++
}"""
    issues = _issues(source, "go")
    assert not any("package-level" in i.message for i in issues)


def test_go_shared_var_read_only_skipped() -> None:
    source = _GO_COUNTER_FIXTURE % (
        "func read() int {\n    return counter\n}"
    )
    issues = _issues(source, "go")
    assert not any("package-level" in i.message for i in issues)


# ---------------------------------------------------------------------------
# Review-followup regressions (mumei-agent#612)
# ---------------------------------------------------------------------------


def test_python_input_call_source_flags() -> None:
    """``input()`` is a call-shaped source — the trailing word boundary
    after ``(`` must not keep it from matching."""
    source = (
        "def find(cur):\n"
        "    name = input('name: ')\n"
        "    cur.execute('SELECT * FROM users WHERE name = ' + name)\n"
    )
    issues = _issues(source, "python")
    assert any("query/command" in i.message for i in issues)


def test_go_formvalue_call_source_flags() -> None:
    source = """func find(db *sql.DB, req *http.Request) {
    id := req.FormValue("id")
    db.QueryRow("SELECT * FROM t WHERE id = " + id)
}"""
    issues = _issues(source, "go")
    assert any("query/command" in i.message for i in issues)


def test_go_queryrow_sink_flags() -> None:
    source = """func find(db *sql.DB, req *http.Request) {
    id := req.URL.Query().Get("id")
    db.QueryRow("SELECT * FROM t WHERE id = " + id)
}"""
    issues = _issues(source, "go")
    assert any("query/command" in i.message for i in issues)


def test_python_sanitize_after_sink_still_flags() -> None:
    """A sanitizer applied after the query does not protect the earlier
    sink — sinks are evaluated in statement order."""
    source = (
        "def find(request, cur):\n"
        "    name = request.args.get('name')\n"
        "    cur.execute('SELECT * FROM users WHERE name = ' + name)\n"
        "    name = html.escape(name)\n"
    )
    issues = _issues(source, "python")
    assert any("query/command" in i.message for i in issues)


def test_python_partial_sanitizer_does_not_clear_taint() -> None:
    """``escape()`` wrapping an unrelated literal must not clear the whole
    assignment's taint."""
    source = (
        "def find(request, cur):\n"
        "    name = request.args.get('name')\n"
        "    q = 'SELECT ' + name + escape('fixed')\n"
        "    cur.execute(q)\n"
    )
    issues = _issues(source, "python")
    assert any("query/command" in i.message for i in issues)


def test_python_multiline_fstring_taint_flags() -> None:
    """Interpolated names inside multi-line f-strings still count."""
    source = (
        "def find(request, cur):\n"
        "    name = request.args.get('name')\n"
        '    q = f"""\n'
        "        SELECT * FROM users\n"
        "        WHERE name = {name}\n"
        '    """\n'
        "    cur.execute(q)\n"
    )
    issues = _issues(source, "python")
    assert any("query/command" in i.message for i in issues)


def test_typescript_multiline_template_taint_flags() -> None:
    source = (
        "function find(db: any, req: any) {\n"
        "    const id = req.params.id;\n"
        "    const q = `SELECT *\n"
        "        FROM t WHERE id = ${id}`;\n"
        "    return db.query(q);\n"
        "}\n"
    )
    issues = _issues(source, "typescript")
    assert any("query/command" in i.message for i in issues)


def test_typescript_escaped_dom_write_skipped() -> None:
    """``DOMPurify.sanitize`` is a DOM-channel sanitizer (the Tier-2
    ``innerHTML`` advisory may still fire — only taint-lite must not)."""
    source = (
        "function render(req: any, el: Element) {\n"
        "    const name = DOMPurify.sanitize(req.query.name);\n"
        "    el.innerHTML = name;\n"
        "}\n"
    )
    issues = _issues(source, "typescript")
    assert not any("writes" in i.message and "to the DOM" in i.message for i in issues)


def test_go_var_block_shared_state_flags() -> None:
    """Grouped ``var ( … )`` declarations count as package state."""
    source = """var (
    mu      sync.Mutex
    counter int
)

func bump() {
    counter++
}"""
    issues = _issues(source, "go")
    assert any("package-level `counter`" in i.message for i in issues)


def test_go_comparison_not_a_write_skipped() -> None:
    """``counter == 0`` is a comparison, not a write."""
    source = _GO_COUNTER_FIXTURE % (
        "func check() int {\n"
        "    if counter == 0 {\n"
        "        return 1\n"
        "    }\n"
        "    return counter\n"
        "}"
    )
    issues = _issues(source, "go")
    assert not any("package-level" in i.message for i in issues)


def test_go_local_shadow_write_skipped() -> None:
    """``counter := 0`` declares a local — later ``counter++`` writes the
    local, not the package variable."""
    source = _GO_COUNTER_FIXTURE % (
        "func bump() {\n    counter := 0\n    counter++\n}"
    )
    issues = _issues(source, "go")
    assert not any("package-level" in i.message for i in issues)


def test_go_write_after_explicit_unlock_flags() -> None:
    """An explicit ``mu.Unlock()`` (not deferred) ends the lock window —
    writes after it race."""
    source = _GO_COUNTER_FIXTURE % (
        "func bump() {\n"
        "    mu.Lock()\n"
        "    counter++\n"
        "    mu.Unlock()\n"
        "    counter++\n"
        "}"
    )
    issues = _issues(source, "go")
    assert any("package-level `counter`" in i.message for i in issues)


def test_go_same_named_methods_per_receiver() -> None:
    """Two methods named ``bump`` on different receivers each check
    against their own receiver name."""
    source = """type A struct {
    mu   sync.Mutex
    hits int
}

type B struct {
    mu   sync.Mutex
    hits int
}

func (a *A) bump() {
    a.mu.Lock()
    a.hits++
    a.mu.Unlock()
}

func (b *B) bump() {
    b.hits++
}"""
    issues = _issues(source, "go")
    assert any("`b.hits`" in i.message for i in issues)


def test_go_generic_receiver_method_flags() -> None:
    """Methods on generic types use ``func (s *Server[T])`` receivers."""
    source = """type Server[T any] struct {
    mu   sync.Mutex
    hits int
}

func (s *Server[T]) bump() {
    s.hits++
}"""
    issues = _issues(source, "go")
    assert any("`s.hits`" in i.message for i in issues)


def test_go_method_writes_package_var_flags() -> None:
    """Method bodies also write package-level state — the plain-function
    block scanner does not see methods."""
    source = _GO_COUNTER_FIXTURE % (
        "type S struct{}\n\n"
        "func (s *S) bump() {\n"
        "    counter++\n"
        "}"
    )
    issues = _issues(source, "go")
    assert any("package-level `counter`" in i.message for i in issues)


def test_go_deferred_unlock_event_ordering() -> None:
    """A deferred ``mu.Unlock()`` is evaluated at function end — a real
    ``mu.Unlock()`` later in source must still release the write."""
    source = _GO_COUNTER_FIXTURE % (
        "func bump() {\n"
        "    mu.Lock()\n"
        "    defer mu.Unlock()\n"
        "    mu.Unlock()\n"
        "    counter++\n"
        "}"
    )
    issues = _issues(source, "go")
    assert any("package-level `counter`" in i.message for i in issues)


def test_go_write_under_undeclared_lock_flags() -> None:
    """``other.Lock()`` where ``other`` is not a declared mutex does not
    protect the package variable."""
    source = _GO_COUNTER_FIXTURE % (
        "func bump() {\n"
        "    other.Lock()\n"
        "    counter++\n"
        "}"
    )
    issues = _issues(source, "go")
    assert any("package-level `counter`" in i.message for i in issues)


def test_go_write_under_read_lock_flags() -> None:
    """``mu.RLock()`` is a shared read lock — a write under it still races."""
    source = (
        "var mu sync.RWMutex\n"
        "var counter int\n"
        "\n"
        "func bump() {\n"
        "    mu.RLock()\n"
        "    counter++\n"
        "}"
    )
    issues = _issues(source, "go")
    assert any("package-level `counter`" in i.message for i in issues)


def test_go_atomic_call_does_not_cover_plain_write() -> None:
    """``atomic.AddInt64(&counter, 1)`` elsewhere leaves ``counter++``
    unguarded — mixed atomic/plain access still races."""
    source = (
        "var mu sync.Mutex\n"
        "var counter int64\n"
        "\n"
        "func bump() {\n"
        "    atomic.AddInt64(&counter, 1)\n"
        "    counter++\n"
        "}"
    )
    issues = _issues(source, "go")
    assert any("package-level `counter`" in i.message for i in issues)


def test_go_write_before_later_shadow_flags() -> None:
    """A ``counter := 0`` declared *after* ``counter++`` does not mask the
    earlier package-level write."""
    source = _GO_COUNTER_FIXTURE % (
        "func bump() {\n"
        "    counter++\n"
        "    if ok {\n"
        "        counter := 0\n"
        "        _ = counter\n"
        "    }\n"
        "}"
    )
    issues = _issues(source, "go")
    assert any("package-level `counter`" in i.message for i in issues)


def test_go_field_of_param_not_package_write() -> None:
    """``v.counter++`` writes a param's field, not the package ``counter``."""
    source = _GO_COUNTER_FIXTURE % (
        "func bump(v struct{ counter int }) {\n"
        "    v.counter++\n"
        "}"
    )
    issues = _issues(source, "go")
    assert not any("package-level `counter`" in i.message for i in issues)


def test_python_sql_comma_inside_literal_keeps_interpolation() -> None:
    """A comma inside the f-string literal must not split the sink args —
    ``{id}`` after the comma is still detected."""
    source = (
        "def find(request, cur):\n"
        "    uid = request.args.get('id')\n"
        "    cur.execute(f'SELECT a, b FROM t WHERE id={uid}')\n"
    )
    issues = _issues(source, "python")
    assert any("query/command" in i.message for i in issues)


def test_python_literal_braces_do_not_alias_tainted_name() -> None:
    """In a plain (non-f) string, ``{name}`` is literal text — it must not
    re-taint the query through the tainted ``name`` variable."""
    source = (
        "def find(request, cur):\n"
        "    name = request.args.get('name')\n"
        "    q = 'SELECT {name}'\n"
        "    cur.execute(q)\n"
    )
    issues = _issues(source, "python")
    assert not any("query/command" in i.message for i in issues)


def test_python_backslash_continuation_keeps_taint() -> None:
    """``q = 'SELECT ' + \\`` continues on the next line — the tainted name
    on that line still reaches the sink."""
    source = (
        "def find(request, cur):\n"
        "    name = request.args.get('name')\n"
        "    q = 'SELECT ' + \\\n"
        "        name\n"
        "    cur.execute(q)\n"
    )
    issues = _issues(source, "python")
    assert any("query/command" in i.message for i in issues)


def test_typescript_dom_write_multiline_rhs_flags() -> None:
    """``el.innerHTML =`` with the tainted value on the next line."""
    source = (
        "function render(req) {\n"
        "    const name = req.query.name;\n"
        "    el.innerHTML =\n"
        "        name;\n"
        "}\n"
    )
    issues = _issues(source, "typescript")
    assert any("DOM" in i.message for i in issues)


def test_go_sprintf_taint_flow_flags() -> None:
    """``fmt.Sprintf`` keeps its variable arguments visible even though the
    format literal is masked."""
    source = """package main
import ("fmt"; "net/http"; "database/sql")
func h(w http.ResponseWriter, r *http.Request, db *sql.DB) {
    name := r.FormValue("name")
    q := fmt.Sprintf("SELECT * FROM t WHERE n='%s'", name)
    db.Exec(q)
}
"""
    issues = _issues(source, "go")
    assert any("query/command" in i.message for i in issues)


def test_go_conditional_lock_does_not_guard() -> None:
    """``mu.Lock()`` inside an ``if`` does not provably hold at the
    top-level write — the conditional lock is skipped."""
    source = _GO_COUNTER_FIXTURE % (
        "func bump(ok bool) {\n"
        "    if ok {\n"
        "        mu.Lock()\n"
        "    }\n"
        "    counter++\n"
        "}"
    )
    issues = _issues(source, "go")
    assert any("package-level `counter`" in i.message for i in issues)


def test_go_block_local_shadow_flags_outer_write() -> None:
    """``counter := 0`` inside a block only shadows writes in that
    block — a package-level write after the block still flags."""
    source = _GO_COUNTER_FIXTURE % (
        "func bump(ok bool) {\n"
        "    if ok {\n"
        "        counter := 0\n"
        "        counter++\n"
        "    }\n"
        "    counter++\n"
        "}"
    )
    issues = _issues(source, "go")
    assert any("package-level `counter`" in i.message for i in issues)


def test_python_comment_source_not_tainted() -> None:
    """A ``#`` comment mentioning ``request.args`` must not taint the
    line's value."""
    source = (
        "def handler(request):\n"
        "    n = 5  # ignores request.args\n"
        "    q = 'SELECT * FROM t WHERE n=' + str(n)\n"
        "    db.execute(q)\n"
    )
    issues = _issues(source, "python")
    assert not any("query/command" in i.message for i in issues)


def test_py_return_taint_one_level_flags() -> None:
    """A helper whose ``return`` is source-derived taints its callers'
    assignment targets (intra-file, one level)."""
    source = (
        "def helper(request):\n"
        "    return request.args['x']\n"
        "\n"
        "def handler(request):\n"
        "    v = helper(request)\n"
        "    db.execute('SELECT * FROM t WHERE n=' + v)\n"
    )
    issues = _issues(source, "python")
    assert any("query/command" in i.message for i in issues)


def test_py_return_taint_clean_helper_skipped() -> None:
    """A helper returning a constant does not taint its callers."""
    source = (
        "def helper(request):\n"
        "    return 'x'\n"
        "\n"
        "def handler(request):\n"
        "    v = helper(request)\n"
        "    db.execute('SELECT * FROM t WHERE n=' + v)\n"
    )
    issues = _issues(source, "python")
    assert not any("query/command" in i.message for i in issues)


def test_py_return_taint_single_level_only() -> None:
    """``g -> f -> source`` does not chain — one propagation level only."""
    source = (
        "def h0(request):\n"
        "    return request.args['x']\n"
        "def h1(request):\n"
        "    return h0(request)\n"
        "def handler(request):\n"
        "    v = h1(request)\n"
        "    db.execute('SELECT * FROM t WHERE n=' + v)\n"
    )
    issues = _issues(source, "python")
    assert not any("query/command" in i.message for i in issues)


def test_go_exec_command_argv_taint_flags() -> None:
    """``exec.Command(\"sh\", \"-c\", v)`` — untrusted argv flags, not just
    the program name argument."""
    source = (
        'package x\nimport "os/exec"\n'
        "func f(r *http.Request) {\n"
        '    n := r.URL.Query().Get("x")\n'
        '    exec.Command("sh", "-c", n)\n'
        "}\n"
    )
    issues = _issues(source, "go")
    assert any("query/command" in i.message for i in issues)


def test_go_strconv_itoa_sanitizes_sql() -> None:
    """``strconv.Itoa`` coerces to numeric — the SQL channel clears."""
    source = (
        'package x\nimport "strconv"\n'
        "func f(r *http.Request) {\n"
        '    n, _ := strconv.Atoi(r.URL.Query().Get("x"))\n'
        '    db.Query("SELECT * FROM t WHERE n=" + strconv.Itoa(n))\n'
        "}\n"
    )
    issues = _issues(source, "go")
    assert not any("query/command" in i.message for i in issues)


def test_go_other_receiver_mutex_not_guarding() -> None:
    """``other.mu.Lock()`` protects ``other``'s fields, not ``s.hits``."""
    source = """type A struct {
    mu sync.Mutex
}
type S struct {
    mu   sync.Mutex
    hits int
}
func (s *S) bump(other *A) {
    other.mu.Lock()
    s.hits++
    other.mu.Unlock()
}
"""
    issues = _issues(source, "go")
    assert any("`s.hits`" in i.message for i in issues)


def test_go_own_receiver_mutex_guards() -> None:
    """``s.mu.Lock()`` still guards ``s.hits`` writes."""
    source = """type S struct {
    mu   sync.Mutex
    hits int
}
func (s *S) bump() {
    s.mu.Lock()
    s.hits++
    s.mu.Unlock()
}
"""
    issues = _issues(source, "go")
    assert not any("`s.hits`" in i.message for i in issues)


def test_ts_arrow_implicit_return_taints() -> None:
    """``const helper = (req) => req.query.x`` — the bare expression is
    the implicit return, so callers of ``helper`` are tainted."""
    source = (
        "const helper = (req) => req.query.x;\n"
        "function handler(req) {\n"
        "    const v = helper(req);\n"
        "    db.query('SELECT * FROM t WHERE n=' + v);\n"
        "}\n"
    )
    issues = _issues(source, "typescript")
    assert any("query/command" in i.message for i in issues)


def test_ts_arrow_clean_body_not_tainted() -> None:
    """A bare arrow body returning a constant does not taint callers."""
    source = (
        "const helper = (req) => 'x';\n"
        "function handler(req) {\n"
        "    const v = helper(req);\n"
        "    db.query('SELECT * FROM t WHERE n=' + v);\n"
        "}\n"
    )
    issues = _issues(source, "typescript")
    assert not any("query/command" in i.message for i in issues)


def test_py_return_inside_string_literal_ignored() -> None:
    """A ``return`` appearing inside a triple-quoted string is not a real
    return — ``helper`` actually returns a constant here."""
    source = (
        "def helper(request):\n"
        '    doc = """\n'
        "    return request.args\n"
        '    """\n'
        "    return 'x'\n"
        "def handler(request):\n"
        "    v = helper(request)\n"
        "    db.execute('SELECT * FROM t WHERE n=' + v)\n"
    )
    issues = _issues(source, "python")
    assert not any("query/command" in i.message for i in issues)
