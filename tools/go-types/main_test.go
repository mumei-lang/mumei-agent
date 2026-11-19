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

func TestMultiResultImportedCallDeclaresArity(t *testing.T) {
	unit := []namedSource{{"a.go", "package p\nimport \"lib\"\nfunc F(x int64) int64 { a, b := lib.G(x); return a + b }"}}
	imports := []importedUnit{{"lib", []namedSource{
		{"g.go", "package lib\nfunc G(y int64) (int64, int64) { return y, y }\nfunc H(y int64) int64 { return y }"},
	}}}
	out := analyze(request{Sources: unit, Imports: imports, TargetArch: "amd64"})
	if out.Status != "ok" {
		t.Fatalf("type checker did not produce a snapshot: %s", out.Status)
	}
	if len(out.Calls) != 1 || out.Calls[0].Kind != "direct_import" || out.Calls[0].Results != 2 {
		t.Fatal("a multi-valued imported call did not declare its arity")
	}
	unit[0].Source = "package p\nimport \"lib\"\nfunc F(x int64) int64 { return lib.H(x) }"
	out = analyze(request{Sources: unit, Imports: imports, TargetArch: "amd64"})
	if len(out.Calls) != 1 || out.Calls[0].Results != 0 {
		t.Fatal("a single-result imported call declared an arity")
	}
	// A multi-valued instantiation declares its instantiated arity.
	imports[0].Sources[0].Source = "package lib\nfunc G(y int64) (int64, int64) { return y, y }\nfunc H(y int64) int64 { return y }\nfunc GI[P any](x P) (P, P) { return x, x }"
	unit[0].Source = "package p\nimport \"lib\"\nfunc F(x int64) int64 { a, b := lib.GI[int64](x); return a + b }"
	out = analyze(request{Sources: unit, Imports: imports, TargetArch: "amd64"})
	if len(out.Calls) != 1 || out.Calls[0].Kind != "direct_import" || out.Calls[0].Results != 2 {
		t.Fatal("a multi-valued instantiated call did not declare its arity")
	}
	// An inferred instantiation `lib.GI(x)` declares the same arity.
	unit[0].Source = "package p\nimport \"lib\"\nfunc F(x int64) int64 { a, b := lib.GI(x); return a + b }"
	out = analyze(request{Sources: unit, Imports: imports, TargetArch: "amd64"})
	if len(out.Calls) != 1 || out.Calls[0].Kind != "direct_import" || out.Calls[0].Results != 2 {
		t.Fatal("an inferred multi-valued instantiated call did not declare its arity")
	}
	// A composite result in the tuple keeps the call closed.
	imports[0].Sources[0].Source = "package lib\nfunc G(y int64) (int64, []int64) { return y, nil }"
	unit[0].Source = "package p\nimport \"lib\"\nfunc F(x int64) int64 { a, _ := lib.G(x); return a }"
	out = analyze(request{Sources: unit, Imports: imports, TargetArch: "amd64"})
	if len(out.Calls) != 1 || out.Calls[0].Kind != "external_or_bodyless" || out.Calls[0].Results != 0 {
		t.Fatal("a composite multi-valued imported call was admitted")
	}
}

func TestPointerTypedSignaturesCarryPointeeIdentity(t *testing.T) {
	// `lib.Take(t)` references the member so it registers; its
	// pointer-typed parameter must pin the pointee's identity.
	unit := []namedSource{{"a.go", "package p\nimport \"lib\"\nfunc F(t *lib.T, y int64) int64 { _ = lib.Take(t); return t.PM(y) }"}}
	imports := []importedUnit{{"lib", []namedSource{
		{"m.go", "package lib\nfunc (t *T) PM(v int64) int64 { return v }\nfunc Take(t *T) int64 { return 0 }"},
		{"t.go", "package lib\ntype T int64"},
	}}}
	out := analyze(request{Sources: unit, Imports: imports, TargetArch: "amd64"})
	if out.Status != "ok" {
		t.Fatalf("type checker did not produce a snapshot: %s", out.Status)
	}
	var tID, takeID string
	var takePins []string
	for _, m := range out.ImportedMembers {
		if m.Name == "T" {
			tID = m.ID
		}
		if m.Name == "Take" {
			takeID = m.ID
			takePins = m.SignatureTypeIDs
		}
	}
	if tID == "" || takeID == "" {
		t.Fatal("the referenced members are missing")
	}
	if len(takePins) != 1 || takePins[0] != tID {
		t.Fatal("a pointer-typed parameter did not pin its pointee")
	}
	if len(out.Functions) != 1 || out.Functions[0].Parameters[0].Type.Kind != "pointer" ||
		out.Functions[0].Parameters[0].Type.TypeID != tID {
		t.Fatal("a pointer parameter lost its pointee identity")
	}
	// A pointer-typed result keeps the call on the `direct_import`
	// path — the arg-union dep set is the same as a scalar result's.
	imports[0].Sources[0].Source += "\nfunc R(t *T) *T { return t }"
	unit[0].Source = "package p\nimport \"lib\"\nfunc F(t *lib.T) *lib.T { return lib.R(t) }"
	out = analyze(request{Sources: unit, Imports: imports, TargetArch: "amd64"})
	if len(out.Calls) != 1 || out.Calls[0].Kind != "direct_import" {
		t.Fatal("a pointer-typed imported result was rejected")
	}
}

