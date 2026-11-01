# KT video outline: gpu-quote-normalizer

## Summary

`gpu-quote-normalizer` is an intake prototype for GPU server quotes, written for Stoa's ops engineers. Dealers send
quotes as CSV or XLSX spreadsheets and plain-text emails. The tool stores each file's raw bytes and SHA-256 hash, parses
it, maps every value onto one strict `Quote` schema (SKU, GPUs per node, nodes, condition, location, unit and total
price, lead time, dealer, validity), and records where each value came from. Anything it can't read with certainty,
like an `H100` with no form factor, a missing condition, EUR prices, a total that doesn't equal unit × nodes, or an
expired quote, goes to a review queue with a reason. The tool never guesses. Every step is an event in an append-only
log. Only fully trusted, truly like-for-like quotes appear side by side in an RFQ comparison. An optional LLM can
help find fields in emails, but it can only point at text. The same deterministic parsers decide the value and the
status. The video is for Stoa founders and engineers who know the domain but haven't seen this code.

Target: ~3.5 min, about 500–530 spoken words.

## Colour meaning (used in every scene)

| Token | Meaning |
|---|---|
| Blue | Incoming data: files, raw cells, requests |
| Amber | Needs a human: ambiguous / missing / review queue |
| Red | Invalid / rejected |
| Green | `ok` / trusted / comparable |
| Violet | Stored state: raw_files, events log |

## Scenes

### 01 · The problem
- **Idea:** Quotes arrive as messy spreadsheets and emails. If one field is normalized wrong, the comparison is wrong. A
  wrong value that looks clean is worse than one that gets flagged.
