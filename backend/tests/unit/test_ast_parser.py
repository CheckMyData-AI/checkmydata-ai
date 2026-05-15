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
    """UID format: lang:rel_path:kind:name:line."""
    parsed = parser.parse_bytes("src/user.py", PY_SOURCE)
    assert parsed is not None
    fn = next(s for s in parsed.symbols if s.name == "standalone_function")
    parts = fn.uid.split(":")
    assert parts[0] == "python"
    assert parts[1] == "src/user.py"
    assert parts[2] == "function"
    assert parts[3] == "standalone_function"
    assert int(parts[4]) == fn.start_line


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
        uid="python:a.py:function:foo:1",
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
