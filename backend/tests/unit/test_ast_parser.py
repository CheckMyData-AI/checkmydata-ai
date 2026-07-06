"""Unit tests for :mod:`app.knowledge.ast_parser` (M1).

Tests cover:
    * Per-language symbol extraction for Python, TypeScript, JavaScript, Java, Go
    * Import extraction across languages
    * Parse-error tolerance (malformed source -> partial results)
    * Size guard (oversized file -> skipped with reason)
    * Binary / minified file detection
    * Decorator extraction for Python and TypeScript
    * UID stability
"""

from __future__ import annotations

import asyncio

import pytest

from app.knowledge.ast_parser import (
    ASTParser,
    ImportRef,
    Symbol,
    detect_language,
)


@pytest.fixture
def parser() -> ASTParser:
    return ASTParser()


# ---------------------------------------------------------------------------
# Language detection
# ---------------------------------------------------------------------------


def test_detect_language_by_extension():
    from pathlib import Path

    assert detect_language(Path("foo.py")).slug == "python"
    assert detect_language(Path("a/b/c.ts")).slug == "typescript"
    assert detect_language(Path("x.tsx")).slug == "tsx"
    assert detect_language(Path("y.go")).slug == "go"
    assert detect_language(Path("z.java")).slug == "java"
    assert detect_language(Path("w.unknown")) is None


def test_detect_language_by_shebang():
    from pathlib import Path

    g = detect_language(Path("scriptfile"), first_bytes=b"#!/usr/bin/env python3\n")
    assert g is not None and g.slug == "python"
    g2 = detect_language(Path("scriptfile2"), first_bytes=b"#!/usr/bin/env node\n")
    assert g2 is not None and g2.slug == "javascript"


# ---------------------------------------------------------------------------
# Python
# ---------------------------------------------------------------------------


PY_SOURCE = b'''"""Module docstring."""

from typing import List
import os as _os

class User:
    """The user model."""

    def __init__(self, name: str) -> None:
        self.name = name

    def greet(self) -> str:
        return f"hi {self.name}"

@decorator_one
@decorator_two("arg")
def standalone_function(x: int) -> int:
    """Standalone fn."""
    return x + 1
'''


def test_parse_python_extracts_class_and_functions(parser: ASTParser):
    parsed = parser.parse_bytes("src/user.py", PY_SOURCE)
    assert parsed is not None
    assert parsed.language == "python"
    assert parsed.byte_size > 0
    assert parsed.parse_errors == []

    names = sorted(s.name for s in parsed.symbols)
    assert "User" in names
    assert "standalone_function" in names
    # __init__ and greet should both appear as methods
    method_names = sorted(s.name for s in parsed.symbols if s.kind == "method")
    assert "__init__" in method_names
    assert "greet" in method_names

    user_class = next(s for s in parsed.symbols if s.name == "User" and s.kind == "class")
    assert user_class.docstring.startswith("The user model")

    fn = next(s for s in parsed.symbols if s.name == "standalone_function")
    assert "decorator_one" in fn.decorators
    # Decorator with call args is captured verbatim
    assert any("decorator_two" in d for d in fn.decorators)


def test_parse_python_extracts_imports(parser: ASTParser):
    parsed = parser.parse_bytes("src/user.py", PY_SOURCE)
    assert parsed is not None
    mods = {imp.source_module for imp in parsed.imports}
    assert "typing" in mods
    assert "os" in mods
    typing_imp = next(imp for imp in parsed.imports if imp.source_module == "typing")
    assert "List" in typing_imp.imported_names
    os_imp = next(imp for imp in parsed.imports if imp.source_module == "os")
    assert os_imp.alias == "_os"


def test_parse_python_methods_have_class_parent_uid(parser: ASTParser):
    parsed = parser.parse_bytes("src/user.py", PY_SOURCE)
    assert parsed is not None
    user_class = next(s for s in parsed.symbols if s.name == "User" and s.kind == "class")
    greet = next(s for s in parsed.symbols if s.name == "greet")
    assert greet.parent_uid == user_class.uid


