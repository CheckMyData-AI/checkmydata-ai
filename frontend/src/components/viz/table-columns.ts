/**
 * How a result table decides what a column is.
 *
 * The pack sets numeric columns right-aligned, in the data face, with tabular
 * figures — which only works if "numeric" is decided from the data rather than
 * from the column name. Pure, so the decision is testable without a DOM.
 */

/** A value the database returned as absent. Rendered as NULL, never as "". */
export function isNull(value: unknown): boolean {
  return value === null || value === undefined;
}

/**
 * A column is numeric when every value it actually has is a number. One empty
 * string in an id column is enough to make it text — and it should be, because
 * right-aligning a column of ids that turned out to hold `N/A` is worse than
 * leaving it alone.
 *
 * An all-null column is NOT numeric: nothing about it is known.
 */
export function isNumericColumn(rows: Array<Record<string, unknown>>, column: string): boolean {
  let seen = 0;
  for (const row of rows) {
    const value = row[column];
    if (isNull(value)) continue;
    if (typeof value === "boolean") return false;
    if (typeof value === "number") {
      if (!Number.isFinite(value)) return false;
      seen++;
      continue;
    }
    if (typeof value === "string") {
      const trimmed = value.trim();
      // A numeric-looking string only counts when it is the whole cell:
      // "2026-08-15" parses as NaN, which is what we want, and " 12 " does not.
      if (trimmed === "" || !Number.isFinite(Number(trimmed))) return false;
      seen++;
      continue;
    }
    return false;
  }
  return seen > 0;
}

/** The numeric columns of a result set, computed once per render. */
export function numericColumns(
  rows: Array<Record<string, unknown>>,
  columns: string[],
): Set<string> {
  return new Set(columns.filter((c) => isNumericColumn(rows, c)));
}
