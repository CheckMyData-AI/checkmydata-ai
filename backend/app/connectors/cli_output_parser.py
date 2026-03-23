"""Parse tabular CLI output from database clients into columns + rows."""

from __future__ import annotations

MAX_OUTPUT_BYTES = 10 * 1024 * 1024  # 10 MB cap


class CLIOutputParser:
    """Parse tab-separated CLI output into structured data."""

    @staticmethod
    def parse_tsv_with_headers(stdout: str) -> tuple[list[str], list[list[str]]]:
        """Parse output where the first line is tab-separated headers.

        Works for: mysql --batch, clickhouse --format TabSeparatedWithNames.
        """
        lines = _strip_lines(stdout)
        if not lines:
            return [], []

        columns = lines[0].split("\t")
        rows = [line.split("\t") for line in lines[1:]]
        return columns, rows

    @staticmethod
    def parse_psql_csv(stdout: str) -> tuple[list[str], list[list[str]]]:
        """Parse psql --csv output (comma-separated, first line = headers)."""
        import csv
        import io

        text = stdout.strip()
        if not text:
            return [], []

        reader = csv.reader(io.StringIO(text))
        all_rows = list(reader)
        columns = all_rows[0]
        rows = all_rows[1:]
        return columns, rows

    @staticmethod
    def parse_psql_tuples(stdout: str) -> tuple[list[str], list[list[str]]]:
        """Parse psql -t -A -F '\\t' output (no headers, tab-separated)."""
        lines = _strip_lines(stdout)
        if not lines:
            return [], []

        rows = [line.split("\t") for line in lines]
        num_cols = len(rows[0]) if rows else 0
        columns = [f"col{i}" for i in range(num_cols)]
        return columns, rows

    @staticmethod
    def parse_generic(stdout: str, delimiter: str = "\t") -> tuple[list[str], list[list[str]]]:
        """Generic delimiter-based parser, first line = headers."""
        lines = _strip_lines(stdout)
        if not lines:
            return [], []

        columns = lines[0].split(delimiter)
        rows = [line.split(delimiter) for line in lines[1:]]
        return columns, rows

    @staticmethod
    def detect_and_parse(
        stdout: str,
        db_type: str,
    ) -> tuple[list[str], list[list[str]]]:
        """Auto-detect the right parser based on db_type."""
        if db_type in ("mysql", "clickhouse"):
            return CLIOutputParser.parse_tsv_with_headers(stdout)
        if db_type in ("postgres", "postgresql"):
            return CLIOutputParser.parse_tsv_with_headers(stdout)
        return CLIOutputParser.parse_generic(stdout)


_NOISE_PREFIXES = (
    "Warning: Using a password",
    "Warning: Using unique option prefix",
    "mysql: [Warning]",
    "mysql: Deprecated",
)


def _strip_lines(text: str) -> list[str]:
    """Split text into non-empty lines, ignoring common CLI noise."""
    lines: list[str] = []
    for raw in text.strip().splitlines():
        line = raw.rstrip("\n\r")
        if not line:
            continue
        if any(line.startswith(prefix) for prefix in _NOISE_PREFIXES):
            continue
        lines.append(line)
    return lines
