"use client";

import { cn } from "@/lib/utils";

/**
 * The `ledger` pack's signature element: a chip in a card's title row saying how
 * that card's number is known. Three states, and the rules that decide whether
 * it is honest rather than decorative (AI_PRODUCT_PATTERNS.md §4):
 *
 *  1. Every state must be reachable. If nothing is ever `unverified`, the seal
 *     is a sticker and readers learn to skip it.
 *  2. The label must be derivable from something real. `sealStateFor` below
 *     derives it from the answer's own shape — the SQL it ran, the sources it
 *     retrieved, the staleness the backend reported — never from a second guess
 *     about the first one.
 *  3. It seals a card, not a screen. One badge over twelve numbers hides
 *     exactly the number that needed checking.
 *
 * The word always renders, **in `--ink`**. All three state hues sit under 4.5:1
 * on the light field, so the word carries the meaning and the colour — on the
 * glyph — reinforces it. This comment said exactly that while the component
 * painted the word in the state's colour anyway; see `TONE` for what the
 * measurement found.
 */
export type SealState = "verified" | "inferred" | "unverified";

const LABEL: Record<SealState, string> = {
  verified: "Verified",
  inferred: "Inferred",
  unverified: "Unverified",
};

/**
 * The GLYPH carries the hue; the word does not.
 *
 * Measured 2026-08-16 against the token layer: painting the word in the state's
 * colour gave `Unverified` **2.13:1** on the light panel and `Verified`
 * **3.63:1** — the first below even the 3:1 non-text floor, on the element this
 * whole design is remembered by. The pack says it outright ("the status word
 * inside a chip renders in --ink with the status colour carried by the dot or
 * the fill") and this component was breaking its own rule while its comment
 * claimed otherwise. In ink the same words measure 16-18:1.
 */
const TONE: Record<SealState, string> = {
  verified: "text-info",
  inferred: "text-accent",
  unverified: "text-warn",
};

/** What the seal means, in one line, for the tooltip and the screen reader. */
const MEANING: Record<SealState, string> = {
  verified: "Computed by a query you can open",
  inferred: "Derived from retrieved context, not from a query",
  unverified: "The system cannot say how this was obtained",
};

/** The shape of an answer, reduced to the fields the seal is derived from. */
export interface SealEvidence {
  responseType?: string | null;
  /** The SQL behind the answer — the proof a reader can open. */
  query?: string | null;
  /** Retrieval hits behind a knowledge answer. */
  sourceCount?: number;
  /** The backend's own freshness warning, when it reported one. */
  stalenessWarning?: string | null;
  error?: string | null;
}

/**
 * Derive the seal from evidence the backend actually sends. Pure, so it is
 * tested as behaviour rather than read as a claim.
 */
export function sealStateFor(evidence: SealEvidence): SealState {
  const { responseType, query, sourceCount = 0, stalenessWarning, error } = evidence;

  // A failed, budget-exhausted or paused run cannot say how it knows anything.
  if (error) return "unverified";
  if (
    responseType === "error" ||
    responseType === "stage_failed" ||
    responseType === "step_limit_reached"
  ) {
    return "unverified";
  }

  if (responseType === "sql_result" && query) {
    // A query the reader can open is the strongest evidence this product has —
    // unless the index behind it is stale, which downgrades it rather than
    // hiding it.
    return stalenessWarning ? "inferred" : "verified";
  }

  // A knowledge answer is derived by a step the system can name, and the step
  // is the retrieval. With nothing retrieved, there is no step to name.
  if (sourceCount > 0) return "inferred";

  return "unverified";
}

export interface SealProps {
  state: SealState;
  /** Overrides the default word. Keep it to one word: this sits in a title row. */
  label?: string;
  /** Opens the proof — the SQL, the source, the metric definition. */
  onOpenProof?: () => void;
  className?: string;
}

export function Seal({ state, label, onOpenProof, className }: SealProps) {
  const word = label ?? LABEL[state];
  const classes = cn(
    "inline-flex h-4 items-center gap-1 font-mono text-kicker tracking-kicker uppercase",
    "text-ink transition-colors duration-(--dur) ease-(--ease)",
    className,
  );

  // One glyph per state, because a single ring with a bar through it reads as
  // "forbidden" beside the word VERIFIED — seen in a screenshot of the real
  // component. A check for what was computed, a hollow ring for what was
  // derived, a bar for what the system cannot vouch for. The glyph is
  // decoration on top of the word, never instead of it.
  const glyph =
    state === "verified" ? (
      <svg viewBox="0 0 10 10" className="size-2.5" fill="none" stroke="currentColor" strokeWidth={1.6}>
        <path d="M1.5 5.2 3.9 7.6 8.5 2.6" strokeLinecap="round" strokeLinejoin="round" />
      </svg>
    ) : state === "inferred" ? (
      <span className="block size-2 rounded-full border border-current" />
    ) : (
      <span className="block h-0.5 w-2.5 rounded-full bg-current" />
    );

  const body = (
    <>
      <span aria-hidden="true" className={cn("grid size-2.5 place-items-center", TONE[state])}>
        {glyph}
      </span>
      <span>{word}</span>
    </>
  );

  if (!onOpenProof) {
    return (
      <span className={classes} title={MEANING[state]}>
        {body}
        <span className="sr-only">. {MEANING[state]}</span>
      </span>
    );
  }

  return (
    <button
      type="button"
      onClick={onOpenProof}
      className={cn(classes, "hover:text-accent")}
      aria-label={`${word}. ${MEANING[state]}. Open the proof`}
      title={MEANING[state]}
    >
      {body}
    </button>
  );
}
