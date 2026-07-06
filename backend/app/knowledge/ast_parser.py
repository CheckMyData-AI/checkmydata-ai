"""Tree-sitter based AST parsing for code intelligence (M1).

Replaces the brittle regex extraction in :mod:`app.knowledge.entity_extractor`
with deterministic AST-driven symbol/import extraction. Output is consumed by
the code knowledge graph builder (M2) and downstream lineage tooling (M5).

Design notes:
    * Parser instances are cached per-language; `tree-sitter-language-pack`
      ships pre-built grammars so no compilation is required at runtime.
    * Each language has a :class:`LanguageGrammar` config that maps tree-sitter
      node types to our normalized symbol kinds.
    * Files that exceed ``ast_max_file_bytes``, look binary/minified, or have
      too many ``ERROR`` AST nodes are skipped and counted in ``ParsedFile.errors``.
    * Symbol UIDs are deterministic: ``{lang}:{rel_path}:{kind}:{name}``.
      The definition line is intentionally excluded (CODEIDX-C7) — a line shift
      above an untouched symbol must not change its UID or orphan inbound edges.
    * Method symbols carry ``parent_uid`` referencing the enclosing class.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

_SYMBOL_KIND_FUNCTION = "function"
_SYMBOL_KIND_METHOD = "method"
_SYMBOL_KIND_CLASS = "class"
_SYMBOL_KIND_INTERFACE = "interface"
_SYMBOL_KIND_ENUM = "enum"
_SYMBOL_KIND_TYPE_ALIAS = "type_alias"

_MAX_SIGNATURE_CHARS = 200
_MAX_DOCSTRING_CHARS = 500
# Files with more than this fraction of ERROR nodes are dropped.
_DEFAULT_PARSE_ERROR_RATIO = 0.3
# Files larger than this many bytes are skipped (binary/minified/generated).
_DEFAULT_MAX_FILE_BYTES = 2_097_152
# Heuristic: lines longer than this without spaces probably mean minified output.
_MINIFIED_LINE_LEN_THRESHOLD = 5000


@dataclass(frozen=True)
class Symbol:
    """A code symbol extracted from an AST.

    Attributes:
        uid: Stable identifier ``{lang}:{rel_path}:{kind}:{name}``.
            The definition line is stored in ``start_line`` (CODEIDX-C7).
        kind: One of function/method/class/interface/enum/type_alias.
        name: Symbol name (e.g. "validate_user", "UserService").
        file_path: Repository-relative path (forward slashes).
        start_line: 1-indexed start line.
        end_line: 1-indexed end line.
        parent_uid: UID of the enclosing class (None for module-level symbols).
        language: Language slug (e.g. "python", "typescript").
        decorators: List of decorator/annotation names (e.g. ["Get('/users')", "Controller"]).
        signature: First line of the definition, truncated to 200 chars.
        docstring: First docstring/JSDoc block, truncated to 500 chars.
    """

    uid: str
    kind: str
    name: str
    file_path: str
    start_line: int
    end_line: int
    parent_uid: str | None = None
    language: str | None = None
    decorators: tuple[str, ...] = ()
    signature: str = ""
    docstring: str = ""


@dataclass(frozen=True)
class ImportRef:
    """A cross-file import reference.

    Attributes:
        source_module: Module path as written in source (e.g. "./auth", "django.db.models").
        imported_names: Concrete names brought in (empty tuple = wildcard or default import).
        alias: Optional alias name (e.g. `import X as Y` -> alias="Y").
        line: 1-indexed source line.
    """

    source_module: str
    imported_names: tuple[str, ...] = ()
    alias: str | None = None
    line: int = 0


@dataclass(frozen=True)
class CallSite:
    """A function/method invocation captured inside a symbol body.

    Used by the M2 graph builder to resolve CALLS edges. We only capture the
    surface form (callee name + optional attribute target); resolution to a
    concrete target UID happens in :mod:`app.knowledge.code_graph`.

    Attributes:
        caller_uid: UID of the function/method/class containing the call.
        callee_name: The called identifier (e.g. ``foo`` for ``foo(...)``,
            ``method`` for ``obj.method(...)``).
        attr_target: When the call is an attribute access (``a.b.c(...)``),
            this is the receiver expression as text (e.g. ``"obj"`` or
            ``"self"``). ``None`` for plain identifier calls.
        line: 1-indexed source line of the call site.
    """

    caller_uid: str
    callee_name: str
    attr_target: str | None = None
    line: int = 0


@dataclass(frozen=True)
class ParseError:
    """Captures a recoverable parse problem for telemetry."""

    file_path: str
    reason: str
    detail: str = ""


@dataclass
class ParsedFile:
    """Result of parsing one source file.

    Empty :attr:`symbols` + empty :attr:`imports` does not necessarily mean
    failure; it can also mean the file contained only data (constants, types).
    Check :attr:`error_ratio` and :attr:`parse_errors` for failure signals.
    """

    file_path: str
    language: str
    symbols: list[Symbol] = field(default_factory=list)
    imports: list[ImportRef] = field(default_factory=list)
    call_sites: list[CallSite] = field(default_factory=list)
    parse_errors: list[ParseError] = field(default_factory=list)
    error_ratio: float = 0.0
    byte_size: int = 0


@dataclass(frozen=True)
class LanguageGrammar:
    """Maps a language's tree-sitter node types to normalized kinds.

    Each list contains tree-sitter node type strings. A node's ``name`` field
    is extracted via :attr:`name_field` (most grammars use ``name``; some use
    ``identifier``-typed children).
    """

    slug: str
    extensions: tuple[str, ...]
    function_nodes: tuple[str, ...] = ()
    method_nodes: tuple[str, ...] = ()
    class_nodes: tuple[str, ...] = ()
    interface_nodes: tuple[str, ...] = ()
    enum_nodes: tuple[str, ...] = ()
    type_alias_nodes: tuple[str, ...] = ()
    import_nodes: tuple[str, ...] = ()
    decorator_nodes: tuple[str, ...] = ()
    # Function-call expression node types (e.g. Python ``call``, JS
    # ``call_expression``). Used by the graph builder to extract CALLS edges.
    call_nodes: tuple[str, ...] = ()
    # Some grammars wrap decorated functions in a parent node (e.g. Python
    # ``decorated_definition``). When set, we descend into it to find the
    # underlying definition.
    decorated_wrapper_nodes: tuple[str, ...] = ()
    name_field: str = "name"
    shebang_aliases: tuple[str, ...] = ()


# Static config — easy to audit, easy to extend. Names verified against
# tree-sitter grammar test corpora; we deliberately keep this minimal and add
# kinds only when they actually exist in the upstream grammar.
LANGUAGE_GRAMMARS: tuple[LanguageGrammar, ...] = (
    LanguageGrammar(
        slug="python",
        extensions=(".py",),
        function_nodes=("function_definition",),
        class_nodes=("class_definition",),
        import_nodes=("import_statement", "import_from_statement"),
        decorator_nodes=("decorator",),
        call_nodes=("call",),
        decorated_wrapper_nodes=("decorated_definition",),
        shebang_aliases=("python", "python3"),
    ),
    LanguageGrammar(
        slug="typescript",
        extensions=(".ts",),
        function_nodes=("function_declaration",),
        method_nodes=("method_definition", "method_signature"),
        class_nodes=("class_declaration",),
        interface_nodes=("interface_declaration",),
        enum_nodes=("enum_declaration",),
        type_alias_nodes=("type_alias_declaration",),
        import_nodes=("import_statement",),
        decorator_nodes=("decorator",),
        call_nodes=("call_expression",),
    ),
    LanguageGrammar(
        slug="tsx",
        extensions=(".tsx",),
        function_nodes=("function_declaration",),
        method_nodes=("method_definition", "method_signature"),
        class_nodes=("class_declaration",),
        interface_nodes=("interface_declaration",),
        enum_nodes=("enum_declaration",),
        type_alias_nodes=("type_alias_declaration",),
        import_nodes=("import_statement",),
        decorator_nodes=("decorator",),
        call_nodes=("call_expression",),
    ),
    LanguageGrammar(
        slug="javascript",
        extensions=(".js", ".mjs", ".cjs"),
        function_nodes=("function_declaration",),
        method_nodes=("method_definition",),
        class_nodes=("class_declaration",),
        import_nodes=("import_statement",),
        decorator_nodes=("decorator",),
        call_nodes=("call_expression",),
        shebang_aliases=("node", "nodejs"),
    ),
    LanguageGrammar(
        slug="jsx",
        extensions=(".jsx",),
        function_nodes=("function_declaration",),
        method_nodes=("method_definition",),
        class_nodes=("class_declaration",),
        import_nodes=("import_statement",),
        call_nodes=("call_expression",),
    ),
    LanguageGrammar(
        slug="java",
        extensions=(".java",),
        method_nodes=("method_declaration", "constructor_declaration"),
        class_nodes=("class_declaration",),
        interface_nodes=("interface_declaration",),
        enum_nodes=("enum_declaration",),
        import_nodes=("import_declaration",),
        decorator_nodes=("modifiers",),  # @Annotation lives inside modifiers
        call_nodes=("method_invocation",),
    ),
    LanguageGrammar(
        slug="kotlin",
        extensions=(".kt", ".kts"),
        function_nodes=("function_declaration",),
        class_nodes=("class_declaration",),
        import_nodes=("import_header",),
        call_nodes=("call_expression",),
    ),
    LanguageGrammar(
        slug="go",
        extensions=(".go",),
        function_nodes=("function_declaration", "method_declaration"),
        type_alias_nodes=("type_declaration",),
        import_nodes=("import_declaration",),
        call_nodes=("call_expression",),
    ),
    LanguageGrammar(
        slug="rust",
        extensions=(".rs",),
        function_nodes=("function_item",),
        class_nodes=("struct_item", "impl_item"),
        enum_nodes=("enum_item",),
        type_alias_nodes=("type_item",),
        import_nodes=("use_declaration",),
        call_nodes=("call_expression",),
    ),
    LanguageGrammar(
        slug="ruby",
        extensions=(".rb",),
        method_nodes=("method", "singleton_method"),
        class_nodes=("class",),
        import_nodes=("call",),  # Ruby uses `require X` as a method call
    ),
    LanguageGrammar(
        slug="php",
        extensions=(".php",),
        function_nodes=("function_definition",),
        method_nodes=("method_declaration",),
        class_nodes=("class_declaration",),
        interface_nodes=("interface_declaration",),
        enum_nodes=("enum_declaration",),
        import_nodes=("namespace_use_declaration",),
        call_nodes=("function_call_expression", "method_call_expression"),
    ),
    LanguageGrammar(
        slug="csharp",
        extensions=(".cs",),
        method_nodes=("method_declaration", "constructor_declaration"),
        class_nodes=("class_declaration",),
        interface_nodes=("interface_declaration",),
        enum_nodes=("enum_declaration",),
        import_nodes=("using_directive",),
        call_nodes=("invocation_expression",),
    ),
)


_EXT_TO_GRAMMAR: dict[str, LanguageGrammar] = {
    ext: g for g in LANGUAGE_GRAMMARS for ext in g.extensions
}
_SHEBANG_TO_GRAMMAR: dict[str, LanguageGrammar] = {
    alias: g for g in LANGUAGE_GRAMMARS for alias in g.shebang_aliases
}


def detect_language(path: Path, first_bytes: bytes = b"") -> LanguageGrammar | None:
    """Return the language grammar for a file, or None if unsupported.

    Preference order: file extension first, then shebang for extensionless
    scripts. ``first_bytes`` is only consulted when the suffix lookup fails.
    """
    suffix = path.suffix.lower()
    g = _EXT_TO_GRAMMAR.get(suffix)
    if g is not None:
        return g
    if first_bytes.startswith(b"#!"):
        line = first_bytes.split(b"\n", 1)[0].decode("utf-8", "replace")
        for alias, candidate in _SHEBANG_TO_GRAMMAR.items():
            if alias in line:
                return candidate
    return None


def _looks_binary(content: bytes, sample_size: int = 8192) -> bool:
    """Heuristic: a non-trivial NULL-byte ratio suggests binary content."""
    sample = content[:sample_size]
    if not sample:
        return False
    nulls = sample.count(b"\x00")
    if nulls > 0:
        return True
    # If the file decodes cleanly as text, treat it as text.
    try:
        sample.decode("utf-8")
        return False
    except UnicodeDecodeError:
        return True


def _looks_minified(content: bytes) -> bool:
    """Heuristic: very long lines without whitespace suggest minified output."""
    # Scan first 16 KB only; bigger files would already be size-rejected.
    sample = content[:16_384]
    longest = 0
    line_len = 0
    for b in sample:
        if b in (0x0A, 0x0D):  # \n or \r
            longest = max(longest, line_len)
            line_len = 0
        else:
            line_len += 1
    longest = max(longest, line_len)
    return longest > _MINIFIED_LINE_LEN_THRESHOLD


def _make_uid(language: str, rel_path: str, kind: str, name: str) -> str:
    # Normalize separators so UIDs are stable across OSes. The definition line
    # is intentionally NOT part of identity (CODEIDX-C7): it is stored as the
    # ``start_line`` attribute so a line shift above an untouched symbol does
    # not orphan its inbound edges on an incremental merge.
    return f"{language}:{rel_path.replace(chr(92), '/')}:{kind}:{name}"


def _node_text(node, source: bytes) -> str:
    """Decode a tree-sitter node's byte span as UTF-8 (lossy)."""
    return source[node.start_byte : node.end_byte].decode("utf-8", "replace")


