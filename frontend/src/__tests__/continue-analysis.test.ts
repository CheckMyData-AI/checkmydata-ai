/** B-27 D1 (SCN-055): a second "Continue analysis" must re-ask the original question. */
import { describe, it, expect } from "vitest";
import { CONTINUE_LABEL, questionToContinue } from "@/lib/continue-analysis";

const q = "Top 10 users by order total in August";

describe("questionToContinue", () => {
  it("takes the last real question", () => {
    expect(questionToContinue([{ role: "user", content: q }, { role: "assistant", content: "…" }])).toBe(q);
  });

  it("skips the local continue marker, however many clicks", () => {
    expect(
      questionToContinue([
        { role: "user", content: q },
        { role: "assistant", content: "partial" },
        { role: "user", content: CONTINUE_LABEL },
        { role: "assistant", content: "still partial" },
        { role: "user", content: CONTINUE_LABEL },
      ]),
    ).toBe(q);
  });

  it("falls back when there is no question at all", () => {
    expect(questionToContinue([])).toBe("Continue the analysis");
  });
});
