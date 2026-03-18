import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useAppStore } from "@/stores/app-store";

vi.mock("@/lib/api", () => ({
  api: {
    sshKeys: {
      list: vi.fn().mockResolvedValue([]),
      create: vi.fn(),
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

function makeSshKey(overrides: Record<string, unknown> = {}) {
  return {
    id: "k1",
    name: "my-key",
    fingerprint: "SHA256:abcdefgh12345678",
    key_type: "ed25519",
    created_at: "2025-01-01T00:00:00Z",
    ...overrides,
  };
}

beforeEach(() => {
  vi.clearAllMocks();
  useAppStore.setState({ sshKeys: [] });
  (api.sshKeys.list as ReturnType<typeof vi.fn>).mockResolvedValue([]);
});

async function renderSshKeyManager() {
  const { SshKeyManager } = await import("@/components/ssh/SshKeyManager");
  return render(<SshKeyManager />);
}

describe("SshKeyManager", () => {
  it("renders Add button", async () => {
    await renderSshKeyManager();
    await waitFor(() => {
      expect(screen.getByText("Add")).toBeInTheDocument();
    });
  });

  it("shows empty state when no keys", async () => {
    await renderSshKeyManager();
    await waitFor(() => {
      expect(screen.getByText("No SSH keys added yet")).toBeInTheDocument();
    });
  });

  it("renders key items from store", async () => {
    useAppStore.setState({
      sshKeys: [
        makeSshKey({ id: "k1", name: "prod-key" }),
        makeSshKey({ id: "k2", name: "dev-key" }),
      ] as never,
    });
    await renderSshKeyManager();
    await waitFor(() => {
      expect(screen.getByText("prod-key")).toBeInTheDocument();
      expect(screen.getByText("dev-key")).toBeInTheDocument();
    });
  });

  it("delete button present per key", async () => {
    useAppStore.setState({ sshKeys: [makeSshKey()] as never });
    await renderSshKeyManager();
    await waitFor(() => {
      expect(screen.getByTitle("Delete key")).toBeInTheDocument();
    });
  });

  it("clicking Add opens create form with name and key fields", async () => {
    await renderSshKeyManager();
    await waitFor(() => expect(screen.getByText("Add")).toBeInTheDocument());
    await userEvent.click(screen.getByText("Add"));
    expect(screen.getByLabelText("Key name")).toBeInTheDocument();
    expect(screen.getByLabelText("Private key")).toBeInTheDocument();
  });

  it("create form has Add Key submit button", async () => {
    await renderSshKeyManager();
    await waitFor(() => expect(screen.getByText("Add")).toBeInTheDocument());
    await userEvent.click(screen.getByText("Add"));
    expect(screen.getByText("Add Key")).toBeInTheDocument();
  });
});
