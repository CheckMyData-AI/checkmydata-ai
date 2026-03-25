"use client";

import { useState } from "react";

interface ClarificationData {
  question: string;
  question_type: "yes_no" | "multiple_choice" | "numeric_range" | "free_text";
  options?: string[];
  context?: string;
}

interface ClarificationCardProps {
  data: ClarificationData;
  onSubmit: (answer: string) => void;
}

export function ClarificationCard({ data, onSubmit }: ClarificationCardProps) {
  const [answer, setAnswer] = useState("");
  const [submitted, setSubmitted] = useState(false);

  const handleSubmit = () => {
    if (!answer.trim()) return;
    setSubmitted(true);
    onSubmit(answer);
  };

  if (submitted) {
    return (
      <div className="mt-3 p-3 rounded-xl border border-border-default bg-surface-2">
        <p className="text-xs text-text-secondary">You answered: {answer}</p>
      </div>
    );
  }

  return (
    <div className="mt-3 p-3 rounded-xl border border-border-default bg-accent-muted">
      {data.context && (
        <p className="text-xs text-text-secondary mb-2">{data.context}</p>
      )}
      <p className="text-sm font-medium text-text-primary mb-3">{data.question}</p>

      {data.question_type === "yes_no" && (
        <div className="flex gap-2">
          <button
            disabled={submitted}
            onClick={() => { setSubmitted(true); setAnswer("Yes"); onSubmit("Yes"); }}
            className="px-3 py-1.5 rounded-md text-xs font-medium bg-success-muted text-success border border-border-default hover:bg-success-muted disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
          >
            Yes
          </button>
          <button
            disabled={submitted}
            onClick={() => { setSubmitted(true); setAnswer("No"); onSubmit("No"); }}
            className="px-3 py-1.5 rounded-md text-xs font-medium bg-error-muted text-error border border-border-default hover:bg-error-muted disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
          >
            No
          </button>
        </div>
      )}

      {data.question_type === "multiple_choice" && data.options && (
        <div className="space-y-1.5">
          {data.options.map((option) => (
            <button
              key={option}
              disabled={submitted}
              onClick={() => { setSubmitted(true); setAnswer(option); onSubmit(option); }}
              className={`block w-full text-left px-3 py-2 rounded-md text-xs border transition-colors disabled:opacity-50 disabled:cursor-not-allowed ${
                answer === option
                  ? "border-accent bg-accent-muted text-accent-hover"
                  : "border-border-default bg-surface-2 text-text-primary hover:bg-surface-3"
              }`}
            >
              {option}
            </button>
          ))}
        </div>
      )}

      {data.question_type === "free_text" && (
        <div className="flex gap-2">
          <input
            type="text"
            value={answer}
            onChange={(e) => setAnswer(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && handleSubmit()}
            placeholder="Type your answer..."
            aria-label="Your answer"
            maxLength={2000}
            className="flex-1 px-3 py-1.5 rounded-md text-xs bg-surface-1 border border-border-default text-text-primary placeholder:text-text-muted focus:outline-none focus:border-accent"
          />
          <button
            onClick={handleSubmit}
            disabled={!answer.trim()}
            className="px-3 py-1.5 rounded-md text-xs font-medium bg-accent text-white hover:bg-accent-hover disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
          >
            Submit
          </button>
        </div>
      )}

      {data.question_type === "numeric_range" && (
        <div className="flex gap-2">
          <input
            type="number"
            value={answer}
            onChange={(e) => setAnswer(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && handleSubmit()}
            placeholder="Enter a number..."
            aria-label="Numeric answer"
            className="flex-1 px-3 py-1.5 rounded-md text-xs bg-surface-1 border border-border-default text-text-primary placeholder:text-text-muted focus:outline-none focus:border-accent"
          />
          <button
            onClick={handleSubmit}
            disabled={!answer.trim()}
            className="px-3 py-1.5 rounded-md text-xs font-medium bg-accent text-white hover:bg-accent-hover disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
          >
            Submit
          </button>
        </div>
      )}
    </div>
  );
}
