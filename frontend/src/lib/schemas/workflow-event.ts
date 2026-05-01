import { z } from "zod";

/**
 * Runtime schemas for messages coming off the SSE wire (T31).
 * These intentionally mirror the TypeScript types but validate on parse
 * to avoid ``as unknown as`` unchecked coercions in component code.
 *
 * Parsers are permissive on unknown trailing fields (default zod behavior)
 * so new backend fields don't break existing consumers.
 */

export const WorkflowEventSchema = z.object({
  workflow_id: z.string(),
  step: z.string(),
  status: z.enum(["started", "completed", "failed", "skipped"]),
  detail: z.string(),
  elapsed_ms: z.number().nullable(),
  timestamp: z.number(),
  pipeline: z.string(),
  extra: z.record(z.string(), z.unknown()).default({}),
});

export type WorkflowEventPayload = z.infer<typeof WorkflowEventSchema>;

export function parseWorkflowEvent(raw: unknown): WorkflowEventPayload | null {
  const result = WorkflowEventSchema.safeParse(raw);
  return result.success ? result.data : null;
}

const TokenUsageSchema = z
  .object({
    prompt_tokens: z.number().optional(),
    completion_tokens: z.number().optional(),
    total_tokens: z.number().optional(),
  })
  .nullable()
  .optional();

export const ChatResponseSchema = z
  .object({
    session_id: z.string(),
    answer: z.string(),
    query: z.string().nullable(),
    query_explanation: z.string().nullable(),
    visualization: z.record(z.string(), z.unknown()).nullable(),
    error: z.string().nullable(),
    workflow_id: z.string().nullable(),
    staleness_warning: z.string().nullable(),
    response_type: z.string().optional(),
    assistant_message_id: z.string().nullable().optional(),
    user_message_id: z.string().nullable().optional(),
    raw_result: z
      .object({
        columns: z.array(z.string()),
        rows: z.array(z.array(z.unknown())),
        total_rows: z.number(),
      })
      .nullable()
      .optional(),
    token_usage: TokenUsageSchema,
    rules_changed: z.boolean().optional(),
    steps_used: z.number().optional(),
    steps_total: z.number().optional(),
    continuation_context: z.string().nullable().optional(),
  })
  .passthrough();

export type ChatResponsePayload = z.infer<typeof ChatResponseSchema>;
