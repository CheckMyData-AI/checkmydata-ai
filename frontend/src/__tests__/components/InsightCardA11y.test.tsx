import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { api } from "@/lib/api";
import { useAppStore } from "@/stores/app-store";

/**
 * AUD-0819-09: the insight card's expand toggle announces its state.
 *
 * Sixteen other toggles in this tree carry `aria-expanded`; this one did not, and
 * the chevron that shows the state visually is `aria-hidden` — so a screen-reader
 * user could not tell an open card from a closed one, and had no way to know the
 * button did anything at all.
 */

vi.mock("@/lib/api", () => ({
  api: {
    insights: {
      list: vi.fn(),
      summary: vi.fn(),
      confirm: vi.fn(),
      dismiss: vi.fn(),
      resolve: vi.fn(),
    },
  },
}));

const INSIGHT = {
  id: "ins-1",
  insight_type: "anomaly",
  severity: "warning",
  title: "Signups dropped 40% week over week",
  description: "The drop is concentrated in the mobile funnel.",
  confidence: 0.8,
  times_surfaced: 1,
  status: "active",
  created_at: new Date(0).toISOString(),
};

describe("insight card expand toggle", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(api.insights.list).mockResolvedValue([INSIGHT] as never);
    vi.mocked(api.insights.summary).mockResolvedValue({
      total_active: 1,
      by_type: { anomaly: 1 },
      by_severity: { warning: 1 },
    } as never);
    useAppStore.setState({
      activeProject: { id: "p1", name: "P1" } as never,
    });
  });

  it("reports collapsed, then expanded, and points at the region it controls", async () => {
    const { InsightFeedPanel } = await import("@/components/insights/InsightFeedPanel");
    render(<InsightFeedPanel />);

    const toggle = await screen.findByRole("button", { expanded: false, name: /Signups dropped/ });
    const controls = toggle.getAttribute("aria-controls");
    expect(controls).toBeTruthy();
    // Collapsed: the region it names is genuinely absent, not merely hidden.
    expect(document.getElementById(controls!)).toBeNull();

    await userEvent.click(toggle);

    expect(toggle).toHaveAttribute("aria-expanded", "true");
    expect(document.getElementById(controls!)).not.toBeNull();
    expect(screen.getByText(/concentrated in the mobile funnel/)).toBeInTheDocument();
  });
});