def _find_name(node, grammar: LanguageGrammar) -> str | None:
    """Locate a definition's name node.

    Tries the language-configured field first (``name`` for most grammars),
    then falls back to the first ``identifier`` child.
    """
    name_node = node.child_by_field_name(grammar.name_field)
    if name_node is not None:
        return name_node.text.decode("utf-8", "replace") if name_node.text else None
    for child in node.children:
        if child.type == "identifier":
            return child.text.decode("utf-8", "replace") if child.text else None
    return None


def _extract_decorators(node, grammar: LanguageGrammar, source: bytes) -> tuple[str, ...]:
    """Collect decorator/annotation names attached to a definition node."""
    if not grammar.decorator_nodes:
        return ()
    decorators: list[str] = []
    # Decorators may live as siblings (Python: parent decorated_definition wraps them)
    # or as children of `modifiers` (Java).
    parent = node.parent
    if parent is not None and parent.type in grammar.decorated_wrapper_nodes:
        for child in parent.children:
            if child.type in grammar.decorator_nodes:
                txt = _node_text(child, source).strip()
                if txt.startswith("@"):
                    txt = txt[1:]
                decorators.append(txt[:_MAX_SIGNATURE_CHARS])
    for child in node.children:
        if child.type in grammar.decorator_nodes:
            txt = _node_text(child, source).strip()
            if txt.startswith("@"):
                txt = txt[1:]
            decorators.append(txt[:_MAX_SIGNATURE_CHARS])
    return tuple(decorators)


