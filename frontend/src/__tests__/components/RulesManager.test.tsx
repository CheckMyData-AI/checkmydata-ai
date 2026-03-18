import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useAppStore } from "@/stores/app-store";

vi.mock("@/lib/api", () => ({
  api: {
    rules: {
      list: vi.fn().mockResolvedValue([]),
      create: vi.fn(),
      update: vi.fn(),
      delete: vi.fn(),
    },
  },
}));

vi.mock("@/stores/toast-store", () => ({
  toast: vi.fn(),
}));

vi.mock("@/components/ui/ConfirmModal", () => ({
  confirmAction: vi.fn().mockResolvedValue(true),
}));

vi.mock("@/components/ui/Spinner", () => ({
  Spinner: () => <div data-testid="spinner">Loading...</div>,
}));

vi.mock("@/components/ui/Icon", () => ({
  Icon: ({ name }: { name: string }) => <span data-testid={`icon-${name}`} />,
}));

vi.mock("@/components/ui/ActionButton", () => ({
  ActionButton: ({
    icon,
    title,
    onClick,
  }: {
    icon: string;
    title: string;
    onClick: (e: React.MouseEvent) => void;
  }) => (
    <button data-testid={`action-${icon}`} title={title} onClick={onClick}>
      {icon}
    </button>
  ),
}));

const { api } = await import("@/lib/api");

function makeRule(overrides: Record<string, unknown> = {}) {
  return {
    id: "r1",
    project_id: "p1",
    name: "Test Rule",
    content: "Some content",
    format: "markdown",
    is_default: false,
    ...overrides,
  };
}

beforeEach(() => {
  vi.clearAllMocks();
  useAppStore.setState({ activeProject: { id: "p1", name: "Test" } as never, rulesVersion: 0 });
  (api.rules.list as ReturnType<typeof vi.fn>).mockResolvedValue([]);
});

async function renderRulesManager() {
  const { RulesManager } = await import("@/components/rules/RulesManager");
  return render(<RulesManager />);
}

describe("RulesManager", () => {
  it("renders New button", async () => {
    await renderRulesManager();
    await waitFor(() => {
      expect(screen.getByText("New")).toBeInTheDocument();
    });
  });

  it("shows empty state message when no rules", async () => {
    await renderRulesManager();
    await waitFor(() => {
      expect(screen.getByText("No custom rules yet")).toBeInTheDocument();
    });
  });

  it("rule items render with name", async () => {
    const rules = [
      makeRule({ id: "r1", name: "Alpha Rule" }),
      makeRule({ id: "r2", name: "Beta Rule" }),
    ];
    (api.rules.list as ReturnType<typeof vi.fn>).mockResolvedValue(rules);

    await renderRulesManager();
    await waitFor(() => {
      expect(screen.getByText("Alpha Rule")).toBeInTheDocument();
      expect(screen.getByText("Beta Rule")).toBeInTheDocument();
    });
  });

  it("edit button present for each rule", async () => {
    (api.rules.list as ReturnType<typeof vi.fn>).mockResolvedValue([makeRule()]);
    await renderRulesManager();
    await waitFor(() => {
      expect(screen.getByTitle("Edit rule")).toBeInTheDocument();
    });
  });

  it("delete button present for each rule", async () => {
    (api.rules.list as ReturnType<typeof vi.fn>).mockResolvedValue([makeRule()]);
    await renderRulesManager();
    await waitFor(() => {
      expect(screen.getByTitle("Delete rule")).toBeInTheDocument();
    });
  });

  it("clicking New opens create form with name and content fields", async () => {
    await renderRulesManager();
    await waitFor(() => expect(screen.getByText("New")).toBeInTheDocument());
    await userEvent.click(screen.getByText("New"));
    expect(screen.getByLabelText("Rule name")).toBeInTheDocument();
    expect(screen.getByLabelText("Rule content")).toBeInTheDocument();
    expect(screen.getByText("Create")).toBeInTheDocument();
  });

  it("clicking edit opens form and cancel returns to list", async () => {
    const rule = makeRule({ id: "r1", name: "My Rule", content: "contents" });
    (api.rules.list as ReturnType<typeof vi.fn>).mockResolvedValue([rule]);
    await renderRulesManager();
    await waitFor(() => expect(screen.getByText("My Rule")).toBeInTheDocument());

    await userEvent.click(screen.getByTitle("Edit rule"));
    expect(screen.getByDisplayValue("My Rule")).toBeInTheDocument();
    expect(screen.getByText("Cancel")).toBeInTheDocument();

    await userEvent.click(screen.getByText("Cancel"));
    expect(screen.queryByDisplayValue("My Rule")).not.toBeInTheDocument();
  });

  it("create form shows Create button", async () => {
    await renderRulesManager();
    await waitFor(() => expect(screen.getByText("New")).toBeInTheDocument());
    await userEvent.click(screen.getByText("New"));
    expect(screen.getByText("Create")).toBeInTheDocument();
  });
});