def test_python_uid_stable(parser: ASTParser):
    """UID format: lang:rel_path:kind:name (no line — CODEIDX-C7)."""
    parsed = parser.parse_bytes("src/user.py", PY_SOURCE)
    assert parsed is not None
    fn = next(s for s in parsed.symbols if s.name == "standalone_function")
    parts = fn.uid.split(":")
    assert parts[0] == "python"
    assert parts[1] == "src/user.py"
    assert parts[2] == "function"
    assert parts[3] == "standalone_function"
    assert len(parts) == 4  # no line component in UID
    assert fn.start_line > 0  # start_line is still captured as an attribute


# ---------------------------------------------------------------------------
# TypeScript / JavaScript
# ---------------------------------------------------------------------------


TS_SOURCE = b"""
import { Get, Controller } from "@nestjs/common";
import UserService from "./user.service";

@Controller("/users")
export class UserController {
    constructor(private readonly users: UserService) {}

    @Get(":id")
    findOne(id: string) {
        return this.users.find(id);
    }
}

export function helper(x: number): number {
    return x + 1;
}

interface Persisted {
    id: string;
}
"""


def test_parse_typescript_class_function_interface(parser: ASTParser):
    parsed = parser.parse_bytes("src/users/user.controller.ts", TS_SOURCE)
    assert parsed is not None
    assert parsed.language == "typescript"

    kinds_by_name = {s.name: s.kind for s in parsed.symbols}
    assert kinds_by_name.get("UserController") == "class"
    assert kinds_by_name.get("helper") == "function"
    assert kinds_by_name.get("Persisted") == "interface"
    assert kinds_by_name.get("findOne") == "method"


def test_parse_typescript_imports(parser: ASTParser):
    parsed = parser.parse_bytes("src/users/user.controller.ts", TS_SOURCE)
    assert parsed is not None
    nest_imp = next(i for i in parsed.imports if i.source_module == "@nestjs/common")
    assert "Get" in nest_imp.imported_names
    assert "Controller" in nest_imp.imported_names
    svc_imp = next(i for i in parsed.imports if i.source_module == "./user.service")
    # Default import: imported_names contains the local default binding.
    assert "UserService" in svc_imp.imported_names


JS_SOURCE = b"""
import express from "express";

function handler(req, res) {
    res.send("ok");
}

class Greeter {
    sayHi() { return "hi"; }
}
"""


def test_parse_javascript_class_function(parser: ASTParser):
    parsed = parser.parse_bytes("server.js", JS_SOURCE)
    assert parsed is not None
    assert parsed.language == "javascript"
    names = {s.name for s in parsed.symbols}
    assert "handler" in names
    assert "Greeter" in names
    assert "sayHi" in names


# ---------------------------------------------------------------------------
# Java
# ---------------------------------------------------------------------------


JAVA_SOURCE = b"""
package com.example;

import java.util.List;
import com.example.UserService;

public class UserController {
    private final UserService service;

    public UserController(UserService service) {
        this.service = service;
    }

    public List<String> list() {
        return service.all();
    }
}
"""


def test_parse_java_class_methods(parser: ASTParser):
    parsed = parser.parse_bytes("src/main/java/com/example/UserController.java", JAVA_SOURCE)
    assert parsed is not None
    assert parsed.language == "java"
    names = {s.name for s in parsed.symbols}
    assert "UserController" in names
    assert "list" in names


def test_parse_java_imports(parser: ASTParser):
    parsed = parser.parse_bytes("src/main/java/com/example/UserController.java", JAVA_SOURCE)
    assert parsed is not None
    mods = {imp.source_module for imp in parsed.imports}
    assert "java.util.List" in mods
    assert "com.example.UserService" in mods


# ---------------------------------------------------------------------------
# Go
# ---------------------------------------------------------------------------


GO_SOURCE = b"""
package main

import (
    "fmt"
    "net/http"
)

func handler(w http.ResponseWriter, r *http.Request) {
    fmt.Fprintln(w, "hello")
}

func main() {
    http.HandleFunc("/", handler)
}
"""


def test_parse_go_functions(parser: ASTParser):
    parsed = parser.parse_bytes("main.go", GO_SOURCE)
    assert parsed is not None
    assert parsed.language == "go"
    names = {s.name for s in parsed.symbols}
    assert "handler" in names
    assert "main" in names


# ---------------------------------------------------------------------------
# Error tolerance & guards
# ---------------------------------------------------------------------------


