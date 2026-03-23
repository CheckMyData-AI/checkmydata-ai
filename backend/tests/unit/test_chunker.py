from app.knowledge.chunker import chunk_document


class TestChunker:
    def test_small_document_single_chunk(self):
        content = "This is a small document."
        chunks = chunk_document(content, "test.py", "orm_model")
        assert len(chunks) == 1
        assert chunks[0].content == content
        assert chunks[0].metadata["source_path"] == "test.py"

    def test_large_document_split_by_class(self):
        parts = []
        for i in range(10):
            parts.append(f"class Model{i}:\n" + "    field = Column(Integer)\n" * 50)
        content = "\n".join(parts)
        chunks = chunk_document(content, "models.py", "orm_model")
        assert len(chunks) > 1
        for chunk in chunks:
            assert chunk.metadata["source_path"] == "models.py"

    def test_extra_metadata_preserved(self):
        content = "class Foo:\n    pass\n" * 200
        chunks = chunk_document(
            content,
            "foo.py",
            "orm_model",
            extra_metadata={"commit_sha": "abc123", "models": "Foo"},
        )
        for chunk in chunks:
            assert chunk.metadata["commit_sha"] == "abc123"
            assert chunk.metadata["models"] == "Foo"

    def test_empty_content(self):
        chunks = chunk_document("", "empty.py", "orm_model")
        assert len(chunks) == 0

    def test_large_document_no_class_boundary(self):
        content = "x = 12345678\n" * 2000
        chunks = chunk_document(content, "plain.py", "raw_sql")
        assert len(chunks) >= 1
        assert all(c.metadata["source_path"] == "plain.py" for c in chunks)

    def test_heading_boundaries(self):
        content = (
            "## Table: users\nUser accounts table\n\n"
            + "x = 12345678\n" * 800
            + "\n## Table: orders\nOrders table\n\n"
            + "y = 12345678\n" * 800
        )
        chunks = chunk_document(content, "schema.md", "raw_sql")
        assert len(chunks) >= 2
