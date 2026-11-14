// Command go-types emits compiler-derived source metadata, never proof evidence.
package main

import (
	"bytes"
	"crypto/sha256"
	"encoding/json"
	"fmt"
	"go/ast"
	"go/parser"
	"go/token"
	"go/types"
	"io"
	"os"
	"runtime"
	"sort"
	"strconv"
	"strings"
	"unicode/utf8"
)

const profile = "mumei.go-types-single-file/v1"
const packageProfile = "mumei.go-types-package/v1"
const languageVersion = "go1.23"
const maxSource = 64 * 1024
const maxFiles = 64
const maxImports = 64
const maxRequest = 512 * 1024
const maxReply = 8 * 1024 * 1024

type namedSource struct {
	Name   string `json:"name"`
	Source string `json:"source"`
}

// importedUnit declares one importable package as source files. Nothing is
// read from disk, the network or the toolchain — the host supplies every
// byte an import path may resolve to.
type importedUnit struct {
	Path    string        `json:"path"`
	Sources []namedSource `json:"sources"`
}

type request struct {
	Source     string         `json:"source"`
	Sources    []namedSource  `json:"sources"`
	Imports    []importedUnit `json:"imports"`
	TargetArch string         `json:"target_arch"`
}

// All spans are half-open UTF-8 byte offsets. In the single-file profile
// they index the complete input source; in the package profile each span
// also carries the `file` index into `sources` (-1 means the whole unit).
type span struct {
	File  *int `json:"file,omitempty"`
	Start int  `json:"start"`
	End   int  `json:"end"`
}

func fileSpan(file, start, end int) span {
	return span{File: &file, Start: start, End: end}
}

type typeFact struct {
	Kind      string `json:"kind"`
	BasicName string `json:"basic_name"`
	BitWidth  int    `json:"bit_width"`
	Signed    *bool  `json:"signed"`
	TypeID    string `json:"type_id"`
	// Elem carries the element type fact on slice/array kinds — `[]T`,
	// `[N]T` and named/alias types whose underlying is one — so a
	// container index read can classify the element it returns. On map
	// kinds it carries the value fact.
	Elem *typeFact `json:"elem,omitempty"`
	// Key carries the key type fact on map kinds — `map[K]V` — so a
	// named key's identity pins like the value's does.
	Key *typeFact `json:"key,omitempty"`
}

type binding struct {
	ID    string   `json:"id"`
	Name  string   `json:"name"`
	Kind  string   `json:"kind"`
	Span  span     `json:"span"`
	Scope *span    `json:"scope"`
	Type  typeFact `json:"type"`
}

type reference struct {
	Span      span   `json:"span"`
	BindingID string `json:"binding_id"`
	Kind      string `json:"kind"`
}

type parameter struct {
	BindingID string   `json:"binding_id"`
	Type      typeFact `json:"type"`
}

type function struct {
	BindingID  string      `json:"binding_id"`
	Body       *span       `json:"body"`
	Parameters []parameter `json:"parameters"`
	Results    []parameter `json:"results"`
	Method     bool        `json:"method"`
	Generic    bool        `json:"generic"`
	Variadic   bool        `json:"variadic"`
}

type call struct {
	Span      span   `json:"span"`
	Arguments []span `json:"arguments"`
	Owner     string `json:"owner"`
	Target    string `json:"target"`
	Kind      string `json:"kind"`
	// Method marks a `direct_import` call whose callee is a method on a
	// named type of an imported unit — the consumer must also evaluate
	// the receiver expression (`recv.M(args)`), not just the arguments.
	Method bool `json:"method,omitempty"`
	// Results declares the result arity of a `direct_import` callee when
	// it is greater than one — the consumer needs it to admit tuple
	// unpacking `a, b := lib.F(x)`. Single/zero-result calls omit it.
	Results int `json:"results,omitempty"`
	// TypeArgTypeIDs pins the named/alias identities an instantiated
	// callee's type arguments resolve to — `lib.G[lib.T](x)` pins `lib.T`
	// at this call site alone, where the member record's signature pins
	// could never cover a substitution declared nowhere.
	TypeArgTypeIDs []string `json:"type_arg_type_ids,omitempty"`
}

type gap struct {
	Reason string `json:"reason"`
	Span   *span  `json:"span"`
}

type fileDigest struct {
	Name   string `json:"name"`
	SHA256 string `json:"sha256"`
}

// member declares an imported object the unit referenced: its identity in
// the imported unit's own coordinate space plus the object's kind and type,
// so a consumer can tell a scalar constant from unmodelled package state.
// A function member also declares the named/alias type identities its
// signature mentions, so a caller can pin them for staleness.
type member struct {
	ID               string   `json:"id"`
	Name             string   `json:"name"`
	Kind             string   `json:"kind"`
	Type             typeFact `json:"type"`
	SignatureTypeIDs []string `json:"signature_type_ids,omitempty"`
	// PointeeTypeIDs declares the named/alias identities a pointer-typed
	// var's pointee mentions, at any depth of pointer, slice, array, map
	// or channel constructors — `**T` declares `[T]`; `*int64` declares
	// `[]`. The key is present only when the pointee tree resolves
	// fully (no signature, struct, interface or type parameter inside),
	// so its absence — not just an empty list — means unpinnable.
	PointeeTypeIDs *[]string `json:"pointee_type_ids,omitempty"`
}

type snapshot struct {
	Profile         string       `json:"profile"`
	SourceSHA256    string       `json:"source_sha256"`
	Files           []fileDigest `json:"files,omitempty"`
	TargetArch      string       `json:"target_arch"`
	LanguageVersion string       `json:"language_version"`
	CompilerVersion string       `json:"compiler_version"`
	Status          string       `json:"status"`
	Bindings        []binding    `json:"bindings"`
	References      []reference  `json:"references"`
	Functions       []function   `json:"functions"`
	Calls           []call       `json:"calls"`
	Gaps            []gap        `json:"gaps"`
	ImportedMembers []member     `json:"imported_members,omitempty"`
}

// importUnit tracks a resolved imported package's own coordinate space so
// imported objects get the same identities that unit's own report produces.
type importUnit struct {
	pkg     *types.Package
	digests []string
	files   map[*token.File]int
}

type indexer struct {
	source   string
	sources  []namedSource
	digests  []string
	files    map[*token.File]int
	packaged bool
	fset     *token.FileSet
	pkg      *types.Package
	sizes    types.Sizes
	info     *types.Info
	out      *snapshot

	importDecls    map[string][]namedSource
	importCache    map[string]*types.Package
	importInFlight map[string]bool
	importUnits    map[*types.Package]*importUnit
	importMembers  map[string]member
}