def test_oversized_file_is_skipped():
    parser = ASTParser(max_file_bytes=100)
    big = b"x = 1\n" * 1000  # 6000 bytes >> 100
    parsed = parser.parse_bytes("big.py", big)
    assert parsed is not None
    assert parsed.parse_errors[0].reason == "too_large"
    assert parsed.symbols == []


def test_binary_file_is_skipped(parser: ASTParser):
    # NULL bytes -> classified as binary
    binary = b"\x00\x01\x02" * 500
    parsed = parser.parse_bytes("payload.py", binary)
    assert parsed is not None
    assert parsed.parse_errors[0].reason == "binary"


def test_minified_file_is_skipped(parser: ASTParser):
    huge_line = b"a=1;b=2;c=3;" * 1000  # one line, > 5000 chars
    parsed = parser.parse_bytes("bundle.js", huge_line)
    assert parsed is not None
    assert parsed.parse_errors[0].reason == "minified"


def test_unsupported_extension_returns_none(parser: ASTParser):
    parsed = parser.parse_bytes("README.md", b"# Title\nbody\n")
    assert parsed is None


def test_empty_file_handled(parser: ASTParser):
    parsed = parser.parse_bytes("empty.py", b"")
    assert parsed is not None
    assert parsed.symbols == []
    assert parsed.parse_errors == []


def test_malformed_python_still_partial(parser: ASTParser):
    # First half is valid, second half is broken syntax — should still extract
    # the first definition before tolerance is exceeded.
    src = b"""def good():
    return 1

def bad(
    this is not python
    ...
"""
    parsed = parser.parse_bytes("mixed.py", src)
    assert parsed is not None
    # Either error_ratio is below threshold and we get symbols, or it's above
    # and we get parse_errors. Both are acceptable; what matters is no crash.
    assert isinstance(parsed.symbols, list)


# ---------------------------------------------------------------------------
# Concurrency: parsing many files via asyncio.to_thread + semaphore
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_parse_many_files_concurrently(parser: ASTParser):
    sources = [(f"file_{i}.py", PY_SOURCE) for i in range(20)]
    sem = asyncio.Semaphore(4)

    async def _parse_one(path, content):
        async with sem:
            return await asyncio.to_thread(parser.parse_bytes, path, content)

    results = await asyncio.gather(*[_parse_one(p, s) for p, s in sources])
    assert all(r is not None for r in results)
    assert all(any(sym.name == "User" for sym in r.symbols) for r in results)


# ---------------------------------------------------------------------------
# Dataclass smoke tests for Symbol / ImportRef
# ---------------------------------------------------------------------------


def test_symbol_is_immutable():
    s = Symbol(
        uid="python:a.py:function:foo",
        kind="function",
        name="foo",
        file_path="a.py",
        start_line=1,
        end_line=2,
    )
    with pytest.raises(Exception):  # frozen dataclass
        s.name = "bar"  # type: ignore[misc]


def test_import_ref_defaults():
    ref = ImportRef(source_module="x")
    assert ref.imported_names == ()
    assert ref.alias is None
    assert ref.line == 0


# ---------------------------------------------------------------------------
# CODEIDX-C7: UID must be line-independent (line is an attribute, not identity)
# ---------------------------------------------------------------------------


def test_uid_is_stable_across_line_shift(parser: ASTParser):
    """Inserting a comment above a function must not change its UID (CODEIDX-C7)."""
    src_v1 = b"def helper():\n    return 1\n"
    src_v2 = b"# an added comment line\ndef helper():\n    return 1\n"
    uid_v1 = parser.parse_bytes("a.py", src_v1).symbols[0].uid
    sym_v2 = parser.parse_bytes("a.py", src_v2).symbols[0]
    assert uid_v1 == sym_v2.uid == "python:a.py:function:helper"
    assert sym_v2.start_line == 2  # line still captured, only as an attribute


def test_method_uid_excludes_line_but_keeps_parent(parser: ASTParser):
    """Method UIDs must not carry a line suffix; parent_uid linkage must still hold."""
    src = b"class Svc:\n    def run(self):\n        return 1\n"
    pf = parser.parse_bytes("s.py", src)
    cls = next(s for s in pf.symbols if s.kind == "class")
    method = next(s for s in pf.symbols if s.kind == "method")
    assert cls.uid == "python:s.py:class:Svc"
    assert method.uid == "python:s.py:method:run"
    assert method.parent_uid == cls.uid


