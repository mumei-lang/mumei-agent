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
}

type gap struct {
	Reason string `json:"reason"`
	Span   *span  `json:"span"`
}

type fileDigest struct {
	Name   string `json:"name"`
	SHA256 string `json:"sha256"`
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
}

var errUnresolvedImport = fmt.Errorf("unresolved import")

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
		f, err := parser.ParseFile(ix.fset, s.Name, s.Source, 0)
		if err != nil {
			return nil, errUnresolvedImport
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
// package boundaries.
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
	f := typeFact{Kind: "unsupported"}
	if t == nil {
		return f
	}
	switch typ := t.(type) {
	case *types.Named:
		f.TypeID = ix.id(typ.Obj())
	case *types.Alias:
		f.TypeID = ix.id(typ.Obj())
	case *types.TypeParam:
		f.TypeID = ix.id(typ.Obj())
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
	if tf.Kind == "unsupported" || tf.Kind == "untyped" || tf.Kind == "function" && kind != "function" {
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

func (ix *indexer) classify(c *ast.CallExpr, functions map[string]function) (string, string) {
	if ix.info.Types[c.Fun].IsType() {
		return "conversion", ""
	}
	fun := unparen(c.Fun)
	switch e := fun.(type) {
	case *ast.IndexExpr:
		fun = unparen(e.X)
	case *ast.IndexListExpr:
		fun = unparen(e.X)
	case *ast.SelectorExpr:
		if selection := ix.info.Selections[e]; selection != nil && selection.Kind() != types.FieldVal {
			return "method_generic_or_variadic", ""
		}
		// A package-qualified call `lib.G(...)`: the callee is declared in
		// a resolved imported unit. The target is that unit's own binding
		// identity; the body stays opaque to the summarizer.
		if x, ok := e.X.(*ast.Ident); ok {
			if _, isPkg := ix.info.Uses[x].(*types.PkgName); isPkg {
				if f, ok := ix.info.Uses[e.Sel].(*types.Func); ok {
					if id := ix.importedID(f); id != "" {
						return "direct_import", id
					}
				}
				return "indirect_or_selector", ""
			}
		}
	}
	ident, ok := fun.(*ast.Ident)
	if !ok {
		return "indirect_or_selector", ""
	}
	obj := ix.info.Uses[ident]
	if _, ok := obj.(*types.Builtin); ok {
		return "builtin", ""
	}
	f, ok := obj.(*types.Func)
	if !ok {
		return "indirect_or_selector", ""
	}
	fn, ok := functions[ix.id(f)]
	if !ok || fn.Body == nil {
		// Dot-imported names reach here: the func is not local but its
		// imported identity is still stable and reportable.
		if id := ix.importedID(f); id != "" {
			return "direct_import", id
		}
		return "external_or_bodyless", ""
	}
	if fn.Method || fn.Generic || fn.Variadic {
		return "method_generic_or_variadic", ""
	}
	return "direct_local", fn.BindingID
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
		files: make(map[*token.File]int),
		importDecls:    importDecls,
		importCache:    make(map[string]*types.Package),
		importInFlight: make(map[string]bool),
		importUnits:    make(map[*types.Package]*importUnit),
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
				kind, target := ix.classify(node, functions)
				if override, ok := special[node]; ok {
					kind, target = override, ""
				}
				sp := ix.nodeSpan(node)
				if fn, ok := functions[owner]; !ok || fn.Body == nil || sp.Start < fn.Body.Start || sp.End > fn.Body.End || spanFile(&sp) != spanFile(fn.Body) {
					owner = ""
				}
				args := []span{}
				for _, arg := range node.Args {
					args = append(args, ix.nodeSpan(arg))
				}
				out.Calls = append(out.Calls, call{sp, args, owner, target, kind})
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
