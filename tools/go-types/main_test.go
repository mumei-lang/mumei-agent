package main

import (
	"bytes"
	"encoding/json"
	"strings"
	"testing"
)

func checked(t *testing.T, source, arch string) snapshot {
	t.Helper()
	out := analyze(request{Source: source, TargetArch: arch})
	if out.Status != "ok" {
		t.Fatalf("type checker did not produce a snapshot: %s", out.Status)
	}
	return out
}

func named(out snapshot, name string) []binding {
	var result []binding
	for _, b := range out.Bindings {
		if b.Name == name {
			result = append(result, b)
		}
	}
	return result
}

func TestTargetWidthsAndNamedTypeIdentity(t *testing.T) {
	source := "package p; type Index int64; func F(x Index, n int, u uintptr, b bool) Index { return x }"
	for _, arch := range []string{"amd64", "386", "arm64"} {
		t.Run(arch, func(t *testing.T) {
			out := checked(t, source, arch)
			width := 64
			if arch == "386" {
				width = 32
			}
			if named(out, "n")[0].Type.BitWidth != width || named(out, "u")[0].Type.BitWidth != width {
				t.Fatal("target-dependent integer width was lost")
			}
			index := named(out, "Index")[0]
			if named(out, "x")[0].Type.TypeID != index.ID || index.Type.BitWidth != 64 || named(out, "b")[0].Type.BitWidth != 1 {
				t.Fatal("named/scalar type identity was lost")
			}
		})
	}
}

func TestShadowingReassignmentAndMixedShortDeclaration(t *testing.T) {
	source := `package p
func F(x int64) int64 {
 x, y := x + 1, x
 { x := y; x++; _ = x }
 x = y
 return x
}`
	out := checked(t, source, "amd64")
	xs := named(out, "x")
	if len(xs) != 2 || xs[0].ID == xs[1].ID {
		t.Fatal("shadowed lexical bindings were merged")
	}
	outer := out.Functions[0].Parameters[0].BindingID
	for _, needle := range []string{"x, y :=", "x = y", "x\n}"} {
		offset := strings.Index(source, needle)
		found := false
		for _, ref := range out.References {
			if ref.Span.Start == offset && ref.BindingID == outer {
				found = true
			}
		}
		if !found {
			t.Fatal("reassignment or a reused short-declaration binding changed identity")
		}
	}
}

func TestImplicitTypeSwitchBindingsDoNotCollide(t *testing.T) {
	out := checked(t, `package p; func F(a any) { switch x := a.(type) { case int64: _ = x; case string: _ = x } }`, "amd64")
	xs := named(out, "x")
	if len(xs) != 2 || xs[0].ID == xs[1].ID || xs[0].Span != xs[1].Span {
		t.Fatal("implicit case bindings need distinct scope-bound identities at one declaration")
	}
	uses := make(map[string]bool)
	for _, ref := range out.References {
		for _, x := range xs {
			if ref.BindingID == x.ID {
				uses[x.ID] = true
			}
		}
	}
	if len(uses) != 2 {
		t.Fatal("case-specific references did not resolve independently")
	}
}

func TestDirectCallsResolveByObjectNotName(t *testing.T) {
	source := `package p
func Callee(x int64) int64 { return x }
func Direct(x int64) int64 { return (Callee)(x) }
func Indirect(Callee func(int64) int64, x int64) int64 { return Callee(x) }
func Alias(x int64) int64 { f := Callee; return f(x) }`
	out := checked(t, source, "amd64")
	calleeID := ""
	for _, b := range named(out, "Callee") {
		if b.Kind == "function" {
			calleeID = b.ID
		}
	}
	if len(out.Calls) != 3 || out.Calls[0].Kind != "direct_local" || out.Calls[0].Target != calleeID {
		t.Fatal("a direct declaration reference was not resolved")
	}
	for _, call := range out.Calls[1:] {
		if call.Kind != "indirect_or_selector" || call.Target != "" {
			t.Fatal("a function variable was treated as a direct declaration")
		}
	}
}

