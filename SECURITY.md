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
- Fernet encryption for stored credentials (MASTER_ENCRYPTION_KEY)
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
