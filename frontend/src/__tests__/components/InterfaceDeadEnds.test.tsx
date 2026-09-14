/**
 * Four controls that described something and would not take you there.
 *
 * Each is small, and each blocked a step of the product's basic loop for a user who
 * did the reasonable thing.
 *
 * - **The Getting Started checklist** told a first-time user to create a project, add
 *   a connection and connect their code — as three plain `<div>`s with no handler.
 * - **The Data panel** printed *"No repository connected. Code questions are
 *   unavailable without one."* on the very panel called Data, with no control to
 *   connect one. `repo_url` lives on the project, and the only way in was the sidebar
 *   form or the one-shot onboarding wizard.
 * - **The demo** was reachable exactly once: `POST /api/demo/setup` had a single
 *   caller inside a wizard that mounts only while the user is un-onboarded with no
 *   projects, and every exit from it — Escape included — calls `completeOnboarding()`.
 * - **The Activity panel** was hidden from non-owners in the sidebar and not gated in
 *   the panel, and `?panel=logs` is a URL an editor can be handed. A control that is
 *   only hidden is not a control that is denied.
 */
import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

const setup = vi.fn().mockResolvedValue({ ok: true });
const projectsList = vi.fn().mockResolvedValue([{ id: "p1", name: "Demo project" }]);
const me = vi.fn().mockResolvedValue({ id: "u1", is_onboarded: true });
vi.mock("@/lib/api", () => ({
  api: { demo: { setup }, projects: { list: projectsList }, auth: { me } },
}));

const mockApp = {
  projects: [] as unknown[],
  activeProject: null as unknown,
  setProjects: vi.fn(),
  setActiveProject: vi.fn(),
};
vi.mock("@/stores/app-store", () => ({
  useAppStore: Object.assign(
    (sel?: (s: typeof mockApp) => unknown) => (sel ? sel(mockApp) : mockApp),
    { setState: vi.fn(), getState: () => mockApp },
  ),
}));
vi.mock("@/stores/auth-store", () => ({
  useAuthStore: Object.assign((sel?: (s: unknown) => unknown) => (sel ? sel({ user: {} }) : { user: {} }), {
    setState: vi.fn(),
    getState: () => ({ user: {} }),
  }),
}));
const pushToast = vi.fn();
vi.mock("@/stores/toast-store", () => ({
  toast: (...a: unknown[]) => pushToast(...a),
  useToastStore: Object.assign((sel?: (s: unknown) => unknown) => (sel ? sel({}) : {}), {
    setState: vi.fn(),
    getState: () => ({}),
  }),
}));

beforeEach(() => vi.clearAllMocks());

describe("the demo is reachable more than once", () => {
  it("loads the demo project and makes it active", async () => {
    const { LoadDemoDataButton } = await import(
      "@/components/onboarding/LoadDemoDataButton"
    );
    render(<LoadDemoDataButton />);
    await userEvent.click(screen.getByRole("button", { name: /load demo data/i }));

    expect(setup).toHaveBeenCalledOnce();
    expect(mockApp.setProjects).toHaveBeenCalled();
    expect(mockApp.setActiveProject).toHaveBeenCalledWith(
      expect.objectContaining({ id: "p1" }),
    );
    expect(pushToast).toHaveBeenCalledWith(expect.stringMatching(/demo project loaded/i), "success");
  });

  it("says so when the demo cannot be created, rather than looking successful", async () => {
    setup.mockRejectedValueOnce(new Error("demo data already exists"));
    const { LoadDemoDataButton } = await import(
      "@/components/onboarding/LoadDemoDataButton"
    );
    render(<LoadDemoDataButton />);
    await userEvent.click(screen.getByRole("button", { name: /load demo data/i }));
    expect(pushToast).toHaveBeenCalledWith("demo data already exists", "error");
    expect(mockApp.setActiveProject).not.toHaveBeenCalled();
  });
});

describe("the checklist and the Data panel are sources, not descriptions", () => {
  it("every Getting Started step is a control, in both copies", async () => {
    const src = await import("fs").then((fs) =>
      fs.readFileSync("src/components/Sidebar.tsx", "utf8"),
    );
    // Two copies exist — mobile and desktop — and only fixing one leaves the other
    // inert on exactly the devices least able to work around it.
    expect(src.match(/onClick: \(\) => setProjCreateReq\(true\)/g)?.length).toBe(2);
    expect(src.match(/setPanel\("connections"\)/g)?.length).toBeGreaterThanOrEqual(2);
    expect(src.match(/setTriggerProjectEdit\(true\)/g)?.length).toBe(2);
    // and no step is a bare div any more
    expect(src).not.toMatch(/<div key=\{item\.step\}/);
  });

  it("the Data panel offers a way to connect the repository it says is missing", async () => {
    const src = await import("fs").then((fs) =>
      fs.readFileSync("src/components/workspace/DataWorkspace.tsx", "utf8"),
    );
    const i = src.indexOf("No repository connected");
    expect(i).toBeGreaterThan(-1);
    const nearby = src.slice(i, i + 1200);
    expect(nearby).toMatch(/Connect a repository/);
    expect(nearby).toMatch(/LoadDemoDataButton/);
  });

  it("the Activity panel refuses a non-owner rather than only hiding its entry", async () => {
    const src = await import("fs").then((fs) =>
      fs.readFileSync("src/app/app/page.tsx", "utf8"),
    );
    // The render branch, not the side-effect that syncs `logsOpen`.
    const i = src.indexOf('if (effectivePanel === "logs") {');
    expect(i).toBeGreaterThan(-1);
    expect(src.slice(i, i + 900)).toMatch(/if \(!isOwner\)/);
  });
});
