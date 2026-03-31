import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

const mockSetProjects = vi.fn();
const mockSetActiveProject = vi.fn();
const mockSetConnections = vi.fn();
const mockSetActiveConnection = vi.fn();

const mockAppState = {
  sshKeys: [] as unknown[],
  setProjects: mockSetProjects,
  setActiveProject: mockSetActiveProject,
  setConnections: mockSetConnections,
  setActiveConnection: mockSetActiveConnection,
};
vi.mock("@/stores/app-store", () => ({
  useAppStore: Object.assign(
    (selector?: (s: typeof mockAppState) => unknown) =>
      selector ? selector(mockAppState) : mockAppState,
    { setState: vi.fn(), getState: () => mockAppState },
  ),
}));

const mockAuthState = { user: { id: "u1", email: "test@test.com", can_create_projects: true } };
vi.mock("@/stores/auth-store", () => ({
  useAuthStore: Object.assign(
    (selector?: (s: typeof mockAuthState) => unknown) =>
      selector ? selector(mockAuthState) : mockAuthState,
    { setState: vi.fn(), getState: () => mockAuthState },
  ),
}));

vi.mock("@/lib/api", () => ({
  api: {
    projects: { create: vi.fn(), list: vi.fn().mockResolvedValue([]), update: vi.fn() },
    connections: {
      create: vi.fn().mockResolvedValue({ id: "c1", name: "test" }),
      test: vi.fn().mockResolvedValue({ success: true }),
      indexDb: vi.fn().mockResolvedValue({}),
      listByProject: vi.fn().mockResolvedValue([]),
    },
    auth: {
      completeOnboarding: vi.fn().mockResolvedValue({}),
      me: vi.fn().mockResolvedValue({ id: "u1", email: "test@test.com", is_onboarded: true }),
    },
    demo: {
      setup: vi.fn().mockResolvedValue({ project_id: "p1", connection_id: "c1" }),
    },
  },
}));

vi.mock("@/stores/toast-store", () => ({
  toast: vi.fn(),
}));

vi.mock("@/components/ui/Icon", () => ({
  Icon: (p: { name: string }) => <span data-testid={`icon-${p.name}`} />,
}));

const { OnboardingWizard } = await import("@/components/onboarding/OnboardingWizard");

describe("OnboardingWizard", () => {
  const onComplete = vi.fn();

  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("renders step 1 - Connect your database", () => {
    render(<OnboardingWizard onComplete={onComplete} />);
    expect(screen.getByText("Connect your database")).toBeTruthy();
  });

  it("shows all DB type buttons", () => {
    render(<OnboardingWizard onComplete={onComplete} />);
    expect(screen.getByText("PostgreSQL")).toBeTruthy();
    expect(screen.getByText("MySQL")).toBeTruthy();
    expect(screen.getByText("ClickHouse")).toBeTruthy();
    expect(screen.getByText("MongoDB")).toBeTruthy();
  });

  it("shows host and port inputs", () => {
    render(<OnboardingWizard onComplete={onComplete} />);
    expect(screen.getByPlaceholderText("127.0.0.1")).toBeTruthy();
    expect(screen.getByDisplayValue("5432")).toBeTruthy();
  });

  it("shows Skip setup entirely button", () => {
    render(<OnboardingWizard onComplete={onComplete} />);
    expect(screen.getByText("Skip setup entirely")).toBeTruthy();
  });

  it("shows Try demo instead button on step 0", () => {
    render(<OnboardingWizard onComplete={onComplete} />);
    expect(screen.getByText("Try demo instead")).toBeTruthy();
  });

  it("Continue button is disabled when required fields empty", () => {
    render(<OnboardingWizard onComplete={onComplete} />);
    const continueBtn = screen.getByText("Continue");
    expect(continueBtn).toHaveProperty("disabled", true);
  });

  it("Continue enables when host and dbName filled", async () => {
    render(<OnboardingWizard onComplete={onComplete} />);
    const dbNameInput = screen.getByPlaceholderText("my_database");
    await userEvent.type(dbNameInput, "testdb");
    const continueBtn = screen.getByText("Continue");
    expect(continueBtn).toHaveProperty("disabled", false);
  });

  it("shows SSH Tunnel toggle", () => {
    render(<OnboardingWizard onComplete={onComplete} />);
    expect(screen.getByText("SSH Tunnel (Advanced)")).toBeTruthy();
  });

  it("reveals SSH fields when toggle clicked", async () => {
    render(<OnboardingWizard onComplete={onComplete} />);
    await userEvent.click(screen.getByText("SSH Tunnel (Advanced)"));
    expect(screen.getByPlaceholderText("ssh.example.com")).toBeTruthy();
    expect(screen.getByPlaceholderText("ubuntu")).toBeTruthy();
  });

  it("renders 5 step indicators", () => {
    const { container } = render(<OnboardingWizard onComplete={onComplete} />);
    const dots = container.querySelectorAll(".rounded-full.transition-all");
    expect(dots.length).toBe(5);
  });
});