func TestNestedNamedTypeArgumentPinsEveryIdentity(t *testing.T) {
	// `lib.GI[other.N[lib.T]](n)` substitutes a generic named type —
	// the call record must pin BOTH the outer `N` and the nested `T`,
	// or a redeclaration of `T` alone would not stale the call site.
	unit := []namedSource{{"a.go", "package p\nimport \"lib\"\nimport \"other\"\nfunc F(n other.N[lib.T]) int64 { return int64(lib.GI[other.N[lib.T]](n)) }"}}
	imports := []importedUnit{
		{"lib", []namedSource{
			{"g.go", "package lib\nfunc GI[P any](v P) P { return v }"},
			{"t.go", "package lib\ntype T int64"},
		}},
		{"other", []namedSource{
			{"n.go", "package other\ntype N[A any] int64"},
		}},
	}
	out := analyze(request{Sources: unit, Imports: imports, TargetArch: "amd64"})
	if out.Status != "ok" {
		t.Fatalf("type checker did not produce a snapshot: %s", out.Status)
	}
	ids := map[string]string{}
	for _, m := range out.ImportedMembers {
		ids[m.Name] = m.ID
	}
	if ids["N"] == "" || ids["T"] == "" {
		t.Fatal("the referenced members are missing")
	}
	var got []string
	for _, c := range out.Calls {
		if c.Kind == "direct_import" {
			got = c.TypeArgTypeIDs
		}
	}
	if got == nil {
		t.Fatal("a nested named type argument was rejected")
	}
	if len(got) != 2 || got[0] != ids["N"] || got[1] != ids["T"] {
		t.Fatalf("a nested named type argument did not pin every identity: %v", got)
	}
}

func TestPointerTypeArgumentPinsPointee(t *testing.T) {
	// `lib.GK[*lib.T](p)` — a composite type argument pins every
	// named identity inside it, so a `T` redeclaration stales the
	// call site. A signature argument carries no pinnable identity
	// and must stay closed.
	unit := []namedSource{{"a.go", "package p\nimport \"lib\"\nfunc F(p *lib.T, t2 lib.T2) int64 { return lib.GK[*lib.T](p) + lib.GN[[]lib.T](t2) }"}}
	imports := []importedUnit{
		{"lib", []namedSource{
			{"g.go", "package lib\ntype T2 int64\nfunc GK[P any](v P) int64 { return 0 }\nfunc GN[P any](v T2) int64 { return 0 }"},
			{"t.go", "package lib\ntype T int64"},
		}},
	}
	out := analyze(request{Sources: unit, Imports: imports, TargetArch: "amd64"})
	if out.Status != "ok" {
		t.Fatalf("type checker did not produce a snapshot: %s", out.Status)
	}
	var tID string
	for _, m := range out.ImportedMembers {
		if m.Name == "T" {
			tID = m.ID
		}
	}
	if tID == "" {
		t.Fatal("the referenced member is missing")
	}
	direct := 0
	for _, c := range out.Calls {
		if c.Kind != "direct_import" {
			continue
		}
		direct++
		if len(c.TypeArgTypeIDs) != 1 || c.TypeArgTypeIDs[0] != tID {
			t.Fatalf("a composite type argument did not pin the pointee: %v", c.TypeArgTypeIDs)
		}
	}
	if direct != 2 {
		t.Fatalf("pointer/slice type arguments were not admitted: %d direct calls", direct)
	}
}

