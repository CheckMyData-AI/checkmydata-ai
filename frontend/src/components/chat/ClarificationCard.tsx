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
      <div className="mt-3 p-3 rounded-lg border border-zinc-700/50 bg-zinc-800/50">
        <p className="text-xs text-zinc-400">You answered: {answer}</p>
      </div>
    );
  }

  return (
    <div className="mt-3 p-3 rounded-lg border border-blue-800/40 bg-blue-950/20">
      {data.context && (
        <p className="text-xs text-zinc-400 mb-2">{data.context}</p>
      )}
      <p className="text-sm font-medium text-zinc-200 mb-3">{data.question}</p>

      {data.question_type === "yes_no" && (
        <div className="flex gap-2">
          <button
            disabled={submitted}
            onClick={() => { setSubmitted(true); setAnswer("Yes"); onSubmit("Yes"); }}
            className="px-3 py-1.5 rounded-md text-xs font-medium bg-emerald-900/40 text-emerald-400 border border-emerald-800/40 hover:bg-emerald-900/60 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
          >
            Yes
          </button>
          <button
            disabled={submitted}
            onClick={() => { setSubmitted(true); setAnswer("No"); onSubmit("No"); }}
            className="px-3 py-1.5 rounded-md text-xs font-medium bg-red-900/40 text-red-400 border border-red-800/40 hover:bg-red-900/60 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
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
                  ? "border-blue-600 bg-blue-900/30 text-blue-300"
                  : "border-zinc-700/50 bg-zinc-800/50 text-zinc-300 hover:bg-zinc-700/50"
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
            maxLength={2000}
            className="flex-1 px-3 py-1.5 rounded-md text-xs bg-zinc-900 border border-zinc-700 text-zinc-200 placeholder:text-zinc-500 focus:outline-none focus:border-blue-600"
          />
          <button
            onClick={handleSubmit}
            disabled={!answer.trim()}
            className="px-3 py-1.5 rounded-md text-xs font-medium bg-blue-600 text-white hover:bg-blue-500 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
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
            className="flex-1 px-3 py-1.5 rounded-md text-xs bg-zinc-900 border border-zinc-700 text-zinc-200 placeholder:text-zinc-500 focus:outline-none focus:border-blue-600"
          />
          <button
            onClick={handleSubmit}
            disabled={!answer.trim()}
            className="px-3 py-1.5 rounded-md text-xs font-medium bg-blue-600 text-white hover:bg-blue-500 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
          >
            Submit
          </button>
        </div>
      )}
    </div>
  );
}
