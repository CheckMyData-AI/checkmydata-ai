import { render, screen, fireEvent, cleanup } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { ConnectionSelector } from "@/components/connections/ConnectionSelector";
import { useAppStore } from "@/stores/app-store";

vi.mock("@/lib/api", () => ({
  api: {
    connections: {
      indexDbStatus: vi.fn().mockResolvedValue({ is_indexed: false }),
      syncStatus: vi.fn().mockResolvedValue({ is_synced: false }),
      learningsStatus: vi.fn().mockResolvedValue({ total_active: 0 }),
    },
  },
}));

afterEach(cleanup);
beforeEach(() => {
  useAppStore.setState({
    activeProject: { id: "p1", name: "Proj" },
    connections: [],
    activeConnection: null,
    sshKeys: [],
  } as never);
});

describe("connection autofill", () => {
  it("autofills host/port/db/user and detects type from a pasted string", () => {
    render(<ConnectionSelector createRequested onCreateHandled={() => {}} />);
    const box = screen.getByLabelText(/paste a connection string/i) as HTMLInputElement;
    fireEvent.change(box, {
      target: { value: "postgres://alice:s3cret@db.example.com:6543/orders" },
    });
    expect((screen.getByLabelText(/database host/i) as HTMLInputElement).value).toBe("db.example.com");
    expect((screen.getByLabelText(/database port/i) as HTMLInputElement).value).toBe("6543");
    expect((screen.getByLabelText(/database name/i) as HTMLInputElement).value).toBe("orders");
    expect((screen.getByLabelText(/database username/i) as HTMLInputElement).value).toBe("alice");
    expect(screen.getByText(/detected: postgres/i)).toBeInTheDocument();
  });
});
