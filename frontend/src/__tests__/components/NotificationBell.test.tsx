import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

vi.mock("@/components/ui/Icon", () => ({
  Icon: ({ name }: { name: string }) => <span data-testid={`icon-${name}`} />,
}));

vi.mock("@/lib/api", () => ({
  api: {
    notifications: {
      count: vi.fn().mockResolvedValue({ count: 0 }),
      list: vi.fn().mockResolvedValue([]),
      markRead: vi.fn().mockResolvedValue(undefined),
      markAllRead: vi.fn().mockResolvedValue(undefined),
    },
  },
}));

const { api } = await import("@/lib/api");

beforeEach(() => {
  vi.clearAllMocks();
  vi.mocked(api.notifications.count).mockResolvedValue({ count: 0 });
  vi.mocked(api.notifications.list).mockResolvedValue([]);
});

async function renderBell() {
  const { NotificationBell } = await import("@/components/ui/NotificationBell");
  return render(<NotificationBell />);
}

describe("NotificationBell", () => {
  it("renders bell icon", async () => {
    await renderBell();
    expect(screen.getByRole("button", { name: "Notifications" })).toBeInTheDocument();
    expect(screen.getByTestId("icon-bell")).toBeInTheDocument();
  });

  it("shows badge when count > 0", async () => {
    vi.mocked(api.notifications.count).mockResolvedValue({ count: 5 });
    await renderBell();
    await waitFor(() => {
      expect(screen.getByText("5")).toBeInTheDocument();
    });
  });

  it("shows no badge when count is 0", async () => {
    vi.mocked(api.notifications.count).mockResolvedValue({ count: 0 });
    await renderBell();
    await waitFor(() => {
      expect(api.notifications.count).toHaveBeenCalled();
    });
    const btn = screen.getByRole("button", { name: "Notifications" });
    expect(btn.querySelectorAll("span")).toHaveLength(1);
  });

  it("opens dropdown on click and fetches list", async () => {
    const user = userEvent.setup();
    const notif = {
      id: "n1",
      user_id: "u1",
      project_id: "p1",
      title: "Hello",
      body: "Body text",
      type: "info",
      is_read: false,
      created_at: new Date(Date.now() - 120_000).toISOString(),
    };
    vi.mocked(api.notifications.list).mockResolvedValue([notif]);
    await renderBell();
    await user.click(screen.getByRole("button", { name: "Notifications" }));
    await waitFor(() => {
      expect(api.notifications.list).toHaveBeenCalledWith(false);
    });
    expect(screen.getByText("Notifications")).toBeInTheDocument();
  });

  it("shows notification title, body, and relative time", async () => {
    const user = userEvent.setup();
    const created = new Date(Date.now() - 5 * 60_000).toISOString();
    vi.mocked(api.notifications.list).mockResolvedValue([
      {
        id: "n1",
        user_id: "u1",
        project_id: "p1",
        title: "Alert title",
        body: "Alert body",
        type: "info",
        is_read: true,
        created_at: created,
      },
    ]);
    await renderBell();
    await user.click(screen.getByRole("button", { name: "Notifications" }));
    await waitFor(() => {
      expect(screen.getByText("Alert title")).toBeInTheDocument();
    });
    expect(screen.getByText("Alert body")).toBeInTheDocument();
    expect(screen.getByText("5m ago")).toBeInTheDocument();
  });
});