var errUnresolvedImport = fmt.Errorf("unresolved import")

// allScalarResults admits a signature when every result is a scalar
// (integer/boolean) or a pointer, at any arity — including zero. A
// pointer result carries the same arg-union dep set as a scalar one:
// the dep model tracks the binding, not the pointee, and the caller's
// own gates decide whether a `*T` binding can store it.
func allScalarResults(sig *types.Signature) bool {
	res := sig.Results()
	for i := 0; i < res.Len(); i++ {
		t := res.At(i).Type()
		if _, ok := t.Underlying().(*types.Pointer); ok {
			continue
		}
		b, ok := t.Underlying().(*types.Basic)
		if !ok || (b.Info()&types.IsInteger == 0 && b.Kind() != types.Bool) {
			return false
		}
	}
	return true
}

// directImportID admits an imported call only when it is summarizable:
// every result must be scalar (integer/boolean), at any arity. Composite
// results stay `external_or_bodyless` — a `range` over a composite would
// break the fragment's integer-only range model. A multi-valued callee
// declares its arity on the call record so the consumer can admit the
// tuple unpacking `a, b := lib.F(x)`.
func (ix *indexer) directImportID(f *types.Func) (string, int, bool) {
	id := ix.importedID(f)
	if id == "" {
		return "", 0, false
	}
	sig, ok := f.Type().(*types.Signature)
	if !ok || !allScalarResults(sig) {
		return "", 0, false
	}
	// A generic callee must go through the instantiation gate — the
	// *declared* signature admits what the *inferred* call would
	// reject: `func G[P any](v P) *P` records `*P` as a pointer result
	// here while `lib.G(t)` infers a named type argument no pin covers.
	if tp := sig.TypeParams(); tp != nil && tp.Len() > 0 {
		return "", 0, false
	}
	return id, sig.Results().Len(), true
}

// directImportMethodID admits an imported method call `recv.M(...)` only
// when the method is declared in a resolved imported unit on a concrete
// named receiver type and every result is scalar. The dependency model
// is the same opaque `direct_import` shape — each result may depend on
// the receiver and every argument; the consumer evaluates the receiver
// expression for a `method` call. Interface receivers stay
// `method_generic_or_variadic`: dispatch there is dynamic, and the
// pinned method identity would not cover the implementations actually
// reached.
func (ix *indexer) directImportMethodID(f *types.Func, recv types.Type) (string, int, []string, bool) {
	id := ix.importedID(f)
	if id == "" {
		return "", 0, nil, false
	}
	sig, ok := f.Type().(*types.Signature)
	if !ok || sig.Recv() == nil || !allScalarResults(sig) {
		return "", 0, nil, false
	}
	rt := types.Unalias(recv)
	if ptr, ok := rt.(*types.Pointer); ok {
		rt = types.Unalias(ptr.Elem())
	}
	named, ok := rt.(*types.Named)
	if !ok {
		return "", 0, nil, false
	}
	if _, ok := named.Underlying().(*types.Interface); ok {
		return "", 0, nil, false
	}
	// A receiver still declared on type parameters (`T[P]` — `TypeParams`
	// is non-nil and `TypeArgs` empty) names types the member records
	// cannot pin, so it stays closed. An instantiated receiver
	// (`lib.GT[lib.T]` — `TypeArgs` non-empty, `TypeParams` still lists
	// the origin's parameters) admits like a concrete one when every
	// type argument is basic, named or alias; the collected identities
	// ride on the record as `type_arg_type_ids` so a type-argument
	// redeclare stales every caller that pins them.
	targs := named.TypeArgs()
	if targs == nil || targs.Len() == 0 {
		if tp := named.TypeParams(); tp != nil && tp.Len() > 0 {
			return "", 0, nil, false
		}
		return id, sig.Results().Len(), nil, true
	}
	var ids []string
	seen := map[string]bool{}
	for i := 0; i < targs.Len(); i++ {
		if !ix.collectTypeArgIDs(targs.At(i), seen, &ids) {
			return "", 0, nil, false
		}
	}
	return id, sig.Results().Len(), ids, true
}

// directImportInstantiation admits an explicit instantiation of an imported
// generic function `lib.G[int64](...)` when every type argument is basic,
// named or alias, every instantiated parameter is basic-underlying, and
// every instantiated result is scalar — arity rides on the record like any
// other `direct_import`. A named/alias type argument's identity rides on
// the record as `type_arg_type_ids` — substituted type-parameter
// identities are declared nowhere, so the member record's signature pins
// could never cover them; a *declared* named parameter type
// (`func G[T any](v T2)`) is already pinned by `signature_type_ids`, while a
// composite instantiated parameter (`[]T`) is outside the scalar fragment
// anyway. The dependency model is the same opaque `direct_import` shape —
// the result depends on every evaluated argument. Inferred calls `lib.G(x)`
// reach the same gate through `importedInstantiationID`, which looks up
// `info.Instances` for inferred and explicit instantiations alike.
func (ix *indexer) directImportInstantiation(x ast.Expr) (string, int, []string, bool) {
	sel, ok := unparen(x).(*ast.SelectorExpr)
	if !ok {
		return "", 0, nil, false
	}
	pkg, ok := sel.X.(*ast.Ident)
	if !ok {
		return "", 0, nil, false
	}
	if _, isPkg := ix.info.Uses[pkg].(*types.PkgName); !isPkg {
		return "", 0, nil, false
	}
	f, ok := ix.info.Uses[sel.Sel].(*types.Func)
	if !ok {
		return "", 0, nil, false
	}
	return ix.importedInstantiationID(f, sel.Sel)
}

