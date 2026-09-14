# What the index knows, what it guesses, and what it must compute

**2026-09-14 · a measurement, then a design.** Written against production v410 and against a
working integration that reads the same database, so every claim below is checkable.

The question: the product indexes a database and a repository into a knowledge base so an
agent can answer questions about them. **Is what it stores the kind of thing that makes an
answer correct?** The way to find out is not to read the pipeline; it is to find someone who
already had to know this database, write down what they needed, and compare.

---

## 1. The control: a working integration over the same database

`sshlg-personal-os/automations/pl/` builds a P&L dashboard from the same MySQL. It is a
useful control for three reasons: it reads the same tables, it was reconciled against a
human's spreadsheet to within 2% on two independent months, and **it contains no LLM at
all** — `grep -rniE "openai|anthropic|llm|gpt|claude|prompt"` over its source returns
nothing. Every number is `SUM`/`COUNT` plus Python arithmetic.

Reverse-engineering it yields **29 facts about this database that `SHOW CREATE TABLE`
cannot tell you**. Their provenance is the interesting part:

| Where the fact came from | Share |
|---|---|
| reading the *other* repository's PHP (who writes `was_handled`, which providers exist) | ~⅓ |
| **measuring production** (payment lag distribution, provider case, dead export dates, a missing index, the currency mix) | ~⅓ |
| reconciling against an artefact outside both systems (the operator's spreadsheet) | ~⅓ |

The middle third is the one this product can automate today and does not.

## 2. What the knowledge base actually holds

Measured on production, 2026-09-14:

| Layer | Volume | Character |
|---|---|---|
| `knowledge_docs` | 782 | **536 are migration history** covering 33 distinct tables; 230 source; 16 are build output, vendor code and minified assets |
| — of those | **25** | say, in prose, that the file has nothing to do with the database. Three of them are the *entire* `query_pattern` corpus: `webpack.mix.js`, `axios.min.js`, a translation bundle |
| `db_index` | 214 tables | `business_description`, `query_hints`, `data_patterns` generated for **214/214**; **140 (65%)** contain "possibly", "might", "suggests", "appears to" |
| — measured columns | 1 628 / 1 707 (95.4%) | but distributed unevenly: `payment_histories` has 4 of 16, `purchases` has **0 of 25** |
| `code_db_sync` | 254 rows | 31 `matched`, 118 `unknown`; for every purchase-related table: confidence 1, no filters, no value mappings |
| `doc_embeddings` | 47 865 | 42 341 of them code symbols, restored 2026-09-14 after three days at zero |

## 3. The comparison, on the table the question is about

**What the index stores for `purchases`, in full:**

> "Use `was_handled = 1` and `deleted_at IS NULL` to filter for valid purchases. Join with
> `subscription_users` for full revenue calculations. Use `created_at` for date filtering,
> ensuring data is post-2023-01-01. **The `amount` column should be divided by 100 to
> convert from cents to dollars.**"

Against the control:

| Claim | Verdict |
|---|---|
| `was_handled = 1`, `deleted_at IS NULL` | **correct**, and these are the two most important filters of the 29 |
| `amount` is in cents | **correct** |
| …"to convert from cents **to dollars**" | **wrong, and expensively so.** `amount` is cents *of `currency`*, and there is no USD column anywhere in the database. Since July 2026 one provider settles in BRL, MXN and NGN. Summing those cents as dollars turned a real ≈$330 into $22 535 — the single most expensive error the control had to fix |
| "Join with `subscription_users` for full revenue calculations" | **unverifiable and unused.** The working integration never joins that table |
| post-2023-01-01 | plausible, uncited |

**And `payment_histories` — the trap.** The control's first finding is that this table is
*not* the revenue table: it records movement history including internal write-offs and
reserves, and is off by 4.3× for one month and by a *different* factor every other month.
The index describes it as *"historical payment records for users, including transaction
details"* and its hints **recommend using it**: *"Filter by `created_at`… Consider
`payment_type` for filtering specific transaction types."* There is no warning.

An agent asked "how much revenue last month" that lands on `payment_histories` will produce
a number several times wrong, with a confident sentence attached and no caveat — because
nothing in the knowledge base knows to object.

## 4. The diagnosis

**The index asks a model to guess what it could have measured, and stores the guess where a
measurement belongs.**

Every claim in the `purchases` hint is a query the product's own connector could run:

| Claim | The query that settles it | What it would have found |
|---|---|---|
| `was_handled` is the validity flag | `SELECT was_handled, COUNT(*) FROM purchases GROUP BY 1` | the flag is binary and how the rows split |
| `deleted_at IS NULL` | null rate of `deleted_at` | whether soft delete is actually used |
| `amount` ÷ 100 = dollars | `SELECT currency, COUNT(*), MIN(amount), MAX(amount) FROM purchases GROUP BY 1` | **the multi-currency mix — this one query kills the expensive claim** |
| data valid post-2023-01-01 | `MIN(created_at)`, rows per year | whether the cut-off is real |

The third row is the argument in one line. One `GROUP BY currency` — a query this product
runs by the thousand during indexing — would have prevented the worst error on the list. It
asked a model instead, and the model answered plausibly and wrongly.

Three structural consequences follow, each measurable:

1. **Measured and guessed live in the same field and are indistinguishable.** An agent
   reading "possibly indicating refunds" cannot tell whether anyone counted. 65% of the
   generated text hedges, which is the model being honest about a doubt the pipeline then
   discards.
2. **The corpus is organised by source file, not by subject.** 536 documents describe
   migrations — one historical change each, 16 per table on average, for 33 of 214 tables.
   A question about purchases needs one current statement per table, not sixteen historical
   ones about a third of the schema.
3. **A generated non-answer is indexed like an answer.** 25 documents say the file has
   nothing to do with the database. They cost tokens to write and now compete for retrieval
   budget with documents that do.

## 5. The design: a table fact is a claim with a receipt

Script-first, applied to indexing. The unit stops being "prose about a file" and becomes a
**TableFact** — a claim, the query that produced it, and the result:

```python
@dataclass(frozen=True)
class TableFact:
    table: str
    kind: Literal["cardinality", "value_domain", "null_rate", "range", "unit",
                  "relationship", "freshness", "usage"]
    claim: str                    # "amount is stored in minor units of `currency`"
    sql: str                      # the statement that established it
    result: dict                  # what it returned — the receipt
    measured_at: datetime
    confidence: Literal["measured", "derived", "asserted"]
```

Three confidence levels, and they are not a scale — they are three different things:

- **`measured`** — a query ran and this is what it returned. Not arguable.
- **`derived`** — computed from measured facts by deterministic code (`amount` is
  multi-currency *because* `GROUP BY currency` returned five values).
- **`asserted`** — a model or a person said so, no query behind it. Kept, clearly labelled,
  and **never presented to the answering agent as equal to a measurement**.

Today everything is effectively `asserted` and nothing says so.

### The probe set: what to measure for every table, once

A fixed, cheap battery — no LLM, ~10 queries per table, all bounded:

| Probe | Query shape | Answers |
|---|---|---|
| shape | `COUNT(*)`, per-column `null_rate` | is the column used at all |
| value domain | `GROUP BY col` with a cardinality cap | is it an enum, and what do the values look like |
| **unit** | `GROUP BY currency-ish col` × `MIN/MAX/AVG` of the money-ish col | **minor units? one currency or many?** |
| range | `MIN/MAX` on every date and numeric | when does the data start, is there a cut-off |
| monotonic key | `corr(id, created_at)` on a sample | can a date window be bracketed by primary key |
| index reality | `SHOW INDEX` vs the columns queries filter on | will a date predicate scan |
| soft delete | null rate of `deleted_at`-shaped columns | is the filter real |
| flag split | `GROUP BY` each boolean-ish column | is `was_handled=1` the majority or the exception |
| relationship | FK candidate + fan-out ratio | will a join multiply rows |
| freshness | `MAX(timestamp)` per table | is this table still filling, or dead like `zzz_*` |

Each one is a `TableFact` with `confidence="measured"`. Together they settle, without a
model, items 3, 4, 5, 7, 8, 13, 14, 17, 18, 19 and 26 of the control's 29 — **eleven of the
twenty-nine, and including the expensive one.**

### What the model is still for

It is good at exactly the things a probe cannot do, and it should be asked *only* those,
with the measurements in front of it:

- naming what a table is *for*, in a sentence
- reading the other repository to find who writes a flag and what the write means
- proposing a relationship worth probing — which then gets probed
- noticing that two tables disagree

And its output is stored as `asserted`, beside the measurement that agrees or disagrees
with it. A model that says "`amount` in dollars" next to a measured
`GROUP BY currency → {USD, EUR, BRL, MXN, NGN}` is visibly wrong; today the same sentence
stands alone and is believed.

### Documents: by subject, not by file

- **One current document per table**, assembled from its facts, not sixteen historical ones.
- Migration files feed the *history* of a table's facts, they do not each become a document.
- **Never index a file the extractor found nothing in.** A generated "this file has nothing
  to do with the database" is a decision not to store, not a thing to store.
- **Never index build output, vendor trees or minified assets.** 16 documents today; the
  cost is retrieval budget, permanently.

### The fact the agent needs most is the warning

`payment_histories` is the case to design for. The knowledge worth having is not its column
list — it is *"this looks like the revenue table and is not; the revenue table is
`purchases`; measured discrepancy 4.3× and unstable month to month."* That is a
**relationship fact between two tables**, it is derivable by measurement (run the same
aggregate on both, compare), and no per-file document will ever contain it.

**The probe that finds it:** for any two tables that both carry a money-shaped column and a
user key, run the monthly aggregate on both and compare. A stable ratio means units; an
unstable ratio means **different definitions** — which is precisely how the control's author
diagnosed it, by hand, in production.

---

## 6. What this changes in the plan

This does not displace Goal #1 (ADR-0005) — it sharpens its premise. The Numbers Gate stops
an agent inventing a figure; it cannot stop an agent computing a real figure from the wrong
table with the wrong units. **The knowledge layer is where that is prevented, and it is
currently the weakest link:** correct on the two filters that matter, wrong on money, silent
on the trap.

Proposed as a project, sized like the others in ADR-0005:

- **PRJ-17 — measured table facts.** The probe battery, the `TableFact` model with its three
  confidence levels, the schema index rewritten to store receipts, and the answering prompt
  changed to show measurement and assertion differently. **M**, and it is the highest-value
  knowledge-layer work available because it turns a third of the control's tribal knowledge
  into something the product derives on its own.
- **PRJ-18 — documents by subject.** One document per table, migrations as history, and the
  three exclusions (non-answers, build output, vendor). **S**, and it shrinks the corpus
  while improving it.
- **PRJ-19 — relationship probes.** The `payment_histories` class: two tables that look
  alike, measured against each other. **S after PRJ-17.**

## 7. What is NOT claimed here

The 29 facts come from reading one integration; another reader might find more. The
`subscription_users` hint is called unverifiable rather than wrong — the control does not
use that table, which is evidence of absence only if the control is complete for revenue,
and it is complete only for the P&L it publishes. And the probe battery's cost has not been
measured on a 6.88M-row table; `db_index_fetch_samples_budget_seconds` exists because that
cost is real, which is why every probe above is written with a cap.
