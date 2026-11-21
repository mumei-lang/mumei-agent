"use strict";

const fs = require("node:fs");
const path = require("node:path");
const { TextDecoder } = require("node:util");
const ts = require("typescript");

const COMPILER_OPTIONS = Object.freeze({
  noEmit: true,
  strict: true,
  target: "ES2022",
  lib: Object.freeze(["lib.es2022.d.ts"]),
  types: Object.freeze([]),
  noResolve: true,
  jsx: "preserve",
});

function typescriptOptions() {
  return {
    noEmit: COMPILER_OPTIONS.noEmit,
    strict: COMPILER_OPTIONS.strict,
    target: ts.ScriptTarget[COMPILER_OPTIONS.target],
    lib: [...COMPILER_OPTIONS.lib],
    types: [...COMPILER_OPTIONS.types],
    noResolve: COMPILER_OPTIONS.noResolve,
    jsx: ts.JsxEmit.Preserve,
  };
}

function sortedJsonValue(value) {
  if (Array.isArray(value)) {
    return value.map(sortedJsonValue);
  }
  if (value !== null && typeof value === "object") {
    return Object.fromEntries(
      Object.keys(value)
        .sort()
        .map((key) => [key, sortedJsonValue(value[key])]),
    );
  }
  return value;
}

function utf8OffsetMap(source) {
  const offsets = new Map([[0, 0]]);
  let utf16Offset = 0;
  let byteOffset = 0;
  while (utf16Offset < source.length) {
    const character = String.fromCodePoint(source.codePointAt(utf16Offset));
    utf16Offset += character.length;
    byteOffset += Buffer.byteLength(character, "utf8");
    offsets.set(utf16Offset, byteOffset);
  }
  return offsets;
}