- **Visual:** Three dealer "documents" (CSV, XLSX, email) drift in. Price chips are placed on a $200k–$240k axis
  (the founders' public figure, cited in the PRD). Then a value that looks clean but is wrong (green with a hidden ✗)
  is set beside a flagged one (amber), with the line "flag, don't guess."
- **Files:** `PRD.md` (Problem, Goals), `README.md` (problem section)

### 02 · Architecture at a glance
- **Idea:** One linear pipeline. Plain code does the exact work, an optional gap-filler only locates text, and the
  quote state is a replay of an event log.
- **Visual:** Boxes animate left to right in the order data moves: `file → raw_files (SHA-256) → parse_file
  (spreadsheet | email) → gap-filler (mock | LLM) → normalize_quote → validate → events → project() → review queue /
  compare()`. The `raw_files` and `events` boxes are violet. The gap-filler box has a dashed border labelled "optional".
- **Files:** `intake/pipeline.py:1-5, 39-76`, `intake/parsers/__init__.py:11-21`, `intake/extractors.py:88-92`,
  `intake/store.py:25-44`

### 03 · One row, end to end
- **Idea:** Follow quote `row 6` of `02_helix_rfq_response.csv` through the real functions.
- **Visual:** A request trace. A card holding the raw row (`H100 SXM, 8, 16, new, "San Jose, CA", $238,000.00,
  $3,820,000.00, 3 weeks, Nov 22 2026`) travels through:
  `ingest()` (SHA-256, `file_received` event) → `parse_spreadsheet()` (header row found, `Model→gpu_sku`,
  `Price/Node→unit_price_usd`, `Warranty` shown as **unmapped**, dealer taken from the preamble cell `A1`) →
  `normalize_quote()` (`"H100 SXM"` → `H100-SXM5-80GB` via `match_sku`, `"3 weeks"` → 21 days, `"$238,000.00"` →
  238000 USD). Then a **code focus** on `validators.py:22-31`: the total check lights up and
  `$3,820,000 ≠ $238,000 × 16 = $3,808,000` turns the total field red. Quote status: `needs_review`.
- **Files:** `data/samples/02_helix_rfq_response.csv`, `intake/pipeline.py:39-76`,
  `intake/parsers/spreadsheet.py:17-33, 104-160`, `intake/catalog.py:75-97`, `intake/normalize.py:59-72, 120-170`,
  `intake/validators.py:19-57`

### 04 · Append-only log and human review
- **Idea:** Quotes are never stored as mutable rows. A reviewer edit is a new event with a required reason, and the
  current state is a replay.
- **Visual:** A data model: `raw_files` (sha256 unique) → `events` (type, quote_id, payload). Event chips stack up:
  `file_received`, `file_parsed`, `quote_extracted`, `quote_normalized`, `quote_validated`, then `field_reviewed`
  (before / after / reason), then a new `quote_validated`. An attempted UPDATE bounces off two shields: "ORM guard"
  and "DB trigger". A short code focus on `review_field` shows the reason check and the reviewer value going through the
  same parser.
- **Files:** `intake/store.py:36-73, 96-102`, `intake/pipeline.py:123-138, 155-177`, `intake/normalize.py:173-179`,
  `tests/test_store_review.py:43-62`

### 05 · Emails and a gap-filler that can't lie
- **Idea:** Line-based rules run first. For fields they miss, a mock (default) or an LLM returns only
  `{span, line}`. `ground()` drops any span that isn't on that line, and the normal parser decides the value.
- **Visual:** A with/without comparison. On the left, the gap-filler says lead time is "about three weeks" on
  L-n; the span is on the line, so it passes and becomes 21 days, tagged `mock`. On the right, a made-up span fails the
  verbatim check and is dropped with a note. A code focus on `ground()` (`extractors.py:95-107`). A small footnote:
  `LLM_PROVIDER` unset → mock; LLM failure → fields stay `missing`.
- **Files:** `intake/parsers/email.py:94-159`, `intake/extractors.py:23-48, 88-107`, `tests/test_email.py:96-121`,
  `tests/test_eval.py:13`

### 06 · Like-for-like comparison, and running it
- **Idea:** A quote is comparable only if SKU, GPUs per node and condition match the RFQ and every field is `ok`.
  Everything else in the same GPU family is listed with its reasons. Then, how to run it: one command.
- **Visual:** The RFQ-1001 card ("16× 8-GPU H100 SXM5 nodes, new"). Quote cards sort into a green "comparable" table
  ranked by price per node and an amber/red "excluded" list with reasons (PCIe not SXM5, 4 GPUs/node, EUR, expired,
  ambiguous SKU). Then a terminal panel: `pip install -r requirements.txt && python -m intake.demo` → it seeds 25
  synthetic files → open `http://127.0.0.1:8000`. The five page names appear: Inbox, Extraction, Review, Compare, Audit.
- **Files:** `intake/compare.py:46-90`, `data/rfqs.json`, `intake/demo.py:19-71`, `intake/web/app.py:43-125`,
  `README.md:3-7`

### 07 · Gotchas and limitations
- **Idea:** Be honest about what this prototype is and isn't.
- **Visual:** A list of gotcha cards appears one at a time:
  1. **Pinned date:** validity is checked against `INTAKE_AS_OF`. The demo pins it to the dataset date 2026-11-02;
     without it, `date.today()` is used, so quotes expire as time passes (`pipeline.py:25-28`, `demo.py:46`).
  2. **The 100% eval is not a real result:** the rules and the generator were written together (README).
  3. **Small catalog:** 7 SKUs; a node is GPU × count, with no CPU, NIC, storage or chassis.
  4. **No currency conversion:** non-USD prices are always flagged.
  5. **Emails:** English, line-based; location must look like `City, ST`; the mock is a keyword heuristic.
  6. **Scale:** `project()` replays every event on each request; no auth, and the reviewer is always `ops`.
  Then "Next steps" in a column on the right: real redacted dealer files → rebuild the eval; full node config;
  measure the LLM against the mock; materialized projection + reviewer identity.
- **Files:** `README.md:109-129`, `PRD.md:91-95`, `intake/pipeline.py:25-28, 123`, `intake/demo.py:44-46`,
  `intake/catalog.py:15-22`, `intake/normalize.py:156-158`

### 08 · Recap
- **Idea:** Five takeaways.
- **Visual:** 5 one-line takeaways: raw bytes + hash first; deterministic parsers decide every value; unclear → review
  with a reason, never a guess; append-only events, state is a replay; compare only true like-for-like. The run command
  sits at the bottom.
- **Files:** (summary of the above)

### 09 · Closing card
- **Narration:** "Thank you for watching."
- **Visual:** "Thank you" large in the display font, "Made by Medhaja H L" smaller beneath it, centred. Fades in as the
  narration starts and holds about 3 s after it ends.

## Open questions

1. Runtime numbers: the README says the demo shows **10 comparable quotes ($205k–$236.5k, a 15% spread)** and **13
   excluded** for RFQ-1001, and that **27% of quotes need a human**. I can't confirm these by reading code alone. Shall I
   run `python -m intake.demo --no-serve` and the eval in a throwaway database to verify them before quoting them? If
   not, I'll leave them out.
2. Scene 01 uses the founders' public "$200k to $240k" figure from the PRD (with the Launch YC / HN links). OK to show
   it on screen with a small "source: Launch YC" caption?
3. Scene 03 traces a spreadsheet row (the total mismatch). Would you rather trace an email instead (for example,
   `25_oakline_h200.eml`, where the mock fills the lead time)? Scene 05 covers emails either way.
4. Should the PRD's personal notes (visa, location, past employers) stay out of the video? I plan to leave them out.