func TestSignatureTypeArgumentStaysClosed(t *testing.T) {
	// `lib.GK[func()](nil)` — a signature type argument carries no
	// pinnable identity, so the call record stays opaque.
	unit := []namedSource{{"a.go", "package p\nimport \"lib\"\nfunc F() int64 { return lib.GK[func()](nil) }"}}
	imports := []importedUnit{
		{"lib", []namedSource{
			{"g.go", "package lib\nfunc GK[P any](v P) int64 { return 0 }"},
		}},
	}
	out := analyze(request{Sources: unit, Imports: imports, TargetArch: "amd64"})
	if out.Status != "ok" {
		t.Fatalf("type checker did not produce a snapshot: %s", out.Status)
	}
	for _, c := range out.Calls {
		if c.Kind == "direct_import" {
			t.Fatalf("a signature type argument was admitted: %+v", c)
		}
	}
}

func TestPointerVarDeclaresPointeeMember(t *testing.T) {
	// A pointer-typed `var` member must declare its named pointee:
	// the consumer needs the pointee's own fact to classify a
	// `*lib.V` dereference read. An unnamed pointee (`*int64`) and a
	// nested pointer (`**T`) contribute no extra member.
	unit := []namedSource{{"a.go", "package p\nimport \"lib\"\nfunc F() int64 { _ = lib.PS\n\t_ = lib.PPV\n\treturn int64(*lib.PV) + *lib.PU }"}}
	imports := []importedUnit{
		{"lib", []namedSource{
			{"v.go", "package lib\nvar PV *T\nvar PU *int64\nvar PPV **T\ntype S struct{ F int64 }\nvar PS *S"},
			{"t.go", "package lib\ntype T int64"},
		}},
	}
	out := analyze(request{Sources: unit, Imports: imports, TargetArch: "amd64"})
	if out.Status != "ok" {
		t.Fatalf("type checker did not produce a snapshot: %s", out.Status)
	}
	members := map[string]member{}
	for _, m := range out.ImportedMembers {
		members[m.Name] = m
	}
	pv, ok := members["PV"]
	if !ok || pv.Kind != "var" || pv.Type.Kind != "pointer" {
		t.Fatalf("the pointer var member is missing or misclassified: %+v", pv)
	}
	tm, ok := members["T"]
	if !ok || tm.Kind != "type" || tm.Type.Kind != "integer" {
		t.Fatalf("the pointee type member is missing or misclassified: %+v", tm)
	}
	if pv.Type.TypeID != tm.ID {
		t.Fatal("the pointer fact does not name the declared pointee member")
	}
	if ppv, ok := members["PPV"]; !ok || ppv.Type.Kind != "pointer" || ppv.Type.TypeID != "" {
		t.Fatalf("a nested pointer pointee must contribute no identity: %+v", ppv)
	}
	sm, ok := members["S"]
	if !ok || sm.Kind != "type" {
		t.Fatalf("a struct pointee must still be declared: %+v", sm)
	}
}

