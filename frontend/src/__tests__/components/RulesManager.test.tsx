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
  useAppStore.setState({ activeProject: { id: "p1", name: "Test" } as never, rulesVersion: 0, userRole: "owner" });
  (api.rules.list as ReturnType<typeof vi.fn>).mockResolvedValue([]);
});

async function renderRulesManager() {
  const { RulesManager } = await import("@/components/rules/RulesManager");
  return render(<RulesManager />);
}

describe("RulesManager", () => {
  it("opens create form when createRequested is true", async () => {
    const { RulesManager } = await import("@/components/rules/RulesManager");
    const onHandled = vi.fn();
    render(<RulesManager createRequested={true} onCreateHandled={onHandled} />);
    await waitFor(() => {
      expect(screen.getByLabelText("Rule name")).toBeInTheDocument();
    });
    expect(onHandled).toHaveBeenCalled();
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

  it("create form has name and content fields via createRequested", async () => {
    const { RulesManager } = await import("@/components/rules/RulesManager");
    render(<RulesManager createRequested={true} onCreateHandled={() => {}} />);
    await waitFor(() => {
      expect(screen.getByLabelText("Rule name")).toBeInTheDocument();
      expect(screen.getByLabelText("Rule content")).toBeInTheDocument();
      expect(screen.getByText("Create")).toBeInTheDocument();
    });
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

  it("create form shows Create button via createRequested", async () => {
    const { RulesManager } = await import("@/components/rules/RulesManager");
    render(<RulesManager createRequested={true} onCreateHandled={() => {}} />);
    await waitFor(() => {
      expect(screen.getByText("Create")).toBeInTheDocument();
    });
  });

  it("clicking a rule row opens the edit form", async () => {
    const rule = makeRule({ id: "r1", name: "Row Click Rule", content: "row content" });
    (api.rules.list as ReturnType<typeof vi.fn>).mockResolvedValue([rule]);
    await renderRulesManager();
    await waitFor(() => expect(screen.getByText("Row Click Rule")).toBeInTheDocument());

    await userEvent.click(screen.getByText("Row Click Rule"));
    await waitFor(() => {
      expect(screen.getByDisplayValue("Row Click Rule")).toBeInTheDocument();
      expect(screen.getByDisplayValue("row content")).toBeInTheDocument();
      expect(screen.getByText("Save")).toBeInTheDocument();
    });
  });

  it("Save button is disabled when no changes have been made", async () => {
    const rule = makeRule({ id: "r1", name: "Unchanged", content: "original" });
    (api.rules.list as ReturnType<typeof vi.fn>).mockResolvedValue([rule]);
    await renderRulesManager();
    await waitFor(() => expect(screen.getByText("Unchanged")).toBeInTheDocument());

    await userEvent.click(screen.getByText("Unchanged"));
    await waitFor(() => expect(screen.getByText("Save")).toBeDisabled());
  });

  it("Save button becomes enabled after modifying content", async () => {
    const rule = makeRule({ id: "r1", name: "Editable", content: "old text" });
    (api.rules.list as ReturnType<typeof vi.fn>).mockResolvedValue([rule]);
    await renderRulesManager();
    await waitFor(() => expect(screen.getByText("Editable")).toBeInTheDocument());

    await userEvent.click(screen.getByText("Editable"));
    await waitFor(() => expect(screen.getByText("Save")).toBeDisabled());

    const textarea = screen.getByLabelText("Rule content");
    await userEvent.clear(textarea);
    await userEvent.type(textarea, "new text");
    await waitFor(() => expect(screen.getByText("Save")).toBeEnabled());
  });

  it("Save button becomes enabled after modifying name", async () => {
    const rule = makeRule({ id: "r1", name: "OldName", content: "content" });
    (api.rules.list as ReturnType<typeof vi.fn>).mockResolvedValue([rule]);
    await renderRulesManager();
    await waitFor(() => expect(screen.getByText("OldName")).toBeInTheDocument());

    await userEvent.click(screen.getByText("OldName"));
    await waitFor(() => expect(screen.getByText("Save")).toBeDisabled());

    const nameInput = screen.getByLabelText("Rule name");
    await userEvent.clear(nameInput);
    await userEvent.type(nameInput, "NewName");
    await waitFor(() => expect(screen.getByText("Save")).toBeEnabled());
  });

  it("viewer clicking a rule row opens read-only view", async () => {
    useAppStore.setState({ userRole: "viewer" });
    const rule = makeRule({ id: "r1", name: "View Only Rule", content: "read-only content" });
    (api.rules.list as ReturnType<typeof vi.fn>).mockResolvedValue([rule]);
    await renderRulesManager();
    await waitFor(() => expect(screen.getByText("View Only Rule")).toBeInTheDocument());

    await userEvent.click(screen.getByText("View Only Rule"));
    await waitFor(() => {
      expect(screen.getByText("read-only content")).toBeInTheDocument();
      expect(screen.queryByLabelText("Rule name")).not.toBeInTheDocument();
      expect(screen.queryByText("Save")).not.toBeInTheDocument();
    });
  });
});