// importedInstantiationID admits an instantiated generic function call
// when every type argument is basic, named or alias, every instantiated
// parameter is basic-underlying (one `*T` layer unwraps, matching the
// declared-signature pointer rule), and every instantiated result is
// scalar — the same rule `directImportInstantiation` applies to
// `lib.G[int64](...)`. It covers *inferred* instantiations
// `lib.G(x)`/`G(x)` too: `info.Instances` records the inferred type
// arguments either way, so `lib.G(t)` with `t` declared `lib.T` behaves
// exactly like an explicit `lib.G[lib.T](x)`. It is used for
// unqualified (dot-imported or plain) instantiation callees too:
// checking the *declared* signature there would let a named type
// argument through with no pin covering its identity. The result arity
// is returned alongside so a multi-valued instantiation declares it
// like any `direct_import` callee. A named/alias type argument's
// identity travels on the call record as `type_arg_type_ids` so the
// consumer pins the substituted type exactly like a declared named
// signature type; a type argument with no declared identity (`error`,
// `any`) needs no pin and contributes nothing.
func (ix *indexer) importedInstantiationID(f *types.Func, ident *ast.Ident) (string, int, []string, bool) {
	inst, ok := ix.info.Instances[ident]
	if !ok {
		return "", 0, nil, false
	}
	var typeArgIDs []string
	seenArg := map[string]bool{}
	for i := 0; i < inst.TypeArgs.Len(); i++ {
		if !ix.collectTypeArgIDs(inst.TypeArgs.At(i), seenArg, &typeArgIDs) {
			return "", 0, nil, false
		}
	}
	isig, ok := inst.Type.(*types.Signature)
	if !ok {
		return "", 0, nil, false
	}
	for i := 0; i < isig.Params().Len(); i++ {
		pt := isig.Params().At(i).Type()
		// `*T` names its pointee as surely as a declared `*lib.T`
		// signature type does — the pointee's identity rides on
		// `type_arg_type_ids` (substituted) or `signature_type_ids`
		// (declared), so one pointer layer unwraps here too.
		if ptr, ok := pt.(*types.Pointer); ok {
			pt = ptr.Elem()
		}
		if _, ok := pt.Underlying().(*types.Basic); !ok {
			return "", 0, nil, false
		}
	}
	if !allScalarResults(isig) {
		return "", 0, nil, false
	}
	id := ix.importedID(f)
	if id == "" {
		return "", 0, nil, false
	}
	return id, isig.Results().Len(), typeArgIDs, true
}

// collectTypeArgIDs admits a type argument built only from basic, named
// and alias types — at any depth of a named/alias type's own argument
// list or inside a pointer, slice, array, map or channel constructor —
// and records every named/alias identity it contains so the call
// record pins each substituted type. `lib.N[other.U]` pins both N and U;
// `*lib.T` and `[]lib.T` pin T; a redeclaration of either must stale
// the call site. A signature, struct, interface or type-parameter
// argument has no pinnable identity, so a type argument containing one
// stays closed.
func (ix *indexer) collectTypeArgIDs(t types.Type, seen map[string]bool, ids *[]string) bool {
	var obj *types.TypeName
	var inner *types.TypeList
	switch tt := t.(type) {
	case *types.Basic:
		// Basic arguments are declared nowhere — nothing to pin.
		return true
	case *types.Named:
		obj = tt.Obj()
		inner = tt.TypeArgs()
	case *types.Alias:
		obj = tt.Obj()
		inner = tt.TypeArgs()
	case *types.Pointer:
		return ix.collectTypeArgIDs(tt.Elem(), seen, ids)
	case *types.Slice:
		return ix.collectTypeArgIDs(tt.Elem(), seen, ids)
	case *types.Array:
		return ix.collectTypeArgIDs(tt.Elem(), seen, ids)
	case *types.Map:
		return ix.collectTypeArgIDs(tt.Key(), seen, ids) &&
			ix.collectTypeArgIDs(tt.Elem(), seen, ids)
	case *types.Chan:
		return ix.collectTypeArgIDs(tt.Elem(), seen, ids)
	default:
		return false
	}
	if obj != nil {
		id := ix.typeID(obj)
		if id == "" {
			// A universe type (`error`, `any`) is declared nowhere and
			// needs no pin — but a packaged named type from a unit the
			// host never declared could not be pinned either, so the
			// call must stay closed rather than admit unpinned.
			if obj.Pkg() != nil {
				return false
			}
		} else if !seen[id] {
			seen[id] = true
			*ids = append(*ids, id)
		}
	}
	if inner != nil {
		for i := 0; i < inner.Len(); i++ {
			if !ix.collectTypeArgIDs(inner.At(i), seen, ids) {
				return false
			}
		}
	}
	return true
}

// Import implements types.Importer against the host-declared import map.
// Resolution is recursive: a declared unit may itself import other declared
// paths, and a cycle simply fails resolution.
func (ix *indexer) Import(path string) (*types.Package, error) {
	if p, ok := ix.importCache[path]; ok {
		return p, nil
	}
	if ix.importInFlight[path] {
		return nil, errUnresolvedImport
	}
	srcs, ok := ix.importDecls[path]
	if !ok {
		return nil, errUnresolvedImport
	}
	ix.importInFlight[path] = true
	defer delete(ix.importInFlight, path)
	rec := &importUnit{files: make(map[*token.File]int)}
	var asts []*ast.File
	for i, s := range srcs {
		d := sha256.Sum256([]byte(s.Source))
		rec.digests = append(rec.digests, fmt.Sprintf("%x", d[:]))
		f, err := parser.ParseFile(ix.fset, s.Name, s.Source, parser.ParseComments)
		if err != nil {
			return nil, errUnresolvedImport
		}
		// Imported sources follow the same no-directive contract as the
		// root unit: the analysis has no build configuration, so
		// `//go:`, `// +build` and `//line` markers cannot be honoured.
		for _, group := range f.Comments {
			for _, comment := range group.List {
				text := strings.TrimSpace(strings.TrimPrefix(comment.Text, "//"))
				if strings.HasPrefix(text, "go:") || strings.HasPrefix(text, "+build") ||
					strings.HasPrefix(text, "line ") || strings.HasPrefix(text, "/*line ") {
					return nil, errUnresolvedImport
				}
			}
		}
		rec.files[ix.fset.File(f.Pos())] = i
		asts = append(asts, f)
	}
	conf := types.Config{GoVersion: languageVersion, Sizes: ix.sizes, Importer: ix}
	pkg, err := conf.Check(path, ix.fset, asts, nil)
	if err != nil {
		return nil, errUnresolvedImport
	}
	rec.pkg = pkg
	ix.importUnits[pkg] = rec
	ix.importCache[path] = pkg
	return pkg, nil
}