func TestNamedPointerUnderlyingTypes(t *testing.T) {
	// `type PP *T` names a pointer through its underlying: the type
	// member itself reads `pointer` — `type_id` keeps PP's own
	// identity (a name a declaration can redeclare) while `elem`
	// carries the pointee fact. A var or signature typed `PP` then
	// declares both PP and T, exactly like `*T` declares T.
	unit := []namedSource{{"a.go", "package p\nimport \"lib\"\nfunc F(v lib.PP) int64 { _ = lib.VS\n\treturn int64(*lib.VV) + lib.G(v) }"}}
	imports := []importedUnit{
		{"lib", []namedSource{
			{"v.go", "package lib\ntype PP *T\ntype PS *[]T\nvar VV PP\nvar VS PS\nfunc G(v PP) int64 { return 0 }"},
			{"t.go", "package lib\ntype T int64"},
		}},
	}
	out := analyze(request{Sources: unit, Imports: imports, TargetArch: "amd64"})
	if out.Status != "ok" {
		t.Fatalf("type checker did not produce a snapshot: %s", out.Status)
	}
	members := map[string]member{}
	for _, m := range out.ImportedMembers {
		members[m.Name] = m
	}
	pp, ok := members["PP"]
	if !ok || pp.Kind != "type" || pp.Type.Kind != "pointer" || pp.Type.TypeID != pp.ID {
		t.Fatalf("a named pointer-underlying type member is missing or misclassified: %+v", pp)
	}
	tm, ok := members["T"]
	if !ok || tm.Kind != "type" || tm.Type.Kind != "integer" {
		t.Fatalf("the pointee type member is missing or misclassified: %+v", tm)
	}
	if pp.Type.Elem == nil || pp.Type.Elem.Kind != "integer" || pp.Type.Elem.TypeID != tm.ID {
		t.Fatalf("the named pointer fact lost its pointee: %+v", pp.Type.Elem)
	}
	ps, ok := members["PS"]
	if !ok || ps.Type.Kind != "pointer" || ps.Type.TypeID != ps.ID ||
		ps.Type.Elem == nil || ps.Type.Elem.Kind != "slice" ||
		ps.Type.Elem.Elem == nil || ps.Type.Elem.Elem.TypeID != tm.ID {
		t.Fatalf("a named pointer-to-slice member is misclassified: %+v", ps)
	}
	vv, ok := members["VV"]
	if !ok || vv.Kind != "var" || vv.Type.Kind != "pointer" || vv.Type.TypeID != pp.ID {
		t.Fatalf("a `var V PP` member must name PP: %+v", vv)
	}
	if vv.PointeeTypeIDs == nil || len(*vv.PointeeTypeIDs) != 1 ||
		(*vv.PointeeTypeIDs)[0] != tm.ID ||
		vv.PointeeKind == nil || *vv.PointeeKind != "integer" {
		t.Fatalf("a `var V PP` member lost the pointee it underlies: %+v", vv)
	}
	if vs, ok := members["VS"]; !ok || vs.Type.TypeID != ps.ID ||
		vs.PointeeKind == nil || *vs.PointeeKind != "slice" ||
		vs.PointeeTypeIDs == nil || len(*vs.PointeeTypeIDs) != 1 ||
		(*vs.PointeeTypeIDs)[0] != tm.ID {
		t.Fatalf("a `var VS PS` member lost its container pointee: %+v", vs)
	}
	// A `p lib.PP` parameter pins PP AND the pointee T it underlies —
	// the caller relies on PP's `*T` shape as surely as on a `*T`.
	g, ok := members["G"]
	if !ok {
		t.Fatal("the referenced function member is missing")
	}
	if len(g.SignatureTypeIDs) != 2 || g.SignatureTypeIDs[0] != pp.ID || g.SignatureTypeIDs[1] != tm.ID {
		t.Fatalf("a `PP` parameter did not pin the declared type and its pointee: %v", g.SignatureTypeIDs)
	}
}

func TestErrorPointerVarRecordsNoEmptyMember(t *testing.T) {
	// `var PE *error` — `error` is a universe object with no imported
	// identity, so the pointee emits no member; a member with an
	// empty id would fail the loader outright.
	unit := []namedSource{{"a.go", "package p\nimport \"lib\"\nfunc F() int64 { _ = lib.PE\n\treturn 0 }"}}
	imports := []importedUnit{
		{"lib", []namedSource{
			{"v.go", "package lib\nvar PE *error"},
		}},
	}
	out := analyze(request{Sources: unit, Imports: imports, TargetArch: "amd64"})
	if out.Status != "ok" {
		t.Fatalf("type checker did not produce a snapshot: %s", out.Status)
	}
	for _, m := range out.ImportedMembers {
		if m.ID == "" {
			t.Fatalf("a member was recorded with an empty id: %+v", m)
		}
	}
	pe, ok := func() (member, bool) {
		for _, m := range out.ImportedMembers {
			if m.Name == "PE" {
				return m, true
			}
		}
		return member{}, false
	}()
	if !ok || pe.Kind != "var" || pe.Type.Kind != "pointer" || pe.Type.TypeID != "" {
		t.Fatalf("the *error var member is missing or misclassified: %+v", pe)
	}
}