def _extract_signature(node, source: bytes) -> str:
    """Return the first non-empty line of the definition, truncated."""
    text = _node_text(node, source)
    for raw in text.splitlines():
        line = raw.strip()
        if line:
            if len(line) > _MAX_SIGNATURE_CHARS:
                return line[:_MAX_SIGNATURE_CHARS] + "..."
            return line
    return ""


def _extract_python_docstring(node, source: bytes) -> str:
    """Extract a Python triple-quoted docstring from the first statement."""
    body = node.child_by_field_name("body")
    if body is None:
        return ""
    for child in body.children:
        if child.type == "expression_statement":
            for inner in child.children:
                if inner.type == "string":
                    raw = _node_text(inner, source).strip()
                    # Strip surrounding quotes (single, triple, prefixed).
                    for quote in ('"""', "'''", '"', "'"):
                        if raw.startswith(quote) and raw.endswith(quote):
                            raw = raw[len(quote) : -len(quote)]
                            break
                    return raw.strip()[:_MAX_DOCSTRING_CHARS]
            return ""
    return ""


def _count_error_nodes(root) -> tuple[int, int]:
    """Walk the tree iteratively, counting ``ERROR`` nodes and total nodes.

    Iterative DFS to avoid stack overflows on deeply-nested trees.
    """
    errors = 0
    total = 0
    stack = [root]
    while stack:
        n = stack.pop()
        total += 1
        if n.type == "ERROR" or n.is_missing:
            errors += 1
        stack.extend(n.children)
    return errors, total