// importedID reproduces the identity the imported unit's own report assigns
// to obj: sha256:{declaring-file-digest}:{file}:{pos}:{scope_start}:{scope_end}
// in that unit's file order. A caller's `direct_import` target therefore
// matches the callee's own binding identity — staleness propagates across
// package boundaries. Identities are content-addressed within a unit's file
// order: two declared packages with identical file contents produce identical
// identities, so a host tracking freshness per path must not rely on identity
// membership alone.
func (ix *indexer) importedID(obj types.Object) string {
	rec := ix.importUnits[obj.Pkg()]
	if rec == nil || !obj.Pos().IsValid() || obj.Name() == "" || obj.Name() == "_" {
		return ""
	}
	f, ok := rec.files[ix.fset.File(obj.Pos())]
	if !ok {
		return ""
	}
	start, end := -1, -1
	if sc := obj.Parent(); sc == rec.pkg.Scope() {
		// Package scope is the unit-wide sentinel, as in `scope`.
		start, end = 0, 0
	} else if sc != nil && sc.Pos().IsValid() {
		start, end = ix.offset(sc.Pos()), ix.offset(sc.End())
	}
	return fmt.Sprintf("sha256:%s:%d:%d:%d:%d",
		rec.digests[f], f, ix.offset(obj.Pos()), start, end)
}

// typeID names a named type's identity: the unit's own binding identity
// for local declarations, the imported unit's own identity for an
// object the unit only references — the same `importedID` a `direct_import`
// call target carries, so a member's declared type pins the imported
// type declaration for staleness. Basic and unnamed types keep no
// identity.
func (ix *indexer) typeID(obj types.Object) string {
	if id := ix.id(obj); id != "" {
		return id
	}
	return ix.importedID(obj)
}

// recordMember declares a referenced imported object: its identity, the
// member kind a consumer needs to classify uses, and its type. Objects the
// unit never names are not declared.
func (ix *indexer) recordMember(obj types.Object, id string) {
	if _, ok := ix.importMembers[id]; ok {
		return
	}
	var kind string
	switch obj.(type) {
	case *types.Func:
		kind = "function"
	case *types.Const:
		kind = "const"
	case *types.Var:
		kind = "var"
	case *types.TypeName:
		kind = "type"
	default:
		return
	}
	m := member{
		ID: id, Name: obj.Name(), Kind: kind, Type: ix.typeOf(obj.Type()),
	}
	if kind == "function" {
		if sig, ok := obj.Type().(*types.Signature); ok {
			m.SignatureTypeIDs = ix.signatureTypeIDs(sig)
		}
	}
	ix.importMembers[id] = m
	if kind == "var" {
		// A pointer-typed var's pointee identity must be declared too:
		// the consumer needs the pointee's own fact to classify a
		// `*lib.V` dereference read, exactly like a signature's
		// `signature_type_ids` declaring the types a contract names.
		if ptr, ok := obj.Type().(*types.Pointer); ok {
			var elem *types.TypeName
			switch e := ptr.Elem().(type) {
			case *types.Named:
				elem = e.Obj()
			case *types.Alias:
				elem = e.Obj()
			}
			if elem != nil {
				// Universe objects (`*error` vars) and anything the
				// imported unit cannot name carry no identity — only
				// an emitted id may be recorded, since the loader
				// rejects a member whose id is empty.
				if eid := ix.typeID(elem); eid != "" {
					ix.recordMember(elem, eid)
				}
			}
			// Deeper pointees (`**T`, `*[]*T`) still name identities a
			// dereference store needs pinned — collect them like type
			// arguments do; a fully unnamed pointee (`*int64`) resolves
			// to the empty list, which the member's own identity then
			// covers completely.
			var pointeeIDs []string
			if ix.collectTypeArgIDs(ptr.Elem(), map[string]bool{}, &pointeeIDs) {
				if pointeeIDs == nil {
					pointeeIDs = []string{}
				}
				m.PointeeTypeIDs = &pointeeIDs
				// `m` was stored by value above — put the updated
				// record back so the key actually serializes.
				ix.importMembers[id] = m
				// The ids collect without declaring their member
				// records — a `*chan T` or `*[]T` pointee names `T`
				// through the list alone, and a pinned id with no
				// member record flags `stale_dependents` forever.
				// Declare each like a direct pointee does.
				ix.recordPointeeMembers(ptr.Elem(), map[string]bool{})
			}
		}
	}
}

// recordPointeeMembers declares every named/alias object a resolved
// pointee tree mentions: `pointee_type_ids` pins those identities, and
// a pin only detects a redeclaration when the member record exists.
func (ix *indexer) recordPointeeMembers(t types.Type, seen map[string]bool) {
	switch tt := t.(type) {
	case *types.Named:
		if id := ix.typeID(tt.Obj()); id != "" && !seen[id] {
			seen[id] = true
			ix.recordMember(tt.Obj(), id)
		}
		for i := 0; i < tt.TypeArgs().Len(); i++ {
			ix.recordPointeeMembers(tt.TypeArgs().At(i), seen)
		}
	case *types.Alias:
		if id := ix.typeID(tt.Obj()); id != "" && !seen[id] {
			seen[id] = true
			ix.recordMember(tt.Obj(), id)
		}
		for i := 0; i < tt.TypeArgs().Len(); i++ {
			ix.recordPointeeMembers(tt.TypeArgs().At(i), seen)
		}
	case *types.Pointer:
		ix.recordPointeeMembers(tt.Elem(), seen)
	case *types.Slice:
		ix.recordPointeeMembers(tt.Elem(), seen)
	case *types.Array:
		ix.recordPointeeMembers(tt.Elem(), seen)
	case *types.Map:
		ix.recordPointeeMembers(tt.Key(), seen)
		ix.recordPointeeMembers(tt.Elem(), seen)
	case *types.Chan:
		ix.recordPointeeMembers(tt.Elem(), seen)
	}
}

// signatureTypeIDs lists the named/alias type identities a signature's
// parameters and results mention, in the coordinate space of the unit
// declaring each type — so a caller pinning a resolved call also pins
// the types its contract names. Basic and unnamed types contribute
// nothing. For a method, the receiver's own named type is included too:
// an admitted `recv.M(args)` depends on that type as surely as on a
// parameter, and a receiver that is a plain local variable carries no
// member read that would pin it otherwise.
func (ix *indexer) signatureTypeIDs(sig *types.Signature) []string {
	seen := map[string]bool{}
	var ids []string
	add := func(t types.Type) {
		// `*lib.T` names `lib.T` as surely as the pointee's own
		// declaration does — a pointer-typed parameter or result must
		// pin the same identity.
		if ptr, ok := t.(*types.Pointer); ok {
			t = ptr.Elem()
		}
		var obj *types.TypeName
		switch typ := t.(type) {
		case *types.Named:
			obj = typ.Obj()
		case *types.Alias:
			obj = typ.Obj()
		case *types.TypeParam:
			obj = typ.Obj()
		}
		if obj == nil {
			return
		}
		if id := ix.typeID(obj); id != "" && !seen[id] {
			seen[id] = true
			ids = append(ids, id)
		}
	}
	if sig.Recv() != nil {
		// `add` does the one-layer unwrap itself, so a `**T` receiver
		// pins nothing — the same rule parameters follow.
		add(sig.Recv().Type())
	}
	for i := 0; i < sig.Params().Len(); i++ {
		add(sig.Params().At(i).Type())
	}
	for i := 0; i < sig.Results().Len(); i++ {
		add(sig.Results().At(i).Type())
	}
	sort.Strings(ids)
	return ids
}

