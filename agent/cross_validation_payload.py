"""Cross-validation payload parsing and atom rendering helpers."""
from __future__ import annotations

import json
import re

from agent.cross_validation_foreign import _safe_identifier
from agent.cross_validation_models import (
    ContractParam,
    CrossValidationIssue,
    IssueKind,
    MumeiContractAtom,
    Severity,
)


def _replace_python_literals_outside_strings(text: str) -> str:
    """Replace unquoted Python ``None``/``True``/``False`` with JSON equivalents.

    Small OSS models frequently mix Python literals into otherwise JSON-shaped
    output (e.g. ``"return_type": None,``).  This helper only rewrites whole
    words that are outside of JSON string literals, so legitimate string
    contents are preserved.
    """
    result: list[str] = []
    i = 0
    n = len(text)
    in_string = False
    escape = False
    replacements = {
        "None": "null",
        "True": "true",
        "False": "false",
        "undefined": "null",
        "NaN": "null",
        "Infinity": "null",
    }
    while i < n:
        ch = text[i]
        if in_string:
            if escape:
                escape = False
            elif ch == "\\":
                escape = True
            elif ch == '"':
                in_string = False
            result.append(ch)
            i += 1
            continue
        if ch == '"':
            in_string = True
            result.append(ch)
            i += 1
            continue
        replaced = False
        for token, replacement in replacements.items():
            end = i + len(token)
            if (
                text[i:end] == token
                and (i == 0 or not text[i - 1].isalnum() and text[i - 1] != "_")
                and (end >= n or not text[end].isalnum() and text[end] != "_")
            ):
                # JavaScript signed infinities (`-Infinity`) and signed NaN
                # (`-NaN`) are emitted as two tokens; consume the leading minus
                # so the result is a single JSON `null` instead of `-null`.
                if (
                    token in ("Infinity", "NaN")
                    and i > 0
                    and text[i - 1] == "-"
                    and (i - 1 == 0 or not text[i - 2].isalnum() and text[i - 2] != "_")
                    and result
                    and result[-1] == "-"
                ):
                    result.pop()
                result.append(replacement)
                i = end
                replaced = True
                break
        if not replaced:
            result.append(ch)
            i += 1
    return "".join(result)


def _repair_invalid_json_string_escapes(text: str) -> str:
    r"""Escape backslashes that begin an invalid JSON escape sequence.

    Small OSS models often copy regex or string literals such as ``\+`` or
    ``\'`` verbatim into JSON strings.  JSON only allows ``\"``, ``\\``,
    ``\/``, ``\b``, ``\f``, ``\n``, ``\r``, ``\t`` and ``\uXXXX``; every
    other backslash is an error.  This helper doubles those backslashes so the
    original character sequence is preserved (e.g. ``\+`` becomes ``\\+`` in
    the source, which decodes to the literal characters ``\+``).
    """
    valid_escape = frozenset('"\\/bfnrtu')
    hex_digits = frozenset("0123456789abcdefABCDEF")
    result: list[str] = []
    i = 0
    n = len(text)
    in_string = False
    escape = False
    while i < n:
        ch = text[i]
        if in_string:
            if escape:
                result.append(ch)
                escape = False
            elif ch == "\\":
                if i + 1 < n and text[i + 1] in valid_escape:
                    if text[i + 1] == "u":
                        # ``\u`` must be followed by exactly four hex digits.
                        if (
                            i + 6 <= n
                            and len(text) >= i + 6
                            and all(c in hex_digits for c in text[i + 2 : i + 6])
                        ):
                            result.append(ch)
                            escape = True
                        else:
                            # Invalid ``\u``; escape the backslash.
                            result.append("\\\\")
                    else:
                        result.append(ch)
                        escape = True
                else:
                    # Invalid escape: escape the backslash so the next char is
                    # interpreted as a literal character.
                    result.append("\\\\")
            elif ch == '"':
                in_string = False
                result.append(ch)
            else:
                result.append(ch)
        else:
            if ch == '"':
                in_string = True
            result.append(ch)
        i += 1
    return "".join(result)


