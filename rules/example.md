# Example Custom Rules

This file demonstrates how to define custom rules for the database agent.
Place your rule files (`.md`, `.yaml`, `.yml`, `.txt`) in this directory.

## Naming Conventions
- Table `users` contains all registered accounts
- Column `created_at` is always UTC timestamp
- Column `is_active` indicates soft-delete status (false = deleted)

## Business Metrics
- **Active Users**: users WHERE is_active = true AND last_login > NOW() - INTERVAL 30 days
- **Revenue**: SUM(orders.total) WHERE orders.status = 'completed'
- **Churn Rate**: users who were active last month but not this month

## Query Guidelines
- Always filter by `is_active = true` unless specifically asked about deleted records
- Use `LIMIT 100` by default for large tables
- Prefer `COUNT(*)` over fetching all rows when only a count is needed