def _walk_definitions(
    root,
    grammar: LanguageGrammar,
    source: bytes,
    rel_path: str,
    parent_uid: str | None = None,
) -> tuple[list[Symbol], list[CallSite]]:
    """Iteratively collect symbols and call sites from the tree.

    Methods nested inside classes inherit the class UID as ``parent_uid``.
    Call sites are scoped to their nearest enclosing function/method/class so
    the graph builder can map them back to a caller symbol.
    """
    symbols: list[Symbol] = []
    call_sites: list[CallSite] = []
    # Stack entries: (node, parent_uid, enclosing_symbol_uid)
    stack: list[tuple[Any, str | None, str | None]] = [(root, parent_uid, None)]
    call_node_types = set(grammar.call_nodes)
    while stack:
        node, current_parent, enclosing = stack.pop()
        kind = _classify_node(node, grammar)
        new_parent = current_parent
        new_enclosing = enclosing
        if kind is not None:
            sym = _node_to_symbol(node, kind, grammar, source, rel_path, current_parent)
            if sym is not None:
                symbols.append(sym)
                if kind in (_SYMBOL_KIND_CLASS, _SYMBOL_KIND_INTERFACE):
                    new_parent = sym.uid
                # Functions and methods become the "enclosing" scope for call
                # resolution; classes do not (their bodies are method defs).
                if kind in (
                    _SYMBOL_KIND_FUNCTION,
                    _SYMBOL_KIND_METHOD,
                ):
                    new_enclosing = sym.uid
        elif enclosing is not None and node.type in call_node_types:
            call = _extract_call_site(node, source, enclosing)
            if call is not None:
                call_sites.append(call)
        for child in node.children:
            stack.append((child, new_parent, new_enclosing))
    return symbols, call_sites


