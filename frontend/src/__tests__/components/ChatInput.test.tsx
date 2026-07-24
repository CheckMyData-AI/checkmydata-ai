import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { ChatInput } from "@/components/chat/ChatInput";

const onSend = vi.fn();

beforeEach(() => {
  vi.clearAllMocks();
});

describe("ChatInput", () => {
  it("renders textarea input", () => {
    render(<ChatInput onSend={onSend} />);
    expect(screen.getByRole("textbox")).toBeInTheDocument();
  });

  it("typing updates value", async () => {
    render(<ChatInput onSend={onSend} />);
    const textarea = screen.getByRole("textbox");
    await userEvent.type(textarea, "hello");
    expect(textarea).toHaveValue("hello");
  });

  it("submit triggers callback on button click", async () => {
    render(<ChatInput onSend={onSend} />);
    const textarea = screen.getByRole("textbox");
    await userEvent.type(textarea, "test query");
    await userEvent.click(screen.getByLabelText("Send message"));
    expect(onSend).toHaveBeenCalledWith("test query");
  });

  it("empty input does not submit", async () => {
    render(<ChatInput onSend={onSend} />);
    await userEvent.click(screen.getByLabelText("Send message"));
    expect(onSend).not.toHaveBeenCalled();
  });

  it("disabled state disables textarea and button", () => {
    render(<ChatInput onSend={onSend} disabled />);
    expect(screen.getByRole("textbox")).toBeDisabled();
    expect(screen.getByLabelText("Send message")).toBeDisabled();
  });

  it("shows custom placeholder text", () => {
    render(<ChatInput onSend={onSend} placeholder="Type here..." />);
    expect(screen.getByPlaceholderText("Type here...")).toBeInTheDocument();
  });

  it("send button has minimum 44px touch target", () => {
    render(<ChatInput onSend={onSend} />);
    const btn = screen.getByLabelText("Send message");
    expect(btn.className).toContain("min-h-[44px]");
    expect(btn.className).toContain("min-w-[44px]");
  });

  it("auto-grows with content up to the cap, then scrolls (SCN-041)", async () => {
    render(<ChatInput onSend={onSend} />);
    const textarea = screen.getByRole("textbox");

    Object.defineProperty(textarea, "scrollHeight", {
      value: 96,
      configurable: true,
    });
    await userEvent.type(textarea, "line one\nline two");
    expect(textarea.style.height).toBe("96px");

    Object.defineProperty(textarea, "scrollHeight", {
      value: 500,
      configurable: true,
    });
    await userEvent.type(textarea, "\nmore");
    // Capped at max-h-40 (160px); overflow-y-auto keeps the rest scrollable.
    expect(textarea.style.height).toBe("160px");
    expect(textarea.className).toContain("overflow-y-auto");
  });

  it("resets its height after sending", async () => {
    render(<ChatInput onSend={onSend} />);
    const textarea = screen.getByRole("textbox");

    Object.defineProperty(textarea, "scrollHeight", {
      value: 120,
      configurable: true,
    });
    await userEvent.type(textarea, "multi\nline\nquestion");
    expect(textarea.style.height).toBe("120px");

    Object.defineProperty(textarea, "scrollHeight", {
      value: 52,
      configurable: true,
    });
    await userEvent.click(screen.getByLabelText("Send message"));
    expect(onSend).toHaveBeenCalled();
    expect(textarea.style.height).toBe("52px");
  });

  it("Enter submits, Shift+Enter inserts a newline (submit UX unchanged)", async () => {
    render(<ChatInput onSend={onSend} />);
    const textarea = screen.getByRole("textbox");
    await userEvent.type(textarea, "first line{Shift>}{Enter}{/Shift}second");
    expect(onSend).not.toHaveBeenCalled();
    await userEvent.type(textarea, "{Enter}");
    expect(onSend).toHaveBeenCalledWith("first line\nsecond");
  });
});