def _remove_trailing_commas(text: str) -> str:
    r"""Remove trailing commas that appear just before a closing ``}`` or ``]``.

    Small OSS models frequently emit lists or objects with a trailing comma
    (e.g. ``"effects": [],`` before a closing ``}``).  JSON does not allow
    trailing commas, so this helper removes them without touching commas inside
    string literals.
    """
    result: list[str] = []
    i = 0
    n = len(text)
    in_string = False
    escape = False
    while i < n:
        ch = text[i]
        if in_string:
            if escape:
                escape = False
            elif ch == "\\":
                escape = True
            elif ch == '"':
                in_string = False
            result.append(ch)
        elif ch == ',':
            # Look ahead for the next non-whitespace character.  If it closes the
            # current object/array, drop the comma.
            j = i + 1
            while j < n and text[j] in " \t\n\r":
                j += 1
            if j < n and text[j] in "}]":
                i = j
                continue
            result.append(ch)
        elif ch == '"':
            in_string = True
            result.append(ch)
        else:
            result.append(ch)
        i += 1
    return "".join(result)


def _strip_markdown_fence(text: str) -> str:
    """Extract JSON content from a markdown code fence if present.

    Small OSS models sometimes wrap JSON in `` ```json ... ``` `` blocks.
    This helper returns the content between the first pair of fences, or
    the original text with any leading prose trimmed away.
    """
    stripped = text.strip()
    fence_match = re.search(
        r"```(?:json)?\s*(.*?)\s*```",
        stripped,
        flags=re.DOTALL,
    )
    if fence_match:
        stripped = fence_match.group(1).strip()
    start = stripped.find("{")
    if start > 0:
        stripped = stripped[start:]
    return stripped


def _tokenize_for_json_repair(text: str) -> list[tuple[str, str]]:
    """Tokenize JSON-like text for repair, preserving strings and comments.

    Quoted strings (double and backtick) are emitted as single ``STR``
    tokens so that structural repairs do not mistake braces or commas
    inside them for JSON syntax.  ``//`` and ``/* */`` comments outside
    strings are dropped.
    """
    tokens: list[tuple[str, str]] = []
    i = 0
    n = len(text)
    start = 0
    quote: str | None = None

    while i < n:
        if quote is None:
            ch = text[i]
            if ch in ('"', "'", '`'):
                start = i
                quote = ch
                i += 1
                continue
            if text[i : i + 2] == "//":
                i += 2
                while i < n and text[i] != "\n":
                    i += 1
                continue
            if text[i : i + 2] == "/*":
                i += 2
                while i < n - 1 and not (text[i] == "*" and text[i + 1] == "/"):
                    i += 1
                if i < n - 1:
                    i += 2
                continue
            if ch.isspace():
                j = i
                while i < n and text[i].isspace():
                    i += 1
                tokens.append(("WS", text[j:i]))
                continue
            tokens.append(("OTHER", ch))
            i += 1
        else:
            if text[i] == "\\":
                i += 2
                continue
            if text[i] == quote:
                end = i + 1
                tokens.append(("STR", text[start:end]))
                quote = None
                i += 1
            else:
                i += 1
    if quote is not None:
        # Unterminated string: keep it as a token so the repairer can still
        # emit what was generated.
        tokens.append(("STR", text[start:]))
    return tokens


def _next_non_ws_token(
    tokens: list[tuple[str, str]],
    index: int,
) -> tuple[str, str] | None:
    while index < len(tokens) and tokens[index][0] == "WS":
        index += 1
    return tokens[index] if index < len(tokens) else None


def _consume_paren_value_as_string(
    tokens: list[tuple[str, str]],
    start: int,
) -> tuple[int, str]:
    """Consume a parenthesized expression and replace it with a JSON string.

    Some small OSS models emit JavaScript tuples or arrow functions as an
    ``ensures``/``requires`` value.  We cannot interpret that syntax, but
    turning the whole ``(...)`` block into a single JSON string lets the
    rest of the pipeline treat it as an opaque clause instead of aborting.
    """
    depth = 1
    i = start + 1
    while i < len(tokens) and depth > 0:
        kind, text = tokens[i]
        if kind == "OTHER":
            if text == "(":
                depth += 1
            elif text == ")":
                depth -= 1
        if depth == 0:
            break
        i += 1
    inner_raw = "".join(t[1] for t in tokens[start + 1 : i])
    return i + 1, json.dumps(inner_raw, ensure_ascii=False)