func unitDigest(sources []namedSource) string {
	h := sha256.New()
	for _, s := range sources {
		d := sha256.Sum256([]byte(s.Source))
		h.Write([]byte(s.Name))
		h.Write([]byte{0})
		h.Write(d[:])
	}
	return fmt.Sprintf("%x", h.Sum(nil))
}

func base(req request) snapshot {
	digest := fmt.Sprintf("%x", sha256.Sum256([]byte(req.Source)))
	prof := profile
	var files []fileDigest
	if len(req.Sources) > 0 {
		prof, digest = packageProfile, unitDigest(req.Sources)
		files = make([]fileDigest, len(req.Sources))
		for i, s := range req.Sources {
			files[i] = fileDigest{s.Name, fmt.Sprintf("%x", sha256.Sum256([]byte(s.Source)))}
		}
	}
	return snapshot{
		Profile: prof, SourceSHA256: digest, Files: files,
		TargetArch: req.TargetArch, LanguageVersion: languageVersion, CompilerVersion: runtime.Version(),
		Status: "invalid_request", Bindings: []binding{}, References: []reference{},
		Functions: []function{}, Calls: []call{}, Gaps: []gap{},
	}
}

func (ix *indexer) offset(p token.Pos) int { return ix.fset.PositionFor(p, false).Offset }

func (ix *indexer) fileOf(p token.Pos) int {
	return ix.files[ix.fset.File(p)]
}

func (ix *indexer) pos(p token.Pos) (int, int) {
	return ix.fileOf(p), ix.offset(p)
}

func (ix *indexer) spanOf(a, b token.Pos) span {
	fa, oa := ix.pos(a)
	_, ob := ix.pos(b)
	if ix.packaged {
		return fileSpan(fa, oa, ob)
	}
	return span{Start: oa, End: ob}
}

func (ix *indexer) nodeSpan(n ast.Node) span { return ix.spanOf(n.Pos(), n.End()) }

func (ix *indexer) scope(obj types.Object) *span {
	sc := obj.Parent()
	if sc == nil {
		return nil
	}
	if sc == ix.pkg.Scope() {
		if ix.packaged {
			// The unit scope covers every file — a sentinel, not a span.
			s := fileSpan(-1, 0, 0)
			return &s
		}
		return &span{Start: 0, End: len(ix.source)}
	}
	s := ix.spanOf(sc.Pos(), sc.End())
	return &s
}

// digestOf returns the digest anchoring a declaration: the whole source in
// the single-file profile, or the declaring file's bytes in the package
// profile — so an untouched file keeps its binding identities stable.
func (ix *indexer) digestOf(file int) string {
	if ix.packaged && file >= 0 {
		return ix.digests[file]
	}
	return ix.out.SourceSHA256
}

func (ix *indexer) id(obj types.Object) string {
	if obj == nil || obj.Pkg() != ix.pkg || !obj.Pos().IsValid() || obj.Name() == "" || obj.Name() == "_" {
		return ""
	}
	start, end := -1, -1
	if sc := ix.scope(obj); sc != nil {
		start, end = sc.Start, sc.End
	}
	declFile := ix.fileOf(obj.Pos())
	// Type-switch case bindings can share a declaration position, not a scope.
	if ix.packaged {
		return fmt.Sprintf("sha256:%s:%d:%d:%d:%d",
			ix.digestOf(declFile), declFile, ix.offset(obj.Pos()), start, end)
	}
	return fmt.Sprintf("sha256:%s:%d:%d:%d",
		ix.out.SourceSHA256, ix.offset(obj.Pos()), start, end)
}

func (ix *indexer) typeOf(t types.Type) typeFact {
	return ix.typeOfRec(t, map[types.Type]bool{})
}

func (ix *indexer) typeOfRec(t types.Type, seen map[types.Type]bool) typeFact {
	f := typeFact{Kind: "unsupported"}
	if t == nil {
		return f
	}
	switch typ := t.(type) {
	case *types.Named:
		f.TypeID = ix.typeID(typ.Obj())
	case *types.Alias:
		f.TypeID = ix.typeID(typ.Obj())
	case *types.TypeParam:
		f.TypeID = ix.typeID(typ.Obj())
	case *types.Pointer:
		// A pointer's own identity is the pointee's named type — the
		// pointer itself names nothing pinnable. The pointee may be
		// anything (basic, composite, named); only a named/alias
		// pointee contributes an identity a pin can cover.
		f.Kind = "pointer"
		switch e := typ.Elem().(type) {
		case *types.Named:
			f.TypeID = ix.typeID(e.Obj())
		case *types.Alias:
			f.TypeID = ix.typeID(e.Obj())
		}
		return f
	}
	// A named container type can name itself — `type R []R` is valid
	// Go — so a type already being expanded stops at its identity:
	// the element fact reads `unsupported`, which keeps index reads
	// of it closed like every unmodelled element.
	if seen[t] {
		return f
	}
	seen[t] = true
	defer delete(seen, t)
	if s, ok := t.Underlying().(*types.Slice); ok {
		// `[]T` — or a named/alias type whose underlying is a slice,
		// which keeps the identity the switch above already set.
		f.Kind = "slice"
		e := ix.typeOfRec(s.Elem(), seen)
		f.Elem = &e
		return f
	}
	if a, ok := t.Underlying().(*types.Array); ok {
		f.Kind = "array"
		e := ix.typeOfRec(a.Elem(), seen)
		f.Elem = &e
		return f
	}
	if m, ok := t.Underlying().(*types.Map); ok {
		// `map[K]V` — or a named/alias type whose underlying is one. The
		// key and value facts let an index read classify what it looks
		// up and what it returns, and carry any named identities a pin
		// needs to cover.
		f.Kind = "map"
		k := ix.typeOfRec(m.Key(), seen)
		e := ix.typeOfRec(m.Elem(), seen)
		f.Key = &k
		f.Elem = &e
		return f
	}
	if _, ok := t.Underlying().(*types.Signature); ok {
		f.Kind = "function"
		return f
	}
	b, ok := t.Underlying().(*types.Basic)
	if !ok {
		return f
	}
	f.BasicName = b.Name()
	if b.Info()&types.IsUntyped != 0 {
		f.Kind = "untyped"
	} else if b.Info()&types.IsInteger != 0 {
		f.Kind = "integer"
		f.BitWidth = int(ix.sizes.Sizeof(b)) * 8
		signed := b.Info()&types.IsUnsigned == 0
		f.Signed = &signed
	} else if b.Kind() == types.Bool {
		f.Kind = "boolean"
		// Logical width, not a Go memory-layout or ABI claim.
		f.BitWidth = 1
	}
	return f
}