func TestOpaqueCalls(t *testing.T) {
	cases := []struct{ source, kind string }{
		{"func F(x string) int { return len(x) }", "builtin"},
		{"func F(x int64) uint64 { return uint64(x) }", "conversion"},
		{"func Ext(int64) int64; func F(x int64) int64 { return Ext(x) }", "external_or_bodyless"},
		{"type T struct{}; func (T) M() int { return 1 }; func F(x T) int { return x.M() }", "method_generic_or_variadic"},
		{"type I interface{M() int}; func F(x I) int { return x.M() }", "method_generic_or_variadic"},
		{"func Id[T any](x T) T { return x }; func F(x int64) int64 { return Id[int64](x) }", "method_generic_or_variadic"},
		{"func Id[T any](x T) T { return x }; func F(x int64) int64 { return Id(x) }", "method_generic_or_variadic"},
		{"func V(x ...int) int { return 1 }; func F() int { return V(1) }", "method_generic_or_variadic"},
		{"func G() {}; func F() { go G() }", "concurrent"},
		{"func G() {}; func F() { defer G() }", "deferred"},
		{"func F() int { return (func() int { return 1 })() }", "indirect_or_selector"},
	}
	for _, tc := range cases {
		t.Run(tc.kind+tc.source[:6], func(t *testing.T) {
			out := checked(t, "package p; "+tc.source, "amd64")
			if len(out.Calls) != 1 || out.Calls[0].Kind != tc.kind || out.Calls[0].Target != "" {
				t.Fatal("an unsupported call acquired a direct target")
			}
		})
	}
}

func TestClosureAndInitializerCallsHaveNoNamedBodyOwner(t *testing.T) {
	out := checked(t, `package p; func G() int { return 1 }; var X = G(); func F() int { f := func() int { return G() }; return f() }`, "amd64")
	if len(out.Calls) != 3 || out.Calls[0].Owner != "" || out.Calls[1].Owner != "" || out.Calls[2].Owner == "" {
		t.Fatal("closure/initializer calls were attributed to an enclosing named body")
	}
}

func TestInvalidInputsNeverReturnPartialBindings(t *testing.T) {
	for _, source := range []string{
		"package p; func F() int { return unknown }",
		"package p; func F( {",
		"package p; import \"fmt\"; func F() {}",
		"//go:build linux\npackage p; func F() {}",
		"//line hidden.go:100\npackage p; func F() {}",
		"package p; type A[T any] = T",
		strings.Repeat(" ", maxSource+1),
	} {
		out := analyze(request{Source: source, TargetArch: "amd64"})
		if out.Status == "ok" || len(out.Bindings) != 0 || len(out.Functions) != 0 || len(out.Calls) != 0 {
			t.Fatal("failed or unsupported input produced partial metadata")
		}
	}
	if analyze(request{Source: "package p", TargetArch: "unknown"}).Status == "ok" {
		t.Fatal("unknown target accepted")
	}
}

func TestReplyIsDeterministicAndDoesNotEchoValuesOrDiagnostics(t *testing.T) {
	const sentinel = "obviously-fake-c06-secret-sentinel"
	t.Setenv("OPENAI_API_KEY", sentinel)
	for _, source := range []string{
		"// " + sentinel + "\npackage p; const S = \"" + sentinel + "\"; func F() int64 { return 1 }",
		"package p; var X int64 = \"" + sentinel + "\"",
		"package p; import \"" + sentinel + "\"",
		"package p; type S struct { X int `json:\"" + sentinel + "\"` }; func F() S { return S{} }",
	} {
		req, _ := json.Marshal(request{Source: source, TargetArch: "amd64"})
		var first bytes.Buffer
		run(bytes.NewReader(req), &first)
		if bytes.Contains(first.Bytes(), []byte(sentinel)) {
			t.Fatal("helper echoed a literal, comment, tag, diagnostic or environment value")
		}
		for range 5 {
			var again bytes.Buffer
			run(bytes.NewReader(req), &again)
			if !bytes.Equal(first.Bytes(), again.Bytes()) {
				t.Fatal("metadata order depends on Go map iteration")
			}
		}
	}
}

func TestProtocolRejectsMalformedRequests(t *testing.T) {
	for _, input := range []string{
		"not JSON", `{}`, `{"source":123,"target_arch":"amd64"}`,
		`{"source":"package p","target_arch":"amd64","extra":true}`,
		`{"source":"package p","target_arch":"amd64"} {}`,
		strings.Repeat(" ", maxRequest+1),
	} {
		var output bytes.Buffer
		run(strings.NewReader(input), &output)
		var reply snapshot
		if json.Unmarshal(output.Bytes(), &reply) != nil || reply.Status == "ok" {
			t.Fatal("malformed request accepted")
		}
	}
}
