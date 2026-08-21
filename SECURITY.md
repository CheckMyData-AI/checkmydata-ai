# Security Policy

## Reporting a Vulnerability

**Do not open a public GitHub issue for security vulnerabilities.**

If you discover a security vulnerability in CheckMyData.ai, please report it
responsibly:

1. **Email**: Send details to **security@checkmydata.ai**
2. **Subject**: Include `[SECURITY]` in the subject line
3. **Include**:
   - Description of the vulnerability
   - Steps to reproduce
   - Potential impact
   - Suggested fix (if any)

We will acknowledge your report within **48 hours** and aim to provide a fix
within **7 days** for critical issues.

## What to Report

- Authentication or authorization bypasses
- SQL injection, command injection, or path traversal
- Cross-site scripting (XSS) or cross-site request forgery (CSRF)
- Sensitive data exposure (credentials, tokens, PII)
- Insecure default configurations
- Dependency vulnerabilities with exploitable impact

## What NOT to Report Publicly

- Do not disclose vulnerability details in GitHub Issues, Discussions, or PRs
- Do not publish proof-of-concept exploits before a fix is released
- Do not access or modify other users' data during testing

## Supported Versions

| Version | Supported |
|---------|-----------|
| main    | Yes       |
| < main  | No        |

We only support the latest version on the `main` branch. Security fixes are
not backported to older commits.

## Security Measures in Place

- JWT authentication with configurable expiry
- Fernet encryption for stored credentials (`MASTER_ENCRYPTION_KEY`), **with key rotation** (F-CONN-05): `MASTER_ENCRYPTION_KEYS_OLD` holds retired keys for reading, new ciphertext is always written with the primary, and a key change detected at boot re-encrypts every stored secret onto it. See *Rotating the encryption key* below.
- Rate limiting on all mutating endpoints
- Input validation with Pydantic models and Literal types
- Path traversal protection via `validate_safe_id`
- SQL identifier quoting to prevent injection
- Security headers middleware (X-Content-Type-Options, X-Frame-Options, etc.)
- CSRF protection on Google OAuth flow
- Production secret validation (rejects insecure defaults)
- Audit logging on security-sensitive operations

## Responsible Disclosure

We follow a coordinated disclosure process. After a fix is released, we will:
1. Credit the reporter (unless they prefer anonymity)
2. Publish a security advisory
3. Update the changelog

## Rotating the encryption key

Every stored credential — database passwords, connection strings, MCP environments, SSH
private keys and passphrases, vendor secrets — is Fernet-encrypted with
`MASTER_ENCRYPTION_KEY`. Until 2026-08-21 that key could not be changed: swapping it made
every stored secret permanently unreadable, so the only path was a hand-written
re-encryption script. In practice that meant the key was never rotated.

**The procedure is two config values and a deploy.**

```bash
# 1. Generate the new key
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"

# 2. Move the current key to the retired list, put the new one in front
heroku config:set \
  MASTER_ENCRYPTION_KEY='<new key>' \
  MASTER_ENCRYPTION_KEYS_OLD='<previous key>' --app <app>
```

At boot, `app.ops.encryption_reconcile` notices the primary key's fingerprint changed and
re-encrypts every secret onto the new key. It is advisory-locked (safe on multiple dynos),
idempotent (a second boot is a no-op), and never blocks startup.

**Then read the boot log, because the outcome decides your next step:**

| Log line | Meaning | What to do |
|---|---|---|
| `Encryption reconcile at startup: rotated (rotated=N failed=0)` | every secret moved | clear `MASTER_ENCRYPTION_KEYS_OLD` on the next deploy |
| `... : partial` + an `ERROR` naming rows | some row is readable by **no** configured key | **keep the retired key.** The marker was deliberately not advanced, so the next boot retries. Investigate the named rows — they are usually the residue of an earlier manual key change |
| `... : unchanged` | the key did not change | nothing to do |
| `... : seeded` | first boot after this feature shipped | nothing to do — existing rows are already on the only key there has ever been |

**Do not clear `MASTER_ENCRYPTION_KEYS_OLD` on a `partial`.** Dropping a key that some row
still needs is the one irreversible mistake available here. The count that answers "is it
safe yet" is `app.ops.credential_rotation.pending_rotation_count`, and zero is the green
light.

**Rotating twice before a sweep finishes is a supported state**, not an error:
`MASTER_ENCRYPTION_KEYS_OLD` accepts a comma-separated list and every entry is tried in
order. A malformed entry raises at first use rather than being skipped — a silently
ignored retired key is how a rotation appears to succeed while leaving rows unreadable.