def _extract_call_site(node, source: bytes, caller_uid: str) -> CallSite | None:
    """Convert a tree-sitter call expression into a :class:`CallSite`.

    Returns ``None`` for calls whose callee cannot be reduced to an identifier
    or attribute (e.g. lambdas, computed names) — we deliberately skip those.
    """
    fn = node.child_by_field_name("function")
    if fn is None:
        # Some grammars expose the callee as the first child instead of a
        # named field. Try a few common types.
        for child in node.children:
            if child.type in ("identifier", "attribute", "member_expression", "field_access"):
                fn = child
                break
    if fn is None:
        return None
    line = node.start_point[0] + 1
    if fn.type == "identifier":
        name = fn.text.decode("utf-8", "replace") if fn.text else ""
        if not name:
            return None
        return CallSite(caller_uid=caller_uid, callee_name=name, line=line)
    # Attribute / member access: obj.method(...)
    name_node = fn.child_by_field_name("attribute")
    if name_node is None:
        name_node = fn.child_by_field_name("property")
    if name_node is None:
        name_node = fn.child_by_field_name("name")
    target_node = fn.child_by_field_name("object")
    if target_node is None:
        target_node = fn.child_by_field_name("receiver")
    if target_node is None and fn.children:
        # Fallback: first child is the target, last named child is the name.
        candidates = [c for c in fn.children if c.is_named]
        if len(candidates) >= 2:
            target_node = candidates[0]
            name_node = candidates[-1]
    if name_node is None:
        return None
    callee = name_node.text.decode("utf-8", "replace") if name_node.text else ""
    if not callee:
        return None
    target = None
    if target_node is not None and target_node.text:
        target = target_node.text.decode("utf-8", "replace")
        # Cap target string to avoid blowing up storage.
        if len(target) > 64:
            target = target[:64]
    return CallSite(caller_uid=caller_uid, callee_name=callee, attr_target=target, line=line)


