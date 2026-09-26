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


def test_python_sanitized_value_skipped() -> None:
    source = (
        "def find(request, cur):\n"
        "    name = request.args.get('name')\n"
        "    name = escape(name)\n"
        "    cur.execute('SELECT * FROM users WHERE name = ' + name)\n"
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