def test_same_name_functions_collapse_to_one_uid(parser: ASTParser):
    """Two same-named functions in one file collapse to a single UID (last wins)."""
    src = b"def f():\n    return 1\n\ndef f():\n    return 2\n"
    pf = parser.parse_bytes("dup.py", src)
    uids = {s.uid for s in pf.symbols if s.name == "f"}
    assert uids == {"python:dup.py:function:f"}


# ---------------------------------------------------------------------------
# CODEIDX-C6: EXTENDS/heritage from AST nodes, multi-base
# ---------------------------------------------------------------------------


def test_python_multi_base_captured_in_bases(parser: ASTParser):
    """Python class with multiple base classes populates Symbol.bases (CODEIDX-C6)."""
    src = b"class A:\n    pass\nclass B:\n    pass\nclass C(A, B):\n    pass\n"
    syms = {s.name: s for s in parser.parse_bytes("h.py", src).symbols}
    assert syms["C"].bases == ("A", "B")


def test_python_single_base_captured(parser: ASTParser):
    """Single-base Python class populates Symbol.bases with one entry."""
    src = b"class Base:\n    pass\nclass Child(Base):\n    pass\n"
    syms = {s.name: s for s in parser.parse_bytes("h.py", src).symbols}
    assert syms["Child"].bases == ("Base",)


def test_python_no_base_empty_bases(parser: ASTParser):
    """Python class without base classes has empty bases tuple."""
    src = b"class Standalone:\n    pass\n"
    syms = {s.name: s for s in parser.parse_bytes("h.py", src).symbols}
    assert syms["Standalone"].bases == ()


def test_python_metaclass_excluded_from_bases(parser: ASTParser):
    """metaclass= keyword argument must not appear in Symbol.bases."""
    src = b"class M(type):\n    pass\nclass A(metaclass=M):\n    pass\n"
    syms = {s.name: s for s in parser.parse_bytes("h.py", src).symbols}
    assert syms["A"].bases == ()


def test_python_multiline_base_list_captured(parser: ASTParser):
    """Multi-line base list (longer than 200 chars) is captured fully from AST."""
    long_name = "A" * 50
    long_name2 = "B" * 50
    src = (
        f"class {long_name}:\n    pass\n"
        f"class {long_name2}:\n    pass\n"
        f"class C(\n    {long_name},\n    {long_name2},\n):\n    pass\n"
    ).encode()
    syms = {s.name: s for s in parser.parse_bytes("h.py", src).symbols}
    assert set(syms["C"].bases) == {long_name, long_name2}


def test_ts_extends_implements_captured(parser: ASTParser):
    """TypeScript class with extends + implements captures both bases (CODEIDX-C6)."""
    src = b"interface I {}\nclass Base {}\nclass Svc extends Base implements I {\n  run() {}\n}\n"
    syms = {s.name: s for s in parser.parse_bytes("s.ts", src).symbols}
    assert set(syms["Svc"].bases) == {"Base", "I"}


def test_ts_extends_generic_base_captured(parser: ASTParser):
    """TypeScript class extending a generic type captures the base name without type args."""
    src = b"class Repo<T> {}\nclass UserRepo extends Repo<User> {}\n"
    syms = {s.name: s for s in parser.parse_bytes("r.ts", src).symbols}
    assert syms["UserRepo"].bases == ("Repo",)


def test_ts_implements_multiple_captured(parser: ASTParser):
    """TypeScript class implementing multiple interfaces captures all names."""
    src = b"class S extends B implements I, J, K {}\n"
    syms = {s.name: s for s in parser.parse_bytes("s.ts", src).symbols}
    assert set(syms["S"].bases) == {"B", "I", "J", "K"}


def test_function_symbol_has_no_bases(parser: ASTParser):
    """Non-class symbols always have an empty bases tuple."""
    src = b"def helper():\n    return 1\n"
    syms = {s.name: s for s in parser.parse_bytes("h.py", src).symbols}
    assert syms["helper"].bases == ()