def _unquote_literal_string(token: str) -> str:
    """Convert a single- or backtick-quoted literal to its raw contents.

    Only the quotes themselves and the most common backslash escapes are
    interpreted; everything else is preserved so foreign code copied by the
    model remains intact.
    """
    if len(token) < 2:
        return token
    quote = token[0]
    if token[-1] != quote:
        # Unterminated literal; strip the opening quote and keep the rest.
        return token[1:]
    content = token[1:-1]
    if quote == '`':
        content = content.replace("\\`", '`').replace("\\\\", "\\")
    elif quote == "'":
        content = content.replace("\\'", "'").replace("\\\\", "\\")
    return content


def _decode_string_token(token: str) -> str | None:
    """Return the decoded content of any supported string-literal token.

    Returns ``None`` for non-string tokens or tokens that cannot be decoded.
    """
    if token.startswith('"'):
        try:
            content = json.loads(token, strict=False)
        except json.JSONDecodeError:
            return None
        return content if isinstance(content, str) else str(content)
    if token.startswith(("'", '`')):
        return _unquote_literal_string(token)
    return None


def _merge_value_strings(
    tokens: list[tuple[str, str]],
    start: int,
    in_object_value: bool = False,
) -> tuple[int, str]:
    """Merge adjacent string literals separated by ``+``, continuation commas,
    type-union ``|``/``&``, or only whitespace.

    Local LLMs sometimes split a long ``ensures`` or ``requires`` clause across
    multiple quoted lines with ``+`` concatenations, a continuation comma, or
    even no operator at all.  They also write union/intersection type strings
    as two quoted fragments such as ``"str"|"None"``.  When the surrounding
    structure is a value (not a new key), merge the decoded string contents into
    one JSON string, preserving ``|`` and ``&`` as part of the value.
    """
    parts: list[str] = []
    i = start
    end = start + 1
    while i < len(tokens) and tokens[i][0] == "STR":
        content = _decode_string_token(tokens[i][1])
        if content is None:
            break
        parts.append(content)

        # Look for ``+``, ``,``, or only whitespace followed by another string.
        j = i + 1
        while j < len(tokens) and tokens[j][0] == "WS":
            j += 1
        if j < len(tokens) and tokens[j][0] == "STR":
            # Adjacent string with no operator.  Only merge when we are inside an
            # object value and the following string is not a new key.
            if not in_object_value:
                break
            m = j + 1
            while m < len(tokens) and tokens[m][0] == "WS":
                m += 1
            if m < len(tokens) and tokens[m][1] == ":":
                break
            i = j
            end = j + 1
            continue
        if j < len(tokens) and tokens[j][1] in ("+", ",", "|", "&"):
            sep = tokens[j][1]
            k = j + 1
            while k < len(tokens) and tokens[k][0] == "WS":
                k += 1
            if k < len(tokens) and tokens[k][0] == "STR":
                # A comma separates array elements; do not merge it inside arrays.
                if sep == "," and not in_object_value:
                    break
                # If the separator is a comma, ``|``, or ``&`` inside an object
                # value, make sure the next string is not actually a new object
                # key (``"key": ...``).
                if sep in (",", "|", "&") and in_object_value:
                    m = k + 1
                    while m < len(tokens) and tokens[m][0] == "WS":
                        m += 1
                    if m < len(tokens) and tokens[m][1] == ":":
                        break
                # Preserve union/intersection operators inside the merged string;
                # ``+`` and continuation commas are dropped.
                if sep in ("|", "&"):
                    parts.append(sep)
                i = k
                end = k + 1
                continue
        break
    joined = "".join(parts)
    return end, json.dumps(joined, ensure_ascii=False)


