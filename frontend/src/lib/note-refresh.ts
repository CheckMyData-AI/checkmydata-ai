import type { RawResult } from "@/stores/app-store";

/**
 * The chat message a re-run saved query posts (SCN-069).
 *
 * It used to repeat the note's saved `answer_text` beside the fresh rows — prose
 * written about an earlier result, presented as if it described this one. A refresh
 * says what was re-run and how much came back; the numbers are in the table.
 */
export function refreshedNoteMessage(title: string, result: RawResult | null): string {
  if (!result) return `[Refreshed] ${title}\n\nThe saved query ran again; no result came back.`;
  const n = result.total_rows ?? result.rows?.length ?? 0;
  const rows = n === 1 ? "1 row" : `${n.toLocaleString("en-US")} rows`;
  return (
    `[Refreshed] ${title}\n\nThe saved query ran again and returned ${rows}. ` +
    "The note's saved answer described an earlier result, so it is not repeated here."
  );
}
