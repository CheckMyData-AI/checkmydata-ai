import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

beforeEach(() => {
  vi.clearAllMocks();
});

async function renderCard(
  data: {
    question: string;
    question_type: "yes_no" | "multiple_choice" | "numeric_range" | "free_text";
    options?: string[];
    context?: string;
  },
  onSubmit = vi.fn(),
) {
  const { ClarificationCard } = await import(
    "@/components/chat/ClarificationCard"
  );
  return { ...render(<ClarificationCard data={data} onSubmit={onSubmit} />), onSubmit };
}

describe("ClarificationCard", () => {
  it("renders yes_no question with two buttons", async () => {
    await renderCard({
      question: "Is this revenue in dollars?",
      question_type: "yes_no",
    });
    expect(screen.getByText("Is this revenue in dollars?")).toBeTruthy();
    expect(screen.getByText("Yes")).toBeTruthy();
    expect(screen.getByText("No")).toBeTruthy();
  });

  it("calls onSubmit with 'Yes' on yes_no click", async () => {
    const user = userEvent.setup();
    const { onSubmit } = await renderCard({
      question: "Confirm?",
      question_type: "yes_no",
    });
    await user.click(screen.getByText("Yes"));
    expect(onSubmit).toHaveBeenCalledWith("Yes");
  });

  it("calls onSubmit with 'No' on yes_no click", async () => {
    const user = userEvent.setup();
    const { onSubmit } = await renderCard({
      question: "Confirm?",
      question_type: "yes_no",
    });
    await user.click(screen.getByText("No"));
    expect(onSubmit).toHaveBeenCalledWith("No");
  });

  it("renders multiple_choice options", async () => {
    await renderCard({
      question: "Which currency?",
      question_type: "multiple_choice",
      options: ["USD", "EUR", "GBP"],
    });
    expect(screen.getByText("USD")).toBeTruthy();
    expect(screen.getByText("EUR")).toBeTruthy();
    expect(screen.getByText("GBP")).toBeTruthy();
  });

  it("selects multiple_choice option", async () => {
    const user = userEvent.setup();
    const { onSubmit } = await renderCard({
      question: "Pick one",
      question_type: "multiple_choice",
      options: ["A", "B"],
    });
    await user.click(screen.getByText("B"));
    expect(onSubmit).toHaveBeenCalledWith("B");
  });

  it("renders free_text input and submit", async () => {
    const user = userEvent.setup();
    const { onSubmit } = await renderCard({
      question: "What do you expect?",
      question_type: "free_text",
    });
    const input = screen.getByPlaceholderText("Type your answer...");
    await user.type(input, "About 1500");
    await user.click(screen.getByText("Submit"));
    expect(onSubmit).toHaveBeenCalledWith("About 1500");
  });

  it("renders numeric_range input", async () => {
    await renderCard({
      question: "How many?",
      question_type: "numeric_range",
    });
    expect(screen.getByPlaceholderText("Enter a number...")).toBeTruthy();
  });

  it("shows context when provided", async () => {
    await renderCard({
      question: "Confirm?",
      question_type: "yes_no",
      context: "Based on last month's data",
    });
    expect(screen.getByText("Based on last month's data")).toBeTruthy();
  });

  it("shows submitted state after answering", async () => {
    const user = userEvent.setup();
    await renderCard({
      question: "Confirm?",
      question_type: "yes_no",
    });
    await user.click(screen.getByText("Yes"));
    expect(screen.getByText("You answered: Yes")).toBeTruthy();
  });
});