def _classify_node(node, grammar: LanguageGrammar) -> str | None:
    """Map a tree-sitter node type to our normalized kind, or return None."""
    t = node.type
    if t in grammar.method_nodes:
        return _SYMBOL_KIND_METHOD
    if t in grammar.function_nodes:
        return _SYMBOL_KIND_FUNCTION
    if t in grammar.class_nodes:
        return _SYMBOL_KIND_CLASS
    if t in grammar.interface_nodes:
        return _SYMBOL_KIND_INTERFACE
    if t in grammar.enum_nodes:
        return _SYMBOL_KIND_ENUM
    if t in grammar.type_alias_nodes:
        return _SYMBOL_KIND_TYPE_ALIAS
    return None


def _node_to_symbol(
    node,
    kind: str,
    grammar: LanguageGrammar,
    source: bytes,
    rel_path: str,
    parent_uid: str | None,
) -> Symbol | None:
    name = _find_name(node, grammar)
    if not name:
        return None
    # Python's class methods come through as `function_definition` nested in a
    # `class_definition`. Promote them to `method` so callers can distinguish.
    if kind == _SYMBOL_KIND_FUNCTION and parent_uid is not None and grammar.slug == "python":
        kind = _SYMBOL_KIND_METHOD
    start_line = node.start_point[0] + 1
    end_line = node.end_point[0] + 1
    uid = _make_uid(grammar.slug, rel_path, kind, name)
    decorators = _extract_decorators(node, grammar, source)
    signature = _extract_signature(node, source)
    docstring = ""
    if grammar.slug == "python":
        docstring = _extract_python_docstring(node, source)
    return Symbol(
        uid=uid,
        kind=kind,
        name=name,
        file_path=rel_path,
        start_line=start_line,
        end_line=end_line,
        parent_uid=parent_uid,
        language=grammar.slug,
        decorators=decorators,
        signature=signature,
        docstring=docstring,
    )


def _extract_imports(root, grammar: LanguageGrammar, source: bytes) -> list[ImportRef]:
    """Walk the tree and collect language-specific import statements."""
    if not grammar.import_nodes:
        return []
    refs: list[ImportRef] = []
    stack = [root]
    while stack:
        node = stack.pop()
        if node.type in grammar.import_nodes:
            ref = _parse_import(node, grammar, source)
            if ref is not None:
                refs.append(ref)
            # Don't descend into the import body for performance.
            continue
        stack.extend(node.children)
    return refs


def _parse_import(node, grammar: LanguageGrammar, source: bytes) -> ImportRef | None:
    """Return an :class:`ImportRef` for a language-specific import statement.

    We deliberately keep this lossy/best-effort: the goal is to give the graph
    builder a hint about cross-file edges, not perfect resolution.
    """
    text = _node_text(node, source).strip()
    line = node.start_point[0] + 1
    if grammar.slug == "python":
        return _parse_python_import(text, line)
    if grammar.slug in ("typescript", "tsx", "javascript", "jsx"):
        return _parse_js_import(text, line)
    if grammar.slug == "java":
        return _parse_java_import(text, line)
    if grammar.slug == "go":
        return _parse_go_import(text, line)
    # Best-effort generic: store the whole statement as a single module.
    return ImportRef(source_module=text, line=line)