function createEnvelope(source, extension) {
  if (extension !== ".ts" && extension !== ".tsx") {
    throw new Error("input must be a .ts or .tsx file");
  }
  if (typeof source !== "string" || Buffer.from(source, "utf8").toString("utf8") !== source) {
    throw new Error("input must contain valid UTF-8 text");
  }

  const fileName = `input${extension}`;
  const inputPath = path.resolve("/", fileName);
  const libraryDirectory = path.dirname(require.resolve("typescript"));
  const compilerOptions = typescriptOptions();
  const utf16ToByte = utf8OffsetMap(source);

  function toByteOffset(offset) {
    const converted = utf16ToByte.get(offset);
    if (converted === undefined) {
      throw new Error("compiler returned a non-boundary source offset");
    }
    return converted;
  }

  function span(start, end) {
    return { start: toByteOffset(start), end: toByteOffset(end) };
  }

  function resolvedPath(fileNameValue) {
    return path.resolve(fileNameValue);
  }

  function isInputPath(fileNameValue) {
    return resolvedPath(fileNameValue) === inputPath;
  }

  function isLibraryPath(fileNameValue) {
    const candidate = resolvedPath(fileNameValue);
    return (
      path.dirname(candidate) === libraryDirectory &&
      /^lib.*\.d\.ts$/.test(path.basename(candidate))
    );
  }

  function readServedFile(fileNameValue) {
    if (isInputPath(fileNameValue)) {
      return source;
    }
    if (!isLibraryPath(fileNameValue)) {
      return undefined;
    }
    try {
      return fs.readFileSync(fileNameValue, "utf8");
    } catch {
      return undefined;
    }
  }

  const host = {
    getSourceFile(fileNameValue, languageVersion) {
      const text = readServedFile(fileNameValue);
      if (text === undefined) {
        return undefined;
      }
      const scriptKind = isInputPath(fileNameValue)
        ? extension === ".tsx"
          ? ts.ScriptKind.TSX
          : ts.ScriptKind.TS
        : ts.ScriptKind.TS;
      return ts.createSourceFile(
        fileNameValue,
        text,
        languageVersion,
        true,
        scriptKind,
      );
    },
    getDefaultLibFileName() {
      return path.join(libraryDirectory, "lib.es2022.d.ts");
    },
    getDefaultLibLocation() {
      return libraryDirectory;
    },
    getCurrentDirectory() {
      return "/";
    },
    getDirectories() {
      return [];
    },
    directoryExists(directory) {
      return resolvedPath(directory) === libraryDirectory;
    },
    fileExists(fileNameValue) {
      return (
        isInputPath(fileNameValue) ||
        (isLibraryPath(fileNameValue) && fs.existsSync(fileNameValue))
      );
    },
    readFile(fileNameValue) {
      return readServedFile(fileNameValue);
    },
    readDirectory() {
      return [];
    },
    getCanonicalFileName(fileNameValue) {
      return path.normalize(fileNameValue);
    },
    useCaseSensitiveFileNames() {
      return true;
    },
    getNewLine() {
      return "\n";
    },
    realpath(fileNameValue) {
      return resolvedPath(fileNameValue);
    },
    writeFile() {},
  };

  const program = ts.createProgram([inputPath], compilerOptions, host);
  const checker = program.getTypeChecker();
  const sourceFile = program.getSourceFile(inputPath);
  if (sourceFile === undefined) {
    throw new Error("compiler did not load the input file");
  }

  function referenceSymbol(identifier) {
    const parent = identifier.parent;
    if (ts.isShorthandPropertyAssignment(parent) && parent.name === identifier) {
      return checker.getShorthandAssignmentValueSymbol(parent);
    }
    return checker.getSymbolAtLocation(identifier);
  }

  function isReferenceIdentifier(identifier) {
    const parent = identifier.parent;
    if (ts.isShorthandPropertyAssignment(parent) && parent.name === identifier) {
      return true;
    }
    if (ts.getNameOfDeclaration(parent) === identifier) {
      return false;
    }
    if (
      (ts.isPropertyAccessExpression(parent) || ts.isQualifiedName(parent)) &&
      parent.name === identifier
    ) {
      return false;
    }
    if (
      (ts.isPropertyAssignment(parent) ||
        ts.isPropertySignature(parent) ||
        ts.isMethodSignature(parent)) &&
      parent.name === identifier
    ) {
      return false;
    }
    if (ts.isJsxAttribute(parent) && parent.name === identifier) {
      return false;
    }
    if (
      (ts.isLabeledStatement(parent) ||
        ts.isBreakStatement(parent) ||
        ts.isContinueStatement(parent)) &&
      parent.label === identifier
    ) {
      return false;
    }
    return true;
  }

  const references = [];
  function collectReferences(node) {
    if (ts.isIdentifier(node) && isReferenceIdentifier(node)) {
      const symbol = referenceSymbol(node);
      if (symbol === undefined) {
        references.push({
          span: span(node.getStart(sourceFile), node.getEnd()),
          name: node.text,
          declarations: null,
          library: false,
        });
      } else {
        const declarations = symbol.declarations ?? [];
        if (declarations.length === 0) {
          references.push({
            span: span(node.getStart(sourceFile), node.getEnd()),
            name: node.text,
            declarations: [],
            library: true,
          });
        } else {
          const inSource = declarations.filter(
            (declaration) =>
              declaration.getSourceFile().fileName === inputPath,
          );
          const declarationSpans = inSource.map((declaration) => {
            const name = ts.getNameOfDeclaration(declaration);
            const nameNode = name === undefined ? declaration : name;
            return span(nameNode.getStart(sourceFile), nameNode.getEnd());
          });
          declarationSpans.sort(
            (left, right) => left.start - right.start || left.end - right.end,
          );
          references.push({
            span: span(node.getStart(sourceFile), node.getEnd()),
            name: node.text,
            declarations: declarationSpans,
            library: inSource.length === 0,
          });
        }
      }
    }
    ts.forEachChild(node, collectReferences);
  }
  collectReferences(sourceFile);
  references.sort(
    (left, right) =>
      left.span.start - right.span.start ||
      left.span.end - right.span.end ||
      left.name.localeCompare(right.name),
  );

  const unsupported = [];
  function addUnsupported(kind, start, end) {
    unsupported.push({ kind, span: span(start, end) });
  }
  function collectUnsupported(node) {
    if (ts.isImportDeclaration(node)) {
      addUnsupported("ImportDeclaration", node.getStart(sourceFile), node.getEnd());
    } else if (ts.isImportEqualsDeclaration(node)) {
      addUnsupported(
        "ImportEqualsDeclaration",
        node.getStart(sourceFile),
        node.getEnd(),
      );
    } else if (
      (ts.isExportDeclaration(node) || ts.isExportAssignment(node)) &&
      node.moduleSpecifier !== undefined
    ) {
      addUnsupported("ExternalExport", node.getStart(sourceFile), node.getEnd());
    } else if (
      ts.isCallExpression(node) &&
      node.expression.kind === ts.SyntaxKind.ImportKeyword
    ) {
      addUnsupported("ImportCall", node.getStart(sourceFile), node.getEnd());
    } else if (ts.isImportTypeNode(node)) {
      addUnsupported("ImportType", node.getStart(sourceFile), node.getEnd());
    } else if (
      ts.isCallExpression(node) &&
      ts.isIdentifier(node.expression) &&
      node.expression.text === "require"
    ) {
      addUnsupported("RequireCall", node.getStart(sourceFile), node.getEnd());
    } else if (
      ts.isModuleDeclaration(node) &&
      ts.isStringLiteral(node.name)
    ) {
      addUnsupported(
        "StringModuleDeclaration",
        node.getStart(sourceFile),
        node.getEnd(),
      );
    }
    ts.forEachChild(node, collectUnsupported);
  }
  collectUnsupported(sourceFile);

  for (const directive of sourceFile.referencedFiles || []) {
    addUnsupported("TripleSlashReference", directive.pos, directive.end);
  }
  for (const directive of sourceFile.typeReferenceDirectives || []) {
    addUnsupported("TripleSlashTypeReference", directive.pos, directive.end);
  }
  for (const directive of sourceFile.libReferenceDirectives || []) {
    addUnsupported("TripleSlashLibReference", directive.pos, directive.end);
  }
  const uniqueUnsupported = new Map();
  for (const item of unsupported) {
    uniqueUnsupported.set(
      `${item.kind}:${item.span.start}:${item.span.end}`,
      item,
    );
  }

  const categoryNames = new Map([
    [ts.DiagnosticCategory.Error, "error"],
    [ts.DiagnosticCategory.Warning, "warning"],
    [ts.DiagnosticCategory.Suggestion, "suggestion"],
    [ts.DiagnosticCategory.Message, "message"],
  ]);
  const diagnostics = ts
    .getPreEmitDiagnostics(program)
    .map((diagnostic) => {
      const category = categoryNames.get(diagnostic.category);
      if (category === undefined) {
        throw new Error("unknown TypeScript diagnostic category");
      }
      return {
        category,
        code: diagnostic.code,
        message: ts.flattenDiagnosticMessageText(diagnostic.messageText, "\n"),
      };
    })
    .sort(
      (left, right) =>
        left.category.localeCompare(right.category) ||
        left.code - right.code ||
        left.message.localeCompare(right.message),
    );

  const unsupportedItems = [...uniqueUnsupported.values()].sort(
    (left, right) =>
      left.span.start - right.span.start ||
      left.span.end - right.span.end ||
      left.kind.localeCompare(right.kind),
  );

  return {
    profile: "mumei.tsc-symbol-envelope/v1",
    typescript_version: ts.version,
    compiler_options: COMPILER_OPTIONS,
    file_name: fileName,
    source,
    diagnostics,
    unsupported: unsupportedItems,
    references,
  };
}

function main(arguments_) {
  if (arguments_.length !== 1) {
    process.stderr.write("usage: node helper.js <file.ts|file.tsx>\n");
    return 2;
  }
  const inputPath = arguments_[0];
  const extension = path.extname(inputPath);
  if (extension !== ".ts" && extension !== ".tsx") {
    process.stderr.write("input must be a .ts or .tsx file\n");
    return 2;
  }
  try {
    const source = new TextDecoder("utf-8", { fatal: true }).decode(
      fs.readFileSync(inputPath),
    );
    const envelope = createEnvelope(source, extension);
    process.stdout.write(
      `${JSON.stringify(sortedJsonValue(envelope), null, 2)}\n`,
    );
    return 0;
  } catch {
    process.stderr.write("unable to produce TypeScript compiler envelope\n");
    return 1;
  }
}

module.exports = { COMPILER_OPTIONS, createEnvelope };

if (require.main === module) {
  process.exitCode = main(process.argv.slice(2));
}