func TestSliceMemberDeclaresElemFact(t *testing.T) {
	// A slice/array member carries the element type fact a container
	// index read needs; a named slice type also keeps its own identity.
	unit := []namedSource{{"a.go", "package p\nimport \"lib\"\nfunc F(s lib.NS) int64 { return lib.VA[0] + int64(lib.VT[0]) + lib.VNS[0] + lib.AA[0] }"}}
	imports := []importedUnit{
		{"lib", []namedSource{
			{"v.go", "package lib\ntype T int64\nvar VA []int64\nvar VT []T\ntype NS []int64\nvar VNS NS\nvar AA [4]int64"},
		}},
	}
	out := analyze(request{Sources: unit, Imports: imports, TargetArch: "amd64"})
	if out.Status != "ok" {
		t.Fatalf("type checker did not produce a snapshot: %s", out.Status)
	}
	members := map[string]member{}
	for _, m := range out.ImportedMembers {
		members[m.Name] = m
	}
	va, ok := members["VA"]
	if !ok || va.Type.Kind != "slice" || va.Type.Elem == nil ||
		va.Type.Elem.Kind != "integer" || va.Type.TypeID != "" {
		t.Fatalf("an unnamed slice member must declare its element fact: %+v", va)
	}
	vt, ok := members["VT"]
	if !ok || vt.Type.Kind != "slice" || vt.Type.Elem == nil ||
		vt.Type.Elem.Kind != "integer" || vt.Type.Elem.TypeID == "" {
		t.Fatalf("a named-element slice must carry the element identity: %+v", vt)
	}
	ns, ok := members["NS"]
	if !ok || ns.Kind != "type" || ns.Type.Kind != "slice" || ns.Type.Elem == nil {
		t.Fatalf("a named slice type must carry the slice fact: %+v", ns)
	}
	vns, ok := members["VNS"]
	if !ok || vns.Type.Kind != "slice" || vns.Type.Elem == nil ||
		vns.Type.Elem.Kind != "integer" || vns.Type.TypeID != ns.ID {
		t.Fatalf("a named-slice member must pin its declared type: %+v", vns)
	}
	aa, ok := members["AA"]
	if !ok || aa.Type.Kind != "array" || aa.Type.Elem == nil ||
		aa.Type.Elem.Kind != "integer" {
		t.Fatalf("an array member must declare its element fact: %+v", aa)
	}
}

func TestMapMemberDeclaresKeyAndElemFacts(t *testing.T) {
	// A map member carries both the key and the value facts a map
	// index read needs; a named key keeps its own identity.
	unit := []namedSource{{"a.go", "package p\nimport \"lib\"\nfunc F(k lib.MK) int64 { _ = lib.VM\n\treturn lib.VMK[k] }"}}
	imports := []importedUnit{
		{"lib", []namedSource{
			{"v.go", "package lib\ntype MK int64\nvar VM map[string]int64\nvar VMK map[MK]int64"},
		}},
	}
	out := analyze(request{Sources: unit, Imports: imports, TargetArch: "amd64"})
	if out.Status != "ok" {
		t.Fatalf("type checker did not produce a snapshot: %s", out.Status)
	}
	members := map[string]member{}
	for _, m := range out.ImportedMembers {
		members[m.Name] = m
	}
	vm, ok := members["VM"]
	if !ok || vm.Type.Kind != "map" || vm.Type.Key == nil ||
		vm.Type.Key.BasicName != "string" || vm.Type.Elem == nil ||
		vm.Type.Elem.Kind != "integer" || vm.Type.TypeID != "" {
		t.Fatalf("an unnamed map member must declare key and value facts: %+v", vm)
	}
	vmk, ok := members["VMK"]
	if !ok || vmk.Type.Kind != "map" || vmk.Type.Key == nil ||
		vmk.Type.Key.TypeID == "" || vmk.Type.Elem == nil ||
		vmk.Type.Elem.Kind != "integer" {
		t.Fatalf("a named-key map must carry the key identity: %+v", vmk)
	}
}

func TestRecursiveSliceTypeTerminates(t *testing.T) {
	// `type R []R` is valid Go — the element fact must stop at the
	// type's own identity instead of recursing forever.
	unit := []namedSource{{"a.go", "package p\nimport \"lib\"\nfunc F() int64 { _ = lib.VR\n\treturn 0 }"}}
	imports := []importedUnit{
		{"lib", []namedSource{
			{"v.go", "package lib\ntype R []R\nvar VR R"},
		}},
	}
	out := analyze(request{Sources: unit, Imports: imports, TargetArch: "amd64"})
	if out.Status != "ok" {
		t.Fatalf("type checker did not produce a snapshot: %s", out.Status)
	}
	var vr *member
	for i := range out.ImportedMembers {
		if out.ImportedMembers[i].Name == "VR" {
			vr = &out.ImportedMembers[i]
		}
	}
	if vr == nil || vr.Type.Kind != "slice" || vr.Type.Elem == nil ||
		vr.Type.Elem.Kind != "unsupported" || vr.Type.Elem.TypeID == "" {
		t.Fatalf("a recursive slice must stop at its identity: %+v", vr)
	}
}