def _parse_python_import(text: str, line: int) -> ImportRef | None:
    # "import X" / "import X as Y" / "from X import Y, Z as W"
    if text.startswith("from "):
        try:
            _, rest = text.split("from ", 1)
            module, after = rest.split(" import ", 1)
        except ValueError:
            return None
        names = tuple(_split_imported_names(after))
        return ImportRef(source_module=module.strip(), imported_names=names, line=line)
    if text.startswith("import "):
        rest = text[len("import ") :].strip()
        # Take first comma-separated segment for the module name; ignore extra.
        segments = [s.strip() for s in rest.split(",") if s.strip()]
        if not segments:
            return None
        first = segments[0]
        alias = None
        if " as " in first:
            module, alias = (s.strip() for s in first.split(" as ", 1))
        else:
            module = first
        return ImportRef(source_module=module, alias=alias, line=line)
    return None


def _split_imported_names(after: str) -> list[str]:
    cleaned = after.strip()
    if cleaned.startswith("("):
        cleaned = cleaned.strip("()").replace("\n", "")
    out: list[str] = []
    for seg in cleaned.split(","):
        s = seg.strip()
        if not s:
            continue
        if " as " in s:
            s = s.split(" as ", 1)[0].strip()
        out.append(s)
    return out


def _parse_js_import(text: str, line: int) -> ImportRef | None:
    # import { A, B as C } from "./x"
    # import X from "./y"
    # import * as ns from "./z"
    # import "./side-effect"
    if "from " in text:
        head, rest = text.rsplit("from ", 1)
        module = rest.strip().rstrip(";").strip('"').strip("'")
        names: list[str] = []
        head_clean = head.strip()
        if head_clean.startswith("import"):
            head_clean = head_clean[len("import") :].strip()
        if head_clean.startswith("{") and "}" in head_clean:
            inside = head_clean[1 : head_clean.index("}")]
            for seg in inside.split(","):
                s = seg.strip()
                if not s:
                    continue
                if " as " in s:
                    s = s.split(" as ", 1)[0].strip()
                names.append(s)
        elif head_clean and head_clean != "*":
            # Default import or namespace import.
            first = head_clean.split(",")[0].strip()
            if first.startswith("*"):
                first = ""
            if first:
                names.append(first)
        return ImportRef(source_module=module, imported_names=tuple(names), line=line)
    # Side-effect import: `import "./styles.css"`.
    if text.startswith("import "):
        rest = text[len("import ") :].strip().rstrip(";").strip('"').strip("'")
        return ImportRef(source_module=rest, line=line)
    return None


def _parse_java_import(text: str, line: int) -> ImportRef | None:
    # `import a.b.C;` or `import static a.b.C.METHOD;`
    body = text.strip().rstrip(";")
    if body.startswith("import "):
        body = body[len("import ") :].strip()
    if body.startswith("static "):
        body = body[len("static ") :].strip()
    return ImportRef(source_module=body, line=line)


def _parse_go_import(text: str, line: int) -> ImportRef | None:
    # `import "fmt"` or `import ( "fmt"; "io" )`
    body = text.strip()
    if body.startswith("import"):
        body = body[len("import") :].strip()
    body = body.strip().strip("()").strip().strip('"')
    return ImportRef(source_module=body, line=line)


