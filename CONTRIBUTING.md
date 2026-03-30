# Contributing to CheckMyData.ai

Thank you for your interest in contributing! This guide explains how to get
started, what we expect from contributions, and how the review process works.

## Quick Start

```bash
# 1. Fork and clone
git clone https://github.com/<your-username>/checkmydata-ai.git
cd checkmydata-ai

# 2. Setup development environment
make setup

# 3. Start development servers
make dev

# 4. Create a feature branch
git checkout -b feat/your-feature-name
```

## Development Environment

### Prerequisites

- Python 3.12+
- Node.js 20+
- npm 10+
- Git

### Setup

```bash
make setup          # Install all dependencies, create .env, run migrations
make dev            # Start backend (:8000) and frontend (:3100)
```

### Running Tests

```bash
make test           # Backend unit tests
make test-frontend  # Frontend tests
make test-all       # All backend tests (unit + integration)
make lint           # Backend linting (ruff)
make check          # Lint + all tests
```

## Branch Naming

Use descriptive branch names with a type prefix:

| Prefix      | Purpose                |
|-------------|------------------------|
| `feat/`     | New feature            |
| `fix/`      | Bug fix                |
| `refactor/` | Code refactoring       |
| `docs/`     | Documentation only     |
| `test/`     | Adding/updating tests  |
| `chore/`    | Maintenance, deps, CI  |

Examples: `feat/batch-export-csv`, `fix/chat-stream-timeout`, `docs/api-reference`

## Commit Messages

Follow conventional commit format:

```
type: short description

Optional longer description explaining the "why" behind the change.
```

Types: `feat`, `fix`, `refactor`, `docs`, `test`, `chore`, `perf`, `security`

Examples:
- `feat: add batch query CSV export`
- `fix: prevent unmounted setState in ChatPanel`
- `security: add rate limiting to auth endpoints`

## Code Style

### Backend (Python)

- **Formatter**: [ruff format](https://docs.astral.sh/ruff/formatter/)
- **Linter**: [ruff check](https://docs.astral.sh/ruff/linter/)
- **Type checker**: [mypy](https://mypy-lang.org/) with `--ignore-missing-imports`
- **Line length**: 100 characters
- **Imports**: Sorted by ruff (isort-compatible)
- All new code should include type hints
- Use `async/await` for all database and I/O operations

### Frontend (TypeScript)

- **Framework**: Next.js 15 (App Router)
- **Linter**: ESLint with `--max-warnings=0`
- **Type checker**: `tsc --noEmit` must pass
- **State management**: Zustand
- **Styling**: Tailwind CSS with design tokens
- Use `"use client"` directive for client components
- Prefer `useCallback`/`useMemo` for performance-critical components

## Pull Request Process

1. **Create a branch** from `main` with a descriptive name
2. **Make your changes** with tests
3. **Run all checks locally**:
   ```bash
   # Backend
   cd backend && ruff check app/ tests/ && ruff format --check app/ tests/
   cd backend && python -m pytest tests/ -x

   # Frontend
   cd frontend && npx tsc --noEmit && npx eslint . --max-warnings=0
   cd frontend && npm test
   ```
4. **Push and open a PR** against `main`
5. **Fill out the PR template** completely
6. **Wait for CI** — all checks must pass before review
7. **Address review feedback** promptly

### PR Requirements

- [ ] All CI checks pass (lint, typecheck, tests, build)
- [ ] New code has tests where applicable
- [ ] Documentation updated if behavior changed
- [ ] No secrets or credentials in the diff
- [ ] PR description explains the "why" not just the "what"

## Testing Expectations

- **Backend**: Add unit tests for new services, routes, and utilities.
  Tests live in `backend/tests/unit/` and `backend/tests/integration/`.
  Use `pytest` with `AsyncMock` for async code.
- **Frontend**: Add tests for new components and utility functions.
  Tests live alongside components as `*.test.tsx` files.
  Use Vitest with React Testing Library.
- **Coverage**: Backend CI enforces ≥72% coverage. Don't decrease it.

## What We Accept

- Bug fixes with reproduction steps
- Performance improvements with benchmarks
- New features aligned with the project roadmap
- Documentation improvements
- Test coverage improvements
- Accessibility improvements
- Security hardening

## What Needs Discussion First

Open an issue before working on:

- Major architectural changes
- New database connectors
- New LLM provider integrations
- Breaking API changes
- Large refactors affecting multiple modules

## Code Review

All PRs are reviewed by maintainers. We look for:

- Correctness and edge case handling
- Test coverage
- Code clarity and consistency
- Security implications
- Performance impact
- Documentation completeness

## License

By contributing, you agree that your contributions will be licensed under the
[MIT License](LICENSE).