func TestRecursiveChanSignatureTypeIDsTerminate(t *testing.T) {
	// `type C chan C` is valid Go — the signature's element walk must
	// see the already-recorded identity instead of recursing until
	// the stack overflows.
	unit := []namedSource{{"a.go", "package p\ntype C chan C\nfunc F(c C) C { return c }"}}
	out := analyze(request{Sources: unit, TargetArch: "amd64"})
	if out.Status != "ok" {
		t.Fatalf("type checker did not produce a snapshot: %s", out.Status)
	}
	var fb binding
	for _, b := range named(out, "F") {
		if b.Kind == "function" {
			fb = b
		}
	}
	if fb.ID == "" {
		t.Fatalf("F missing from snapshot")
	}
	if len(fb.SignatureTypeIDs) != 1 {
		t.Fatalf("F should pin only C's identity, got %v", fb.SignatureTypeIDs)
	}
}

func TestGenericChanInstantiationsPinEachElementType(t *testing.T) {
	// `Q[A]` and `Q[B]` share the declaration's identity — the
	// element walk must still descend into each instantiation so
	// both `A` and `B` land in the signature's type deps.
	unit := []namedSource{{"a.go", "package p\ntype A int64\ntype B int64\ntype Q[T any] chan T\nfunc G(a Q[A], b Q[B]) int64 { return 0 }"}}
	out := analyze(request{Sources: unit, TargetArch: "amd64"})
	if out.Status != "ok" {
		t.Fatalf("type checker did not produce a snapshot: %s", out.Status)
	}
	var gb binding
	for _, b := range named(out, "G") {
		if b.Kind == "function" {
			gb = b
		}
	}
	if len(gb.SignatureTypeIDs) != 3 {
		t.Fatalf("G should pin Q plus each instantiation's element type, got %v", gb.SignatureTypeIDs)
	}
}

func TestLocalTypeShadowingPackageTypePinsBoth(t *testing.T) {
	// A function-local `type T` shadows the package `type T`, yet
	// `types.Type.String()` reports both as "p.T" — a guard keyed
	// on that string would walk only the first decl and drop the
	// other's emitted id. `var g func(x T, h Gn)` references the
	// local T directly and the package T through Gn's signature.
	unit := []namedSource{{"a.go", "package p\n" +
		"type T chan int64\n" +
		"type Gn func(y T) T\n" +
		"func F() {\n" +
		"\ttype T chan bool\n" +
		"\tvar g func(x T, h Gn) int64\n" +
		"\t_ = g\n" +
		"}"}}
	out := analyze(request{Sources: unit, TargetArch: "amd64"})
	if out.Status != "ok" {
		t.Fatalf("type checker did not produce a snapshot: %s", out.Status)
	}
	var gb binding
	for _, b := range named(out, "g") {
		if b.Kind == "variable" {
			gb = b
		}
	}
	if gb.ID == "" {
		t.Fatalf("g missing from snapshot")
	}
	if len(gb.SignatureTypeIDs) != 3 {
		t.Fatalf("g should pin the local T, Gn, and the package T it names, got %v", gb.SignatureTypeIDs)
	}
}

func TestClosureAndInitializerCallsHaveNoNamedBodyOwner(t *testing.T) {
	out := checked(t, `package p; func G() int { return 1 }; var X = G(); func F() int { f := func() int { return G() }; return f() }`, "amd64")
	if len(out.Calls) != 3 || out.Calls[0].Owner != "" || out.Calls[1].Owner != "" || out.Calls[2].Owner == "" {
		t.Fatal("closure/initializer calls were attributed to an enclosing named body")
	}
}

func TestFunctionValuesAreUnsupportedEvenWithoutACall(t *testing.T) {
	out := checked(t, "package p; func F(f func()) { _ = f }", "amd64")
	f := named(out, "f")[0]
	for _, gap := range out.Gaps {
		if gap.Reason == "unsupported_value_semantics" && gap.Span != nil && *gap.Span == f.Span {
			return
		}
	}
	t.Fatal("function-value binding has no unsupported-value gap")
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
