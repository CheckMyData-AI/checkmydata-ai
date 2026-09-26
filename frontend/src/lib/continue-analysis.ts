/**
 * "Continue analysis" re-asks the question that was cut short (SCN-055).
 *
 * The click also posts a local user bubble reading `CONTINUE_LABEL`, so taking the
 * LAST user message made a second consecutive click send "Continue analysis" as the
 * question — the original was lost (B-27 D1). The label is skipped; the stored
 * history keeps the real question, so a reload is unaffected.
 */
export const CONTINUE_LABEL = "Continue analysis";

export function questionToContinue(
  messages: ReadonlyArray<{ role: string; content: string }>,
): string {
  for (let i = messages.length - 1; i >= 0; i--) {
    const m = messages[i];
    if (m.role === "user" && m.content.trim() && m.content !== CONTINUE_LABEL) {
      return m.content;
    }
  }
  return "Continue the analysis";
}