def _reconstruct_repaired_json(tokens: list[tuple[str, str]]) -> str:
    """Rebuild a repairable JSON string from tokens.

    This pass also collapses ``+``/continuation string literals and converts
    parenthesized values to strings while keeping braces, brackets, commas
    and colons in their original positions.
    """
    out: list[str] = []
    stack: list[tuple[str, bool]] = []  # container kind, expect_key for objects
    i = 0
    n = len(tokens)

    while i < n:
        kind, text = tokens[i]
        if kind == "WS":
            out.append(text)
            i += 1
            continue

        if kind == "OTHER":
            if text == "{":
                stack.append(("obj", True))
                out.append(text)
                i += 1
                continue
            if text == "[":
                stack.append(("arr", False))
                out.append(text)
                i += 1
                continue
            if text == "}":
                if stack and stack[-1][0] == "obj":
                    stack.pop()
                    out.append(text)
                # A stray ``}`` (e.g. a JS closing brace copied outside a
                # string) is dropped so it does not close a mismatched container.
                i += 1
                continue
            if text == "]":
                if stack and stack[-1][0] == "arr":
                    stack.pop()
                    out.append(text)
                # Likewise, a stray ``]`` is dropped when not closing an array.
                i += 1
                continue
            if text == ":":
                if stack and stack[-1][0] == "obj":
                    stack[-1] = ("obj", False)
                out.append(text)
                i += 1
                continue
            if text == ",":
                if stack and stack[-1][0] == "obj":
                    stack[-1] = ("obj", True)
                out.append(text)
                i += 1
                continue
            if text == "(":
                end, string_token = _consume_paren_value_as_string(tokens, i)
                out.append(string_token)
                i = end
                continue
            out.append(text)
            i += 1
            continue

        if kind == "STR":
            # A string is a key when inside an object and the next non-whitespace
            # token is a colon (or we are still expecting a key after { or ,).
            is_key = False
            if stack and stack[-1][0] == "obj":
                nxt = _next_non_ws_token(tokens, i + 1)
                if stack[-1][1] or (nxt is not None and nxt[1] == ":"):
                    is_key = True
            if is_key:
                # Models sometimes emit Python/JS-style quoted keys. Convert any
                # non-JSON quote style to a proper JSON string key.
                if text.startswith(("'", '`')):
                    out.append(json.dumps(_unquote_literal_string(text), ensure_ascii=False))
                else:
                    out.append(text)
                if stack and stack[-1][0] == "obj":
                    stack[-1] = ("obj", False)
                i += 1
                continue
            if text.startswith('"'):
                in_object_value = bool(stack and stack[-1][0] == "obj")
                end, merged = _merge_value_strings(tokens, i, in_object_value)
                out.append(merged)
                i = end
                continue
            if text.startswith(("'", '`')):
                out.append(json.dumps(_unquote_literal_string(text), ensure_ascii=False))
                i += 1
                continue
            out.append(text)
            i += 1
            continue

    return "".join(out)


def _repair_json_output(text: str) -> str:
    """Apply structural repairs to small/OSS-LLM JSON output.

    Removes JSON comments, merges split string literals, and wraps
    parenthesized JavaScript expressions in strings so ``_json_from_text``
    can decode the first JSON object even when the model deviates from
    strict JSON syntax.
    """
    tokens = _tokenize_for_json_repair(text)
    return _reconstruct_repaired_json(tokens)


def _raw_decode_with_missing_comma_retry(text: str) -> tuple[dict[str, object], int]:
    """Decode JSON, inserting missing commas reported by the decoder.

    Small OSS models sometimes omit commas between two array/object
    entries (e.g. ``{"atoms": [{...} {...}]}``).  When the decoder reports
    ``Expecting ',' delimiter`` we insert a comma at the reported position and
    retry.  This is repeated up to ``max_attempts`` because a single LLM output
    may contain several missing commas.  If the error persists for any other
    reason we raise the most recent exception.
    """
    max_attempts = 10
    for _ in range(max_attempts):
        try:
            return json.JSONDecoder(strict=False).raw_decode(text)
        except json.JSONDecodeError as exc:
            if "Expecting ',' delimiter" not in str(exc) or not (0 <= exc.pos < len(text)):
                raise
            text = text[: exc.pos] + "," + text[exc.pos :]
    return json.JSONDecoder(strict=False).raw_decode(text)


def _normalize_type_fields(payload: dict[str, object]) -> dict[str, object]:
    """Ensure `type` and `return_type` are strings, flattening any schema objects.

    OSS LLMs sometimes emit `type` or `return_type` as JSON schema objects
    (e.g. ``{"type": "dict", "properties": ...}``) instead of the expected
    simple Mumei type string.  Convert those objects (or arrays) back to a
    JSON string so downstream consumers receive a string as documented in the
    output schema.
    """
    atoms_value = payload.get("atoms")
    if not isinstance(atoms_value, list):
        return payload
    for atom in atoms_value:
        if not isinstance(atom, dict):
            continue
        if isinstance(atom.get("return_type"), (dict, list)):
            atom["return_type"] = json.dumps(atom["return_type"], ensure_ascii=False)
        params_value = atom.get("params")
        if isinstance(params_value, list):
            for param in params_value:
                if isinstance(param, dict) and isinstance(param.get("type"), (dict, list)):
                    param["type"] = json.dumps(param["type"], ensure_ascii=False)
    return payload


