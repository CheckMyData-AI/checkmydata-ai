from app.knowledge.file_splitter import split_large_file


class TestFileSplitter:
    def test_small_file_single_segment(self):
        content = "class Foo:\n    pass\n"
        segments = split_large_file(content, "foo.py")
        assert len(segments) == 1
        assert segments[0].content == content

    def test_python_split_at_class_boundary(self):
        classes = []
        for i in range(5):
            classes.append(f"class Model{i}(Base):\n" + "    field = 'x'\n" * 200)
        preamble = "import sqlalchemy\n\n"
        content = preamble + "\n".join(classes)
        segments = split_large_file(content, "models.py", max_segment_chars=500)
        assert len(segments) >= 2
        for seg in segments:
            assert "import sqlalchemy" in seg.content

    def test_prisma_split_at_model_boundary(self):
        models = []
        for i in range(5):
            models.append(
                f"model Entity{i} {{\n"
                + "  id Int @id\n" * 100
                + "}\n"
            )
        preamble = "generator client {\n  provider = \"prisma-client-js\"\n}\n\n"
        content = preamble + "\n".join(models)
        segments = split_large_file(content, "schema.prisma", max_segment_chars=800)
        assert len(segments) >= 2
        for seg in segments:
            assert seg.name.startswith("Entity")

    def test_js_ts_split(self):
        blocks = []
        for i in range(5):
            blocks.append(
                f"export class Service{i} {{\n"
                + f"  method{i}() {{ return {i}; }}\n" * 200
                + "}\n"
            )
        preamble = "import {{ Injectable }} from '@nestjs/common';\n\n"
        content = preamble + "\n".join(blocks)
        segments = split_large_file(content, "services.ts", max_segment_chars=800)
        assert len(segments) >= 2
        for seg in segments:
            assert "import" in seg.content

    def test_generic_split_at_blank_lines(self):
        paragraphs = ["paragraph " * 200 + "\n"] * 10
        content = "\n\n".join(paragraphs)
        segments = split_large_file(content, "notes.md", max_segment_chars=500)
        assert len(segments) >= 2

    def test_python_no_classes_uses_generic(self):
        content = ("x = 1\n" * 50 + "\n") * 100
        segments = split_large_file(content, "script.py", max_segment_chars=500)
        assert len(segments) >= 2

    def test_python_syntax_error_uses_generic(self):
        content = "def broken(\n" + "  x = 1\n" * 5000
        segments = split_large_file(content, "broken.py", max_segment_chars=500)
        assert len(segments) >= 1

    def test_segment_names(self):
        content = (
            "import os\n\n"
            "class Alpha:\n" + "    pass\n" * 500 + "\n"
            "class Beta:\n" + "    pass\n" * 500 + "\n"
        )
        segments = split_large_file(content, "models.py", max_segment_chars=500)
        names = [s.name for s in segments]
        assert "Alpha" in names
        assert "Beta" in names

    def test_drizzle_table_boundary(self):
        tables = []
        for i in range(5):
            tables.append(
                f"export const table{i} = pgTable('table{i}', {{\n"
                + f"  col{i}: serial('col{i}'),\n" * 100
                + "});\n"
            )
        preamble = "import { pgTable, serial } from 'drizzle-orm/pg-core';\n\n"
        content = preamble + "\n".join(tables)
        segments = split_large_file(content, "schema.ts", max_segment_chars=800)
        assert len(segments) >= 2