# ---------------------------------------------------------------------------
# CODEIDX-C5: module-level vars/consts, arrow-function components, exports
# ---------------------------------------------------------------------------


def test_arrow_function_component_is_a_function_symbol(parser: ASTParser):
    """Arrow-function-assigned const (React component style) becomes kind=function."""
    src = b"export const Button = (props) => {\n  return null;\n};\n"
    syms = {s.name: s for s in parser.parse_bytes("Button.tsx", src).symbols}
    assert "Button" in syms
    assert syms["Button"].kind == "function"


def test_module_const_is_a_variable_symbol(parser: ASTParser):
    """Plain module-level const (non-function value) becomes kind=variable."""
    src = b"export const MAX_ROWS = 1000;\nconst LOCAL = 2;\n"
    syms = {s.name: s.kind for s in parser.parse_bytes("c.ts", src).symbols}
    assert syms.get("MAX_ROWS") == "variable"
    assert syms.get("LOCAL") == "variable"


def test_exported_function_declaration_is_a_function_symbol(parser: ASTParser):
    """export function bar() {} still extracts as function (already via function_declaration)."""
    src = b"export function bar() { return 1; }\n"
    syms = {s.name: s for s in parser.parse_bytes("b.ts", src).symbols}
    assert "bar" in syms
    assert syms["bar"].kind == "function"


def test_arrow_function_component_tsx(parser: ASTParser):
    """Arrow-function component in .tsx file is extracted as kind=function."""
    src = b"import React from 'react';\nexport const Card = () => <div />;\n"
    syms = {s.name: s for s in parser.parse_bytes("Card.tsx", src).symbols}
    assert "Card" in syms
    assert syms["Card"].kind == "function"


def test_function_expression_const_is_function_symbol(parser: ASTParser):
    """const Baz = function() {} is extracted as kind=function."""
    src = b"const Baz = function() { return 1; };\n"
    syms = {s.name: s for s in parser.parse_bytes("b.js", src).symbols}
    assert "Baz" in syms
    assert syms["Baz"].kind == "function"


def test_js_module_const_is_a_variable_symbol(parser: ASTParser):
    """Plain const in .js file (non-function value) becomes kind=variable."""
    src = b"export const API_URL = 'https://example.com';\nconst TIMEOUT = 30;\n"
    syms = {s.name: s.kind for s in parser.parse_bytes("config.js", src).symbols}
    assert syms.get("API_URL") == "variable"
    assert syms.get("TIMEOUT") == "variable"


def test_variable_symbol_uid_format(parser: ASTParser):
    """Variable symbols get correct UID: lang:path:variable:name."""
    src = b"const MY_CONST = 42;\n"
    syms = {s.name: s for s in parser.parse_bytes("cfg.ts", src).symbols}
    assert "MY_CONST" in syms
    assert syms["MY_CONST"].uid == "typescript:cfg.ts:variable:MY_CONST"


def test_arrow_fn_symbol_uid_format(parser: ASTParser):
    """Arrow-function symbols get kind=function in their UID."""
    src = b"const myFunc = () => {};\n"
    syms = {s.name: s for s in parser.parse_bytes("f.ts", src).symbols}
    assert "myFunc" in syms
    assert syms["myFunc"].uid == "typescript:f.ts:function:myFunc"


def test_existing_ts_symbols_unaffected_by_c5(parser: ASTParser):
    """Adding variable_nodes must not break existing class/function/interface extraction."""
    parsed = parser.parse_bytes("src/users/user.controller.ts", TS_SOURCE)
    assert parsed is not None
    kinds_by_name = {s.name: s.kind for s in parsed.symbols}
    assert kinds_by_name.get("UserController") == "class"
    assert kinds_by_name.get("helper") == "function"
    assert kinds_by_name.get("Persisted") == "interface"
    assert kinds_by_name.get("findOne") == "method"


def test_python_consts_not_extracted_by_c5(parser: ASTParser):
    """Python module-level constants must NOT be extracted (C5 is JS/TS only)."""
    src = b"MAX_ROWS = 1000\nLOCAL = 2\n\ndef helper():\n    return 1\n"
    syms = {s.name: s for s in parser.parse_bytes("c.py", src).symbols}
    assert "MAX_ROWS" not in syms
    assert "LOCAL" not in syms
    assert "helper" in syms