def _json_from_text(text: str) -> dict[str, object]:
    stripped = _strip_markdown_fence(text)

    # Small OSS models may emit Python literals, invalid escape sequences,
    # literal control characters, trailing commas, JavaScript-style comments,
    # split string literals, or parenthesized expressions inside otherwise
    # JSON-shaped output.  Repair those artifacts before decoding, and parse
    # with ``strict=False`` so a literal newline in a string does not abort
    # parsing.
    stripped = _repair_invalid_json_string_escapes(stripped)
    stripped = _repair_json_output(stripped)
    stripped = _replace_python_literals_outside_strings(stripped)
    stripped = _remove_trailing_commas(stripped)

    # Some models omit the comma between array/object entries.  Retry by
    # inserting a comma at the reported failure position when the parser
    # complains about a missing ',' delimiter.
    payload, _end = _raw_decode_with_missing_comma_retry(stripped)
    if not isinstance(payload, dict):
        raise json.JSONDecodeError("expected JSON object", stripped, 0)

    # Some models emit `type`/`return_type` as JSON schema objects.  Normalize
    # them back to strings so the rest of the pipeline expects the documented
    # schema.
    payload = _normalize_type_fields(payload)
    return payload


def _atoms_from_payload(payload: dict[str, object]) -> list[MumeiContractAtom]:
    atoms_value = payload.get("atoms")
    if not isinstance(atoms_value, list):
        return []
    atoms: list[MumeiContractAtom] = []
    for index, atom_value in enumerate(atoms_value):
        if isinstance(atom_value, dict):
            atoms.append(_atom_from_mapping(atom_value, index))
    return atoms


def _requires_clause(value: object) -> str:
    """Normalize a precondition clause from an LLM-extracted JSON payload.

    Small OSS models frequently emit ``false`` when there is no meaningful
    precondition.  A literal ``false`` precondition is unsatisfiable and would
    always refute the code, so treat it as the intended ``true`` (no
    precondition).  This only applies to the LLM JSON payload path; other
    call-sites can still use ``requires: false`` to express a genuine
    unsatisfiable precondition.
    """
    clause = _contract_clause(value)
    return "true" if clause.strip().lower() == "false" else clause


def _ensures_clause(value: object) -> str:
    """Normalize a postcondition clause from an LLM-extracted JSON payload.

    Small OSS models also emit ``false`` for the postcondition when they cannot
    infer a meaningful return value (or when the function has no return value).
    A literal ``false`` postcondition is unsatisfiable and produces false
    `refuted` verdicts for otherwise valid code, so treat it as the intended
    ``true`` (no postcondition).  This only applies to the LLM JSON payload path;
    manually-written specs and test fixtures can still use ``ensures: false`` to
    express a genuine contradiction.
    """
    clause = _contract_clause(value)
    return "true" if clause.strip().lower() == "false" else clause


def _atom_from_mapping(value: dict[object, object], index: int) -> MumeiContractAtom:
    name = _safe_identifier(_string_value(value, "name", f"cross_validation_{index}"))
    params = _params_from_value(value.get("params") or value.get("inputs"))
    return_type = _string_value(value, "return_type", "i64")
    requires = _requires_clause(value.get("requires"))
    ensures = _ensures_clause(value.get("ensures"))
    effects = _string_list(value.get("effects"))
    return MumeiContractAtom(
        name=name,
        params=params,
        return_type=return_type,
        requires=requires,
        ensures=ensures,
        effects=effects,
    )


def _issues_from_payload(payload: dict[str, object]) -> list[CrossValidationIssue]:
    issues_value = payload.get("issues")
    if not isinstance(issues_value, list):
        return []
    issues: list[CrossValidationIssue] = []
    valid_kinds = {
        "contradiction",
        "ambiguity",
        "overconstraint",
        "satisfiability",
        "llm",
        "verification",
        "alignment",
        "missing_implementation",
        "postcondition_violated",
        "drift",
    }
    for issue_value in issues_value:
        if not isinstance(issue_value, dict):
            continue
        kind_text = str(issue_value.get("kind") or "llm")
        kind: IssueKind = kind_text if kind_text in valid_kinds else "llm"
        severity_text = str(issue_value.get("severity") or "error")
        severity: Severity = "warning" if severity_text == "warning" else "error"
        issues.append(
            CrossValidationIssue(
                kind=kind,
                message=str(issue_value.get("message") or "LLM reported a cross-validation issue."),
                evidence=str(issue_value.get("evidence") or ""),
                fix_suggestion=str(issue_value.get("fix_suggestion") or ""),
                location=str(issue_value.get("location") or ""),
                severity=severity,
                source_line=_int_value(issue_value.get("source_line")),
            )
        )
    return issues