class ASTParser:
    """Stateful parser cache wrapping :mod:`tree_sitter_language_pack`.

    A single :class:`ASTParser` instance is intended to live for the duration
    of a pipeline run; the underlying parsers are immutable and thread-safe.
    """

    def __init__(
        self,
        max_file_bytes: int = _DEFAULT_MAX_FILE_BYTES,
        parse_error_ratio: float = _DEFAULT_PARSE_ERROR_RATIO,
    ) -> None:
        self._max_file_bytes = max_file_bytes
        self._parse_error_ratio = parse_error_ratio
        self._parsers: dict[str, object] = {}

    def _get_parser(self, language: str):
        cached = self._parsers.get(language)
        if cached is not None:
            return cached
        # Lazy import: tree-sitter-language-pack is heavy at import time.
        from tree_sitter_language_pack import get_parser

        try:
            # ``language`` is a runtime-resolved grammar name; the stub types
            # ``get_parser`` against a Literal of supported languages.
            parser = get_parser(language)  # type: ignore[arg-type]
        except Exception:
            logger.warning("Failed to load tree-sitter parser for %s", language, exc_info=True)
            return None
        self._parsers[language] = parser
        return parser

    def parse_bytes(
        self,
        rel_path: str,
        content: bytes,
        grammar: LanguageGrammar | None = None,
    ) -> ParsedFile | None:
        """Parse raw bytes and return a :class:`ParsedFile`.

        Returns ``None`` for binary, oversized, or unsupported files so the
        caller can short-circuit cheaply. ``ParsedFile.parse_errors`` is
        populated for partial failures (broken syntax, etc.).
        """
        if grammar is None:
            grammar = detect_language(Path(rel_path), first_bytes=content[:64])
        if grammar is None:
            return None
        size = len(content)
        if size == 0:
            return ParsedFile(
                file_path=rel_path,
                language=grammar.slug,
                byte_size=0,
            )
        if size > self._max_file_bytes:
            return ParsedFile(
                file_path=rel_path,
                language=grammar.slug,
                byte_size=size,
                parse_errors=[
                    ParseError(
                        file_path=rel_path,
                        reason="too_large",
                        detail=f"{size} bytes > {self._max_file_bytes}",
                    )
                ],
            )
        if _looks_binary(content):
            return ParsedFile(
                file_path=rel_path,
                language=grammar.slug,
                byte_size=size,
                parse_errors=[ParseError(file_path=rel_path, reason="binary")],
            )
        if _looks_minified(content):
            return ParsedFile(
                file_path=rel_path,
                language=grammar.slug,
                byte_size=size,
                parse_errors=[ParseError(file_path=rel_path, reason="minified")],
            )
        parser = self._get_parser(grammar.slug)
        if parser is None:
            return ParsedFile(
                file_path=rel_path,
                language=grammar.slug,
                byte_size=size,
                parse_errors=[
                    ParseError(file_path=rel_path, reason="parser_unavailable"),
                ],
            )
        try:
            tree = parser.parse(content)
        except Exception as exc:
            logger.debug("Tree-sitter parse failure on %s: %s", rel_path, exc, exc_info=True)
            return ParsedFile(
                file_path=rel_path,
                language=grammar.slug,
                byte_size=size,
                parse_errors=[
                    ParseError(
                        file_path=rel_path,
                        reason="parse_exception",
                        detail=str(exc),
                    )
                ],
            )
        root = tree.root_node
        errors, total = _count_error_nodes(root)
        ratio = (errors / total) if total > 0 else 0.0
        if total > 0 and ratio > self._parse_error_ratio:
            return ParsedFile(
                file_path=rel_path,
                language=grammar.slug,
                byte_size=size,
                error_ratio=ratio,
                parse_errors=[
                    ParseError(
                        file_path=rel_path,
                        reason="error_ratio_exceeded",
                        detail=f"errors={errors} total={total} ratio={ratio:.2f}",
                    )
                ],
            )
        symbols, call_sites = _walk_definitions(root, grammar, content, rel_path)
        imports = _extract_imports(root, grammar, content)
        return ParsedFile(
            file_path=rel_path,
            language=grammar.slug,
            symbols=symbols,
            imports=imports,
            call_sites=call_sites,
            error_ratio=ratio,
            byte_size=size,
        )

    def parse_file(self, repo_root: Path, rel_path: str) -> ParsedFile | None:
        """Read a file from disk and parse it. Returns ``None`` for unsupported types."""
        abs_path = repo_root / rel_path
        if not abs_path.is_file():
            return None
        try:
            content = abs_path.read_bytes()
        except OSError as exc:
            logger.warning("Failed to read %s: %s", abs_path, exc)
            return None
        grammar = detect_language(abs_path, first_bytes=content[:64])
        if grammar is None:
            return None
        return self.parse_bytes(rel_path, content, grammar=grammar)


__all__ = [
    "ASTParser",
    "CallSite",
    "ImportRef",
    "LANGUAGE_GRAMMARS",
    "LanguageGrammar",
    "ParseError",
    "ParsedFile",
    "Symbol",
    "detect_language",
]
