import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { Seal, sealStateFor } from "@/components/ui/Seal";

describe("sealStateFor — the seal is derived, never asserted", () => {
  it("seals a query the reader can open as verified", () => {
    expect(
      sealStateFor({ responseType: "sql_result", query: "SELECT 1" }),
    ).toBe("verified");
  });

  it("downgrades a query whose index the backend reported stale", () => {
    expect(
      sealStateFor({
        responseType: "sql_result",
        query: "SELECT 1",
        stalenessWarning: "Schema indexed 9 days ago",
      }),
    ).toBe("inferred");
  });

  it("calls a retrieval-backed answer inferred — the step it can name is the retrieval", () => {
    expect(sealStateFor({ responseType: "knowledge", sourceCount: 3 })).toBe("inferred");
  });

  it("refuses to seal an answer with no query and nothing retrieved", () => {
    expect(sealStateFor({ responseType: "text" })).toBe("unverified");
    expect(sealStateFor({ responseType: "knowledge", sourceCount: 0 })).toBe("unverified");
  });

  // Each case carries evidence that would otherwise seal it higher — sources,
  // or a query. Without that the assertion lands on the function's final
  // fallback and the terminal-state branch is never exercised: two planted
  // defects survived the first version of this test for exactly that reason.
  // A partial run that retrieved four sources and then died is the case that
  // separates them: it must not read as `inferred`.
  it("refuses to seal a terminal run that carries evidence anyway", () => {
    expect(sealStateFor({ responseType: "stage_failed", sourceCount: 4 })).toBe("unverified");
    expect(sealStateFor({ responseType: "step_limit_reached", sourceCount: 4 })).toBe(
      "unverified",
    );
    expect(sealStateFor({ responseType: "error", sourceCount: 4 })).toBe("unverified");
    expect(sealStateFor({ responseType: "sql_result", query: "SELECT 1", error: "boom" })).toBe(
      "unverified",
    );
  });

  it("keeps every state reachable — a vocabulary with a dead state is decoration", () => {
    const reached = new Set(
      [
        { responseType: "sql_result", query: "SELECT 1" },
        { responseType: "knowledge", sourceCount: 2 },
        { responseType: "text" },
      ].map(sealStateFor),
    );
    expect(reached).toEqual(new Set(["verified", "inferred", "unverified"]));
  });
});

describe("Seal", () => {
  it("renders the word VISIBLY, because the colour cannot carry the meaning alone", () => {
    render(<Seal state="verified" />);
    const word = screen.getByText("Verified");
    expect(word).toBeInTheDocument();
    // `getByText` finds an sr-only node just as happily, which is how the first
    // version of this test passed against a seal that had been reduced to a
    // coloured dot. The point of the rule is that a sighted reader who cannot
    // distinguish the hue still gets the word.
    expect(word.closest(".sr-only")).toBeNull();
    expect(word.className).not.toMatch(/\bsr-only\b/);
  });

  // The contrast test measures TOKENS; it cannot see which class a component
  // hangs on a word. A planted revert — the word back in the state's colour —
  // walked straight past it, which is why this assertion is here and not there.
  it.each(["verified", "inferred", "unverified"] as const)(
    "paints the %s word in ink and puts the state's colour on the glyph only",
    (state) => {
      const { container } = render(<Seal state={state} />);
      const root = container.firstElementChild as HTMLElement;
      expect(root.className).toContain("text-ink");
      // `Unverified` in --warn measures 2.13:1 on the light panel. The word is
      // never the coloured part.
      expect(root.className).not.toMatch(/\btext-(warn|info|accent)\b/);
      const glyph = container.querySelector("[aria-hidden='true']") as HTMLElement;
      expect(glyph.className).toMatch(/\btext-(warn|info|accent)\b/);
    },
  );

  it("becomes the link to the proof when there is one", async () => {
    const onOpenProof = vi.fn();
    render(<Seal state="verified" onOpenProof={onOpenProof} />);
    await userEvent.click(screen.getByRole("button", { name: /open the proof/i }));
    expect(onOpenProof).toHaveBeenCalledOnce();
  });

  it("says what each state means, for a reader who cannot see the hue", () => {
    render(<Seal state="unverified" />);
    expect(screen.getByText(/cannot say how this was obtained/i)).toBeInTheDocument();
  });
});
