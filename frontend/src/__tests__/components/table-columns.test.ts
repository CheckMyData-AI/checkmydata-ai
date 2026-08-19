import { describe, expect, it } from "vitest";
import { isNull, isNumericColumn, numericColumns } from "@/components/viz/table-columns";

describe("isNull", () => {
  it("counts only absence as absence", () => {
    expect(isNull(null)).toBe(true);
    expect(isNull(undefined)).toBe(true);
    // These are values a database returned, and rendering them as NULL would be
    // a lie about the data.
    expect(isNull("")).toBe(false);
    expect(isNull(0)).toBe(false);
    expect(isNull(false)).toBe(false);
  });
});

describe("isNumericColumn — alignment is decided from the data, not the name", () => {
  const rows = [
    { id: 1, account: "Northcurrent", mrr: 156000, delta: "4", seats: null, flag: true, at: "2026-08-15" },
    { id: 2, account: "Lumenwave", mrr: 135250, delta: "-6", seats: null, flag: false, at: "2026-08-14" },
  ];

  it("aligns numbers and number-shaped strings right", () => {
    expect(isNumericColumn(rows, "id")).toBe(true);
    expect(isNumericColumn(rows, "mrr")).toBe(true);
    expect(isNumericColumn(rows, "delta")).toBe(true);
  });

  it("leaves text alone", () => {
    expect(isNumericColumn(rows, "account")).toBe(false);
  });

  it("does not mistake a date for a number", () => {
    // `Number("2026-08-15")` is NaN, which is the answer we want — a date column
    // right-aligned in tabular figures reads as a quantity.
    expect(isNumericColumn(rows, "at")).toBe(false);
  });

  it("does not mistake a boolean for a number", () => {
    expect(isNumericColumn(rows, "flag")).toBe(false);
  });

  it("calls an all-null column unknown rather than numeric", () => {
    expect(isNumericColumn(rows, "seats")).toBe(false);
  });

  it("lets one non-numeric value decide the whole column", () => {
    // A column of ids where one row says "N/A" is text: right-aligning it and
    // setting it in tabular figures would present a value that is not a number
    // as one.
    expect(isNumericColumn([{ n: 1 }, { n: 2 }, { n: "N/A" }], "n")).toBe(false);
    expect(isNumericColumn([{ n: 1 }, { n: 2 }, { n: "" }], "n")).toBe(false);
  });

  it("ignores nulls between real values", () => {
    expect(isNumericColumn([{ n: 1 }, { n: null }, { n: 3 }], "n")).toBe(true);
  });

  it("refuses a non-finite number", () => {
    expect(isNumericColumn([{ n: Number.POSITIVE_INFINITY }], "n")).toBe(false);
  });

  it("refuses a column carrying structured values", () => {
    // A jsonb or array column arrives as an object. The branch that rejects it
    // was the one plant this suite missed on its first pass: every other case
    // exits earlier, so nothing exercised it.
    expect(isNumericColumn([{ n: 1 }, { n: { total: 2 } }], "n")).toBe(false);
    expect(isNumericColumn([{ n: 1 }, { n: [1, 2] }], "n")).toBe(false);
  });
});

describe("numericColumns", () => {
  it("returns exactly the columns that are numeric", () => {
    const rows = [{ a: 1, b: "x" }, { a: 2, b: "y" }];
    expect(numericColumns(rows, ["a", "b"])).toEqual(new Set(["a"]));
  });

  it("is empty for an empty result set — nothing is known about any column", () => {
    expect(numericColumns([], ["a", "b"])).toEqual(new Set());
  });
});
