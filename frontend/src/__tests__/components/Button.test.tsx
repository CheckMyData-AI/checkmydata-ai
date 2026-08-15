import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { Button } from "@/components/ui/Button";
import { cn } from "@/lib/utils";

describe("Button — the pack's one ban, enforced at the primitive", () => {
  it("fills the primary with INK and never with the accent", () => {
    render(<Button>Run query</Button>);
    const cls = screen.getByRole("button", { name: "Run query" }).className;
    expect(cls).toContain("bg-primary");
    expect(cls).not.toMatch(/\bbg-accent\b/);
  });

  it("keeps the label's colour through the class merge", () => {
    // The defect this exists for: `tailwind-merge` did not know `text-body` and
    // `text-meta` are font SIZES, so it put them in the same conflict group as
    // `text-primary-foreground` and dropped the colour. The button rendered as a
    // black slab with an invisible label, and every gate stayed green — it was
    // caught in a screenshot.
    for (const size of ["sm", "md"] as const) {
      render(<Button size={size}>Label {size}</Button>);
      const cls = screen.getByRole("button", { name: `Label ${size}` }).className;
      expect(cls).toContain("text-primary-foreground");
    }
  });

  it("makes the destructive a bordered ghost rather than a red slab", () => {
    render(<Button variant="destructive">Delete</Button>);
    const cls = screen.getByRole("button", { name: "Delete" }).className;
    expect(cls).toContain("border-danger");
    expect(cls).toContain("text-danger");
    expect(cls).toContain("bg-transparent");
  });

  it("lets a caller override a variant class instead of fighting it", () => {
    render(
      <Button className="bg-panel" >
        Ghosted
      </Button>,
    );
    const cls = screen.getByRole("button", { name: "Ghosted" }).className;
    expect(cls).toContain("bg-panel");
    // The unprefixed fill is gone; `hover:bg-primary/92` is a different conflict
    // group and stays, which is tailwind-merge behaving correctly rather than a
    // leak — asserting on the bare substring would have flagged it.
    expect(cls).not.toMatch(/(^|\s)bg-primary(\s|$)/);
  });
});

describe("cn — the merge this project relies on", () => {
  it("keeps a size and a colour that only look alike", () => {
    expect(cn("text-body", "text-primary-foreground")).toBe("text-body text-primary-foreground");
    expect(cn("text-primary-foreground", "text-meta")).toBe("text-primary-foreground text-meta");
  });

  it("still resolves a real conflict", () => {
    expect(cn("text-body", "text-title")).toBe("text-title");
    expect(cn("bg-primary", "bg-panel")).toBe("bg-panel");
    expect(cn("tracking-kicker", "tracking-title")).toBe("tracking-title");
  });
});
