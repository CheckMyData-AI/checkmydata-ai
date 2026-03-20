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
});
