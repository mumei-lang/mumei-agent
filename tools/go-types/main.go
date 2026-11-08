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
	"strings"
	"unicode/utf8"
)

const profile = "mumei.go-types-single-file/v1"
const languageVersion = "go1.23"
const maxSource = 64 * 1024
const maxRequest = 512 * 1024
const maxReply = 8 * 1024 * 1024

type request struct {
	Source     string `json:"source"`
	TargetArch string `json:"target_arch"`
}

// All spans are half-open UTF-8 byte offsets in the complete input source.
type span struct {
	Start int `json:"start"`
	End   int `json:"end"`
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

type snapshot struct {
	Profile         string      `json:"profile"`
	SourceSHA256    string      `json:"source_sha256"`
	TargetArch      string      `json:"target_arch"`
	LanguageVersion string      `json:"language_version"`
	CompilerVersion string      `json:"compiler_version"`
	Status          string      `json:"status"`
	Bindings        []binding   `json:"bindings"`
	References      []reference `json:"references"`
	Functions       []function  `json:"functions"`
	Calls           []call      `json:"calls"`
	Gaps            []gap       `json:"gaps"`
}

type indexer struct {
	source string
	fset   *token.FileSet
	pkg    *types.Package
	sizes  types.Sizes
	info   *types.Info
	out    *snapshot
}

func base(req request) snapshot {
	return snapshot{
		Profile: profile, SourceSHA256: fmt.Sprintf("%x", sha256.Sum256([]byte(req.Source))),
		TargetArch: req.TargetArch, LanguageVersion: languageVersion, CompilerVersion: runtime.Version(),
		Status: "invalid_request", Bindings: []binding{}, References: []reference{},
		Functions: []function{}, Calls: []call{}, Gaps: []gap{},
	}
}

func (ix *indexer) offset(p token.Pos) int { return ix.fset.PositionFor(p, false).Offset }

func (ix *indexer) nodeSpan(n ast.Node) span { return span{ix.offset(n.Pos()), ix.offset(n.End())} }

func (ix *indexer) scope(obj types.Object) *span {
	sc := obj.Parent()
	if sc == nil {
		return nil
	}
	if sc == ix.pkg.Scope() {
		return &span{0, len(ix.source)}
	}
	return &span{ix.offset(sc.Pos()), ix.offset(sc.End())}
}

func (ix *indexer) id(obj types.Object) string {
	if obj == nil || obj.Pkg() != ix.pkg || !obj.Pos().IsValid() || obj.Name() == "" || obj.Name() == "_" {
		return ""
	}
	start, end := -1, -1
	if sc := ix.scope(obj); sc != nil {
		start, end = sc.Start, sc.End
	}
	// Type-switch case bindings can share a declaration position, not a scope.
	return fmt.Sprintf("sha256:%s:%d:%d:%d", ix.out.SourceSHA256, ix.offset(obj.Pos()), start, end)
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
	ix.out.Bindings = append(ix.out.Bindings, binding{
		id, obj.Name(), kind, span{start, start + len(obj.Name())}, ix.scope(obj), tf,
	})
	if tf.Kind == "unsupported" || tf.Kind == "untyped" || tf.Kind == "function" && kind != "function" {
		sp := span{start, start + len(obj.Name())}
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
		return "external_or_bodyless", ""
	}
	if fn.Method || fn.Generic || fn.Variadic {
		return "method_generic_or_variadic", ""
	}
	return "direct_local", fn.BindingID
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
	if len(req.Source) > maxSource || !utf8.ValidString(req.Source) {
		out.Gaps = append(out.Gaps, gap{"source_limit_or_encoding", nil})
		return out
	}
	switch req.TargetArch {
	case "amd64", "386", "arm64":
	default:
		out.Gaps = append(out.Gaps, gap{"unsupported_target", nil})
		return out
	}
	fset := token.NewFileSet()
	file, err := parser.ParseFile(fset, "source.go", req.Source, parser.ParseComments|parser.AllErrors)
	if err != nil {
		out.Status = "parse_error"
		out.Gaps = append(out.Gaps, gap{"parse_error", nil})
		return out
	}
	ix := indexer{source: req.Source, fset: fset, out: &out, sizes: types.SizesFor("gc", req.TargetArch)}
	for _, imp := range file.Imports {
		sp := ix.nodeSpan(imp)
		out.Gaps = append(out.Gaps, gap{"imports_not_supported", &sp})
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
	if len(out.Gaps) != 0 {
		out.Status = "unsupported"
		return out
	}
	info := &types.Info{
		Defs: make(map[*ast.Ident]types.Object), Uses: make(map[*ast.Ident]types.Object),
		Implicits: make(map[ast.Node]types.Object), Types: make(map[ast.Expr]types.TypeAndValue),
		Selections: make(map[*ast.SelectorExpr]*types.Selection),
	}
	conf := types.Config{GoVersion: languageVersion, Sizes: ix.sizes, Error: func(e error) {
		if len(out.Gaps) < 16 {
			var sp *span
			if te, ok := e.(types.Error); ok && te.Pos.IsValid() {
				p := ix.offset(te.Pos)
				sp = &span{p, p}
			}
			out.Gaps = append(out.Gaps, gap{"type_error", sp})
		}
	}}
	pkg, err := conf.Check("mumei.local/singlefile", fset, []*ast.File{file}, info)
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
		id, kind := ix.id(obj), "local"
		if id == "" {
			kind = "universe"
		}
		out.References = append(out.References, reference{ix.nodeSpan(ident), id, kind})
	}
	functions := make(map[string]function)
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
			fn.Body = &span{ix.offset(fd.Body.Lbrace) + 1, ix.offset(fd.Body.Rbrace)}
		}
		functions[fn.BindingID] = fn
		out.Functions = append(out.Functions, fn)
	}
	owners := []string{}
	special := make(map[*ast.CallExpr]string)
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
			if fn, ok := functions[owner]; !ok || fn.Body == nil || sp.Start < fn.Body.Start || sp.End > fn.Body.End {
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
			if kind != "direct_local" {
				out.Gaps = append(out.Gaps, gap{"call_not_summarized_" + kind, &sp})
			}
		}
		owners = append(owners, owner)
		return true
	})
	sort.Slice(out.Bindings, func(i, j int) bool { return out.Bindings[i].ID < out.Bindings[j].ID })
	sort.Slice(out.References, func(i, j int) bool { return out.References[i].Span.Start < out.References[j].Span.Start })
	sort.Slice(out.Functions, func(i, j int) bool { return out.Functions[i].BindingID < out.Functions[j].BindingID })
	sort.Slice(out.Gaps, func(i, j int) bool {
		a, b := out.Gaps[i], out.Gaps[j]
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
