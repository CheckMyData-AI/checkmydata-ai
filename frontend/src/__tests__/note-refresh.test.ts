/** B-27 (SCN-069): a refreshed note must not repeat prose written about an older result. */
import { describe, it, expect } from "vitest";
import { refreshedNoteMessage } from "@/lib/note-refresh";

describe("refreshedNoteMessage", () => {
  it("states what came back, not the old answer", () => {
    const msg = refreshedNoteMessage("Revenue by month", {
      columns: ["m", "rev"],
      rows: [["2026-08", 1], ["2026-09", 2]],
      total_rows: 2,
    });
    expect(msg).toContain("[Refreshed] Revenue by month");
    expect(msg).toContain("returned 2 rows");
  });

  it("uses the singular for one row and handles no result", () => {
    expect(refreshedNoteMessage("t", { columns: [], rows: [[1]], total_rows: 1 })).toContain("1 row.");
    expect(refreshedNoteMessage("t", null)).toContain("no result came back");
  });
});