func (ix *indexer) parameters(tuple *types.Tuple) []parameter {
	out := []parameter{}
	for v := range tuple.Variables() {
		out = append(out, parameter{ix.id(v), ix.typeOf(v.Type())})
	}
	return out
}

func (ix *indexer) addBinding(obj types.Object, seen map[string]bool) {
	// Package-name bindings are namespace qualifiers, not values — uses of
	// the imported member carry an `import` reference instead.
	if _, ok := obj.(*types.PkgName); ok {
		return
	}
	id := ix.id(obj)
	if id == "" || seen[id] {
		return
	}
	seen[id] = true
	kind := "variable"
	switch obj.(type) {
	case *types.Func:
		kind = "function"
	case *types.TypeName:
		kind = "type"
	case *types.Const:
		kind = "constant"
	case *types.Label:
		kind = "label"
	}
	start := ix.offset(obj.Pos())
	tf := ix.typeOf(obj.Type())
	sp := span{Start: start, End: start + len(obj.Name())}
	if ix.packaged {
		f := ix.fileOf(obj.Pos())
		sp = fileSpan(f, start, start+len(obj.Name()))
	}
	ix.out.Bindings = append(ix.out.Bindings, binding{
		id, obj.Name(), kind, sp, ix.scope(obj), tf,
	})
	if tf.Kind == "unsupported" || tf.Kind == "untyped" || tf.Kind == "slice" || tf.Kind == "array" || tf.Kind == "map" || tf.Kind == "function" && kind != "function" {
		ix.out.Gaps = append(ix.out.Gaps, gap{"unsupported_value_semantics", &sp})
	}
}

func unparen(e ast.Expr) ast.Expr {
	for {
		p, ok := e.(*ast.ParenExpr)
		if !ok {
			return e
		}
		e = p.X
	}
}

func (ix *indexer) classify(c *ast.CallExpr, functions map[string]function) (string, string, bool, int, []string) {
	if ix.info.Types[c.Fun].IsType() {
		return "conversion", "", false, 0, nil
	}
	fun := unparen(c.Fun)
	var instIdent *ast.Ident
	switch e := fun.(type) {
	case *ast.IndexExpr:
		if id, arity, ids, ok := ix.directImportInstantiation(e.X); ok {
			return "direct_import", id, false, arity, ids
		}
		// An unqualified instantiation (`G[T](x)`, dot-imported or plain)
		// still needs the instantiation-aware check below — the declared
		// signature's basic-type-argument gate must not see a named type
		// argument before its `type_arg_type_ids` pin is recorded.
		if i, ok := unparen(e.X).(*ast.Ident); ok {
			instIdent = i
		}
		fun = unparen(e.X)
	case *ast.IndexListExpr:
		if id, arity, ids, ok := ix.directImportInstantiation(e.X); ok {
			return "direct_import", id, false, arity, ids
		}
		if i, ok := unparen(e.X).(*ast.Ident); ok {
			instIdent = i
		}
		fun = unparen(e.X)
	case *ast.SelectorExpr:
		if selection := ix.info.Selections[e]; selection != nil && selection.Kind() != types.FieldVal {
			// `recv.M(args)`: admit a concrete-receiver method declared
			// in a resolved imported unit as a `direct_import` marked
			// `method`, so the consumer evaluates the receiver too.
			// A method expression `T.M` takes the same gate — its
			// receiver is already the leading argument, so the plain
			// `direct_import` shape needs no flag.
			if selection.Kind() == types.MethodVal || selection.Kind() == types.MethodExpr {
				// A promoted selection (`s.GM` through `struct{ GT[T] }`,
				// or an embedded interface's method) has an Index path
				// longer than one: the static receiver is the outer type,
				// so the embedded instantiation's type arguments — or the
				// dynamic dispatch itself — escape the gate. Both stay
				// closed.
				if f, ok := selection.Obj().(*types.Func); ok && len(selection.Index()) == 1 {
					if id, arity, ids, ok := ix.directImportMethodID(f, selection.Recv()); ok {
						// `lib.T.M(recv, args)` — a method expression:
						// the receiver is already the leading argument,
						// so the plain `direct_import` result-depends-
						// on-every-argument model covers it; no `method`
						// flag is needed.
						return "direct_import", id, selection.Kind() == types.MethodVal, arity, ids
					}
				}
			}
			return "method_generic_or_variadic", "", false, 0, nil
		}
		// A package-qualified call `lib.G(...)`: the callee is declared in
		// a resolved imported unit. The target is that unit's own binding
		// identity; the body stays opaque to the summarizer.
		if x, ok := e.X.(*ast.Ident); ok {
			if _, isPkg := ix.info.Uses[x].(*types.PkgName); isPkg {
				if f, ok := ix.info.Uses[e.Sel].(*types.Func); ok {
					if id, arity, ok := ix.directImportID(f); ok {
						return "direct_import", id, false, arity, nil
					}
					// `lib.G(x)` — an inferred instantiation. The
					// declared signature fails the scalar-parameter
					// rule, so admit through the instantiation gate,
					// which also records each named type argument's pin.
					if id, arity, ids, ok := ix.importedInstantiationID(f, e.Sel); ok {
						return "direct_import", id, false, arity, ids
					}
					return "external_or_bodyless", "", false, 0, nil
				}
				return "indirect_or_selector", "", false, 0, nil
			}
		}
	}
	ident, ok := fun.(*ast.Ident)
	if !ok {
		return "indirect_or_selector", "", false, 0, nil
	}
	obj := ix.info.Uses[ident]
	if _, ok := obj.(*types.Builtin); ok {
		return "builtin", "", false, 0, nil
	}
	f, ok := obj.(*types.Func)
	if !ok {
		return "indirect_or_selector", "", false, 0, nil
	}
	fn, ok := functions[ix.id(f)]
	if !ok || fn.Body == nil {
		if instIdent != nil {
			if id, arity, ids, ok := ix.importedInstantiationID(f, instIdent); ok {
				return "direct_import", id, false, arity, ids
			}
			return "external_or_bodyless", "", false, 0, nil
		}
		// A dot-imported inferred instantiation `G(x)` reaches the
		// same gate as `lib.G(x)` — the callee ident keys
		// `info.Instances`.
		if id, arity, ids, ok := ix.importedInstantiationID(f, ident); ok {
			return "direct_import", id, false, arity, ids
		}
		// Dot-imported names reach here: the func is not local but its
		// imported identity is still stable and reportable.
		if id, arity, ok := ix.directImportID(f); ok {
			return "direct_import", id, false, arity, nil
		}
		return "external_or_bodyless", "", false, 0, nil
	}
	if fn.Method || fn.Generic || fn.Variadic {
		return "method_generic_or_variadic", "", false, 0, nil
	}
	return "direct_local", fn.BindingID, false, 0, nil
}

