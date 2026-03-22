from app.connectors.cli_output_parser import CLIOutputParser, _strip_lines


class TestStripLines:
    def test_empty(self):
        assert _strip_lines("") == []

    def test_strips_blanks(self):
        assert _strip_lines("\n\n  \n") == []

    def test_strips_mysql_warnings(self):
        lines = _strip_lines(
            "Warning: Using a password on the command line interface can be insecure.\n"
            "id\tname\n1\talice\n"
        )
        assert lines == ["id\tname", "1\talice"]

    def test_preserves_normal_lines(self):
        lines = _strip_lines("a\nb\nc")
        assert lines == ["a", "b", "c"]


class TestParseTsvWithHeaders:
    def test_basic(self):
        stdout = "id\tname\tage\n1\talice\t30\n2\tbob\t25\n"
        columns, rows = CLIOutputParser.parse_tsv_with_headers(stdout)
        assert columns == ["id", "name", "age"]
        assert rows == [["1", "alice", "30"], ["2", "bob", "25"]]

    def test_single_row(self):
        stdout = "count\n42\n"
        columns, rows = CLIOutputParser.parse_tsv_with_headers(stdout)
        assert columns == ["count"]
        assert rows == [["42"]]

    def test_empty(self):
        columns, rows = CLIOutputParser.parse_tsv_with_headers("")
        assert columns == []
        assert rows == []

    def test_headers_only(self):
        stdout = "id\tname\n"
        columns, rows = CLIOutputParser.parse_tsv_with_headers(stdout)
        assert columns == ["id", "name"]
        assert rows == []

    def test_with_mysql_warning(self):
        stdout = (
            "Warning: Using a password on the command line"
            " interface can be insecure.\nid\tname\n1\talice\n"
        )
        columns, rows = CLIOutputParser.parse_tsv_with_headers(stdout)
        assert columns == ["id", "name"]
        assert rows == [["1", "alice"]]


class TestParsePsqlTuples:
    def test_basic(self):
        stdout = "1\talice\n2\tbob\n"
        columns, rows = CLIOutputParser.parse_psql_tuples(stdout)
        assert columns == ["col0", "col1"]
        assert rows == [["1", "alice"], ["2", "bob"]]

    def test_empty(self):
        columns, rows = CLIOutputParser.parse_psql_tuples("")
        assert columns == []
        assert rows == []


class TestParseGeneric:
    def test_comma_delimiter(self):
        stdout = "a,b,c\n1,2,3\n"
        columns, rows = CLIOutputParser.parse_generic(stdout, delimiter=",")
        assert columns == ["a", "b", "c"]
        assert rows == [["1", "2", "3"]]

    def test_tab_delimiter(self):
        stdout = "x\ty\n10\t20\n"
        columns, rows = CLIOutputParser.parse_generic(stdout)
        assert columns == ["x", "y"]
        assert rows == [["10", "20"]]


class TestDetectAndParse:
    def test_mysql(self):
        stdout = "id\tname\n1\talice\n"
        columns, rows = CLIOutputParser.detect_and_parse(stdout, "mysql")
        assert columns == ["id", "name"]
        assert rows == [["1", "alice"]]

    def test_postgres(self):
        stdout = "id\tname\n1\talice\n"
        columns, rows = CLIOutputParser.detect_and_parse(stdout, "postgres")
        assert columns == ["id", "name"]
        assert rows == [["1", "alice"]]

    def test_clickhouse(self):
        stdout = "count\n42\n"
        columns, rows = CLIOutputParser.detect_and_parse(stdout, "clickhouse")
        assert columns == ["count"]
        assert rows == [["42"]]

    def test_unknown_db_type(self):
        stdout = "a\tb\n1\t2\n"
        columns, rows = CLIOutputParser.detect_and_parse(stdout, "somedb")
        assert columns == ["a", "b"]
        assert rows == [["1", "2"]]


class TestParsePsqlCsv:
    def test_basic(self):
        stdout = "id,name\n1,alice\n2,bob\n"
        columns, rows = CLIOutputParser.parse_psql_csv(stdout)
        assert columns == ["id", "name"]
        assert rows == [["1", "alice"], ["2", "bob"]]

    def test_empty(self):
        columns, rows = CLIOutputParser.parse_psql_csv("")
        assert columns == []
        assert rows == []

    def test_quoted_fields(self):
        stdout = 'id,name\n1,"alice, jr"\n'
        columns, rows = CLIOutputParser.parse_psql_csv(stdout)
        assert columns == ["id", "name"]
        assert rows == [["1", "alice, jr"]]

    def test_headers_only_no_data_rows(self):
        """CSV with only a header line."""
        stdout = "id,name\n"
        columns, rows = CLIOutputParser.parse_psql_csv(stdout)
        assert columns == ["id", "name"]
        assert rows == []


class TestParseGenericEdgeCases:
    def test_empty_input(self):
        columns, rows = CLIOutputParser.parse_generic("")
        assert columns == []
        assert rows == []


class TestStripLinesEdgeCases:
    def test_skips_blank_lines_between_content(self):
        lines = _strip_lines("a\n\nb\n\nc")
        assert lines == ["a", "b", "c"]