def _string_value(value: dict[object, object], key: str, default: str) -> str:
    raw = value.get(key)
    if raw is None:
        return default
    text = str(raw).strip()
    return text or default


def _int_value(value: object) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def _params_from_value(value: object) -> list[ContractParam]:
    if not isinstance(value, list):
        return []
    params: list[ContractParam] = []
    for index, raw_param in enumerate(value):
        if isinstance(raw_param, dict):
            name = _safe_identifier(str(raw_param.get("name") or f"arg{index}"))
            type_name = str(raw_param.get("type") or "i64").strip() or "i64"
            params.append(ContractParam(name=name, type=type_name))
    return params


def _string_list(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item).strip() for item in value if str(item).strip()]


def _normalize_mumei_boolean_literals(clause: str) -> str:
    """Map Python/JSON-style boolean literals to Mumei lowercase keywords.

    LLMs and JSON decoders may produce ``True``/``False`` (Python bools) or
    the capitalized strings ``"True"``/``"False"``.  Mumei source expects
    lowercase ``true``/``false`` in contract clauses, so normalize them before
    writing ``.mm`` files or passing clauses to Z3/mumei.
    """
    return re.sub(r"\bTrue\b", "true", re.sub(r"\bFalse\b", "false", clause))


def _contract_clause(value: object) -> str:
    if isinstance(value, bool):
        clause = "true" if value else "false"
    elif isinstance(value, list):
        parts = [str(item).strip().rstrip(";") for item in value if str(item).strip()]
        clause = " && ".join(parts) if parts else "true"
    else:
        clause = str(value).strip().rstrip(";") if value is not None else "true"
        clause = clause or "true"
    return _normalize_mumei_boolean_literals(clause)


def _extract_inline_contract_atoms(spec_text: str) -> list[MumeiContractAtom]:
    requires_match = re.search(r"requires\s*:\s*([^;\n]+)", spec_text, flags=re.IGNORECASE)
    ensures_match = re.search(r"ensures\s*:\s*([^;\n]+)", spec_text, flags=re.IGNORECASE)
    if not requires_match and not ensures_match:
        return []
    return [
        MumeiContractAtom(
            name="nl_spec_contract",
            params=_params_from_contract_text(spec_text),
            return_type="i64",
            requires=requires_match.group(1).strip() if requires_match else "true",
            ensures=ensures_match.group(1).strip() if ensures_match else "true",
        )
    ]


def _params_from_contract_text(text: str) -> list[ContractParam]:
    names = sorted(
        name
        for name in set(re.findall(r"\b[a-zA-Z_][a-zA-Z0-9_]*\b", text))
        if name
        not in {
            "and",
            "or",
            "true",
            "false",
            "requires",
            "ensures",
            "result",
            "i64",
            "MAX",
            "MIN",
        }
    )
    return [ContractParam(name=name, type="i64") for name in names[:8]]


def _atoms_to_mumei_module(atoms: list[MumeiContractAtom]) -> str:
    blocks: list[str] = []
    for atom in atoms:
        params = ", ".join(f"{param.name}: {param.type}" for param in atom.params)
        default_value = _default_literal(atom.return_type)
        requires = _normalize_mumei_boolean_literals(atom.requires)
        ensures = _normalize_mumei_boolean_literals(atom.ensures)
        blocks.append(
            "\n".join(
                [
                    f"trusted atom {atom.name}({params}) -> {atom.return_type} {{",
                    f"    requires: {requires};",
                    f"    ensures: {ensures};",
                    "    body: {",
                    f"        {default_value}",
                    "    }",
                    "}",
                ]
            )
        )
    return "\n\n".join(blocks) + ("\n" if blocks else "")


def _default_literal(return_type: str) -> str:
    normalized = return_type.strip().lower()
    if normalized in {"bool", "boolean"}:
        return "true"
    if normalized in {"str", "string"}:
        return '""'
    if normalized in {"()", "void", "unit", "none", "nonetype"}:
        return "()"
    if normalized in {"float", "f64"}:
        return "0.0"
    return "0"