func spanFile(s *span) int {
	if s != nil && s.File != nil {
		return *s.File
	}
	return -2
}

func spanLess(a, b span) bool {
	fa, fb := spanFile(&a), spanFile(&b)
	if fa != fb {
		return fa < fb
	}
	if a.Start != b.Start {
		return a.Start < b.Start
	}
	return a.End < b.End
}

func analyze(req request) (out snapshot) {
	out = base(req)
	defer func() {
		if recover() != nil {
			out = base(req)
			out.Status = "internal_error"
			out.Gaps = append(out.Gaps, gap{"internal_error", nil})
		}
	}()
	packaged := len(req.Sources) > 0
	// `imports` only applies to package units: it declares the source sets
	// an import path may resolve to. The single-file profile stays closed.
	if packaged == (req.Source != "") || (!packaged && len(req.Imports) > 0) {
		out.Gaps = append(out.Gaps, gap{"invalid_request", nil})
		return out
	}
	unit := req.Sources
	if !packaged {
		unit = []namedSource{{"source.go", req.Source}}
	}
	if len(unit) > maxFiles {
		out.Gaps = append(out.Gaps, gap{"source_limit_or_encoding", nil})
		return out
	}
	validateUnit := func(sources []namedSource) bool {
		if len(sources) == 0 || len(sources) > maxFiles {
			return false
		}
		seen := make(map[string]bool)
		for _, s := range sources {
			if s.Name == "" || seen[s.Name] || len(s.Source) > maxSource || !utf8.ValidString(s.Source) {
				return false
			}
			seen[s.Name] = true
		}
		return true
	}
	if !validateUnit(unit) {
		out.Gaps = append(out.Gaps, gap{"source_limit_or_encoding", nil})
		return out
	}
	importDecls := make(map[string][]namedSource, len(req.Imports))
	if len(req.Imports) > maxImports {
		out.Gaps = append(out.Gaps, gap{"invalid_request", nil})
		return out
	}
	for _, imp := range req.Imports {
		if imp.Path == "" || importDecls[imp.Path] != nil || !validateUnit(imp.Sources) {
			out.Gaps = append(out.Gaps, gap{"invalid_request", nil})
			return out
		}
		importDecls[imp.Path] = imp.Sources
	}
	switch req.TargetArch {
	case "amd64", "386", "arm64":
	default:
		out.Gaps = append(out.Gaps, gap{"unsupported_target", nil})
		return out
	}
	fset := token.NewFileSet()
	ix := indexer{
		source: req.Source, sources: unit, fset: fset, packaged: packaged,
		out: &out, sizes: types.SizesFor("gc", req.TargetArch),
		files:          make(map[*token.File]int),
		importDecls:    importDecls,
		importCache:    make(map[string]*types.Package),
		importInFlight: make(map[string]bool),
		importUnits:    make(map[*types.Package]*importUnit),
		importMembers:  make(map[string]member),
	}
	for _, s := range unit {
		ix.digests = append(ix.digests, fmt.Sprintf("%x", sha256.Sum256([]byte(s.Source))))
	}
	var astFiles []*ast.File
	for i, s := range unit {
		file, err := parser.ParseFile(fset, s.Name, s.Source, parser.ParseComments|parser.AllErrors)
		if err != nil {
			out.Status = "parse_error"
			var sp *span
			if packaged {
				p := fileSpan(i, 0, 0)
				sp = &p
			}
			out.Gaps = append(out.Gaps, gap{"parse_error", sp})
			return out
		}
		ix.files[fset.File(file.Pos())] = i
		astFiles = append(astFiles, file)
	}
	for _, file := range astFiles {
		for _, imp := range file.Imports {
			// Imports resolve only through the declared map — there is no
			// disk, network or stdlib importer.
			path, err := strconv.Unquote(imp.Path.Value)
			if err != nil {
				path = ""
			}
			if _, err := ix.Import(path); err != nil {
				sp := ix.nodeSpan(imp)
				out.Gaps = append(out.Gaps, gap{"unresolved_import", &sp})
			}
		}
		for _, group := range file.Comments {
			for _, comment := range group.List {
				text := strings.TrimSpace(strings.TrimPrefix(comment.Text, "//"))
				if strings.HasPrefix(text, "go:") || strings.HasPrefix(text, "+build") ||
					strings.HasPrefix(text, "line ") || strings.HasPrefix(text, "/*line ") {
					sp := ix.nodeSpan(comment)
					out.Gaps = append(out.Gaps, gap{"source_directive_not_supported", &sp})
				}
			}
		}
	}
	if len(out.Gaps) != 0 {
		out.Status = "unsupported"
		return out
	}
	info := &types.Info{
		Defs: make(map[*ast.Ident]types.Object), Uses: make(map[*ast.Ident]types.Object),
		Implicits: make(map[ast.Node]types.Object), Types: make(map[ast.Expr]types.TypeAndValue),
		Selections: make(map[*ast.SelectorExpr]*types.Selection),
		Instances:  make(map[*ast.Ident]types.Instance),
	}
	conf := types.Config{GoVersion: languageVersion, Sizes: ix.sizes, Importer: &ix, Error: func(e error) {
		if len(out.Gaps) < 16 {
			var sp *span
			if te, ok := e.(types.Error); ok && te.Pos.IsValid() {
				s := ix.spanOf(te.Pos, te.Pos)
				sp = &s
			}
			out.Gaps = append(out.Gaps, gap{"type_error", sp})
		}
	}}
	pkg, err := conf.Check("mumei.local/singlefile", fset, astFiles, info)
	if err != nil {
		out.Status = "type_error"
		return out
	}
	ix.pkg, ix.info = pkg, info
	seen := make(map[string]bool)
	for _, obj := range info.Defs {
		ix.addBinding(obj, seen)
	}
	for _, obj := range info.Implicits {
		ix.addBinding(obj, seen)
	}
	for ident, obj := range info.Uses {
		if _, ok := obj.(*types.PkgName); ok {
			continue
		}
		id, kind := ix.id(obj), "local"
		if id == "" {
			if iid := ix.importedID(obj); iid != "" {
				id, kind = iid, "import"
				ix.recordMember(obj, iid)
			} else {
				kind = "universe"
			}
		}
		out.References = append(out.References, reference{ix.nodeSpan(ident), id, kind})
	}
	functions := make(map[string]function)
	for _, file := range astFiles {
		for _, decl := range file.Decls {
			fd, ok := decl.(*ast.FuncDecl)
			if !ok {
				continue
			}
			obj := info.Defs[fd.Name].(*types.Func)
			if ix.id(obj) == "" {
				sp := ix.nodeSpan(fd.Name)
				out.Gaps = append(out.Gaps, gap{"blank_function_not_indexed", &sp})
				continue
			}
			sig := obj.Signature()
			fn := function{
				BindingID: ix.id(obj), Parameters: ix.parameters(sig.Params()), Results: ix.parameters(sig.Results()),
				Method: sig.Recv() != nil, Generic: sig.TypeParams().Len() != 0 || sig.RecvTypeParams().Len() != 0,
				Variadic: sig.Variadic(),
			}
			if fd.Body != nil {
				body := ix.spanOf(fd.Body.Lbrace+1, fd.Body.Rbrace)
				fn.Body = &body
			}
			functions[fn.BindingID] = fn
			out.Functions = append(out.Functions, fn)
		}
	}
	owners := []string{}
	special := make(map[*ast.CallExpr]string)
	for _, file := range astFiles {
		ast.Inspect(file, func(n ast.Node) bool {
			if n == nil {
				owners = owners[:len(owners)-1]
				return true
			}
			owner := ""
			if len(owners) > 0 {
				owner = owners[len(owners)-1]
			}
			switch node := n.(type) {
			case *ast.FuncDecl:
				owner = ix.id(info.Defs[node.Name])
			case *ast.FuncLit:
				owner = ""
				sp := ix.nodeSpan(node)
				out.Gaps = append(out.Gaps, gap{"closure_body_not_summarized", &sp})
			case *ast.GoStmt:
				special[node.Call] = "concurrent"
			case *ast.DeferStmt:
				special[node.Call] = "deferred"
			case *ast.CallExpr:
				kind, target, method, results, typeArgIDs := ix.classify(node, functions)
				if override, ok := special[node]; ok {
					kind, target, method, results, typeArgIDs = override, "", false, 0, nil
				}
				// `results` only travels on a `direct_import` record
				// whose callee returns more than one value — the
				// consumer needs the declared arity to admit tuple
				// unpacking.
				if kind != "direct_import" || results <= 1 {
					results = 0
				}
				sp := ix.nodeSpan(node)
				if fn, ok := functions[owner]; !ok || fn.Body == nil || sp.Start < fn.Body.Start || sp.End > fn.Body.End || spanFile(&sp) != spanFile(fn.Body) {
					owner = ""
				}
				args := []span{}
				for _, arg := range node.Args {
					args = append(args, ix.nodeSpan(arg))
				}
				out.Calls = append(out.Calls, call{sp, args, owner, target, kind, method, results, typeArgIDs})
				if owner == "" {
					out.Gaps = append(out.Gaps, gap{"call_outside_named_body", &sp})
				}
				// `direct_import` calls are summarized conservatively — the
				// result may depend on every argument — so they are not a
				// `call_not_summarized_*` gap.
				if kind != "direct_local" && kind != "direct_import" {
					out.Gaps = append(out.Gaps, gap{"call_not_summarized_" + kind, &sp})
				}
			}
			owners = append(owners, owner)
			return true
		})
	}
	for _, m := range ix.importMembers {
		out.ImportedMembers = append(out.ImportedMembers, m)
	}
	sort.Slice(out.ImportedMembers, func(i, j int) bool { return out.ImportedMembers[i].ID < out.ImportedMembers[j].ID })
	sort.Slice(out.Bindings, func(i, j int) bool { return out.Bindings[i].ID < out.Bindings[j].ID })
	sort.Slice(out.References, func(i, j int) bool { return spanLess(out.References[i].Span, out.References[j].Span) })
	sort.Slice(out.Functions, func(i, j int) bool { return out.Functions[i].BindingID < out.Functions[j].BindingID })
	sort.Slice(out.Gaps, func(i, j int) bool {
		a, b := out.Gaps[i], out.Gaps[j]
		if a.Span == nil || b.Span == nil {
			if a.Span == b.Span {
				return a.Reason < b.Reason
			}
			return b.Span == nil
		}
		if spanFile(a.Span) != spanFile(b.Span) {
			return spanFile(a.Span) < spanFile(b.Span)
		}
		if a.Span.Start != b.Span.Start {
			return a.Span.Start < b.Span.Start
		}
		if a.Span.End != b.Span.End {
			return a.Span.End < b.Span.End
		}
		return a.Reason < b.Reason
	})
	out.Status = "ok"
	return out
}

func run(in io.Reader, out io.Writer) {
	data, err := io.ReadAll(io.LimitReader(in, maxRequest+1))
	reply := base(request{})
	reply.Gaps = append(reply.Gaps, gap{"invalid_request", nil})
	if err == nil && len(data) <= maxRequest && utf8.Valid(data) {
		decoder := json.NewDecoder(bytes.NewReader(data))
		decoder.DisallowUnknownFields()
		var req request
		var extra any
		if decoder.Decode(&req) == nil && decoder.Decode(&extra) == io.EOF {
			reply = analyze(req)
		}
	}
	encoded, err := json.Marshal(reply)
	if err != nil || len(encoded) > maxReply {
		reply = base(request{})
		reply.Gaps = append(reply.Gaps, gap{"output_limit", nil})
		encoded, _ = json.Marshal(reply)
	}
	_, _ = out.Write(append(encoded, '\n'))
}

func main() { run(os.Stdin, os.Stdout) }
