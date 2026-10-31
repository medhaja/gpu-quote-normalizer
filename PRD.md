# Dealer Quote Intake: messy GPU quotes in, validated records out

**One-liner**
A small tool that reads dealer spreadsheets and quote emails for GPU servers, maps them to a strict quote schema, rejects or queues anything ambiguous, and shows like-for-like quotes for one RFQ side by side.

This is independent work. I used only public information about Stoa and synthetic sample data. I have no access to Stoa's data, systems or users.

## Problem (outside-in)
From the outside, it looks like GPU hardware still trades over phone calls, forwarded spreadsheets and email. The founders say a buyer asking several dealers for similar nodes can get quotes from $200k to $240k ([Launch YC](https://www.ycombinator.com/launches/SDZ-stoa-the-market-behind-ai-hardware), [Launch HN](https://news.ycombinator.com/item?id=49246057)). Stoa's pitch is that every RFQ, quote, award and settlement gets recorded ([stoaexchange.com](https://www.stoaexchange.com)). The public [docs](https://www.stoaexchange.com/docs) cover a CLI that opens RFQs from a request file. Quotes are accepted in the web app.

If counterparties keep sending spreadsheets, someone has to turn them into records. If SKU, configuration, condition, location or quantity is normalized wrong, the quote comparison is wrong, and so are any price marks built on it. A wrong field that looks clean is worse than one that gets flagged.

## Users and the job to be done
- **Stoa ops engineer:** "When a dealer emails a spreadsheet, I want it turned into quote records I can trust, and I want to see exactly which fields need a human."
- **Buyer (indirectly):** "I want quotes for the same configuration compared on the same basis."

## Goals / Non-goals
**Goals**
- Parse CSV/XLSX and plain-text email quotes into one strict schema.
- Never guess. An unclear field goes to a review queue with the reason.
- Keep an append-only audit trail from raw input to final record.
- Run with no API keys.

**Non-goals**
- Verifying hardware condition.
- Pricing, awards, settlement or payments.

## Prototype scope
The repo contains:
- A Pydantic schema for `Quote` with an enum-backed SKU and condition catalog.
- A deterministic parser for spreadsheets and a rule-based email extractor.
- An optional LLM extractor (LiteLLM), with a deterministic mock as the default.
- Validators and a review queue.
- A FastAPI app with server-rendered pages.
- A synthetic data generator, a labeled eval set and a pytest suite.
- `make demo` (or `python -m intake.demo`), which seeds data and starts the app.

## Functional requirements
1. FR1: Upload or select a sample file (CSV, XLSX, .eml/.txt). The system stores the raw bytes and a SHA-256 hash before parsing.
2. FR2: Spreadsheet columns are mapped by an alias table (`"GPU"`, `"Card"`, `"Model"` → `gpu_sku`). Unmapped columns are listed, not dropped silently.
3. FR3: SKU normalization maps variants (`H100 SXM5 80G`, `h100-sxm`) to a canonical SKU. If the input matches more than one canonical SKU (e.g. `H100` with no form factor), the field is marked `ambiguous`.
4. FR4: Each quote has: `gpu_sku`, `gpus_per_node`, `node_count`, `condition` (new/refurbished/used/unknown), `location`, `unit_price_usd`, `total_price_usd`, `lead_time_days`, `dealer`, `valid_until`.
5. FR5: Validators check: total ≈ unit × nodes within $1; currency is USD or flagged; condition is never inferred (missing → `unknown` + flag); quantity > 0; valid_until is not in the past.
6. FR6: Every field records its source (cell ref or email line), the extractor used (rule/LLM/mock) and its status (`ok`, `ambiguous`, `invalid`, `missing`).
7. FR7: A quote with any non-`ok` required field goes to the review queue. A reviewer can set a value and must enter a reason. The edit is stored as a new event. The original is not overwritten.
8. FR8: Re-ingesting the same file (same hash) does not create duplicate quotes.
9. FR9: The comparison view groups only quotes whose canonical SKU, gpus_per_node and condition all match.
10. FR10: With `LLM_PROVIDER` unset, the mock extractor runs and all tests pass offline.

## Demo UI
1. **Inbox:** seeded sample files with status counts (parsed, needs review, rejected). Click one.
2. **Extraction view:** raw input on the left, structured fields on the right. Each field is colored by status, and hovering shows its source cell or line.
3. **Review queue:** flagged fields with the reason ("`H100` matches SXM5 and PCIe"). Resolve with a value and a note.
4. **RFQ comparison:** one synthetic RFQ ("16× 8-GPU H100 SXM5 nodes"), comparable quotes in a table, and excluded quotes listed with why they were excluded.
5. **Audit log:** an event stream per quote, from ingest to extract to validate to review.

## Data
The generator script (seeded, reproducible) produces:
- 12 dealers, 3 RFQs, about 60 quotes across 25 files.
- Formats: 10 CSV, 8 XLSX (merged header cells, extra blank rows), 7 emails (prose, inline tables, forwarded chains).
- SKUs: H100 SXM5/PCIe, H200, A100 40/80GB, B200, L40S.
- Edge cases: ambiguous SKU, missing condition, totals that don't match unit × qty, EUR prices, "8x" vs "8 GPUs", expired validity dates, a duplicate file, and two quotes in one email.
- Ground-truth labels for every field, used by the eval.

## Architecture
```
file → raw_store (hash) → parser (csv/xlsx | email)
     → extractor [rules → optional LLM → mock]
     → normalizer (catalog) → validators → quotes + events
     → review queue → comparison view
```
- **Plain code** does column mapping, SKU catalog lookup, arithmetic, dates and dedupe. These steps must be exact and testable.
- **The LLM helps** only with free-text emails, where rules miss fields. It returns JSON against the schema. Its output goes through the same validators, and it cannot mark a field `ok` on its own.
- Storage: append-only `events` table plus a `quotes` view derived from it.

## Tech choices
- **Python + FastAPI + Jinja/htmx:** these match the job post's Python focus and are what I've shipped with before (FastAPI services at Infinite Computer Solutions and in my resume RAG chatbot). Server-rendered pages keep the demo to one process. I'm skipping TypeScript here to save time.
- **SQLite by default, PostgreSQL via `DATABASE_URL`:** one-command demo, with the same SQLAlchemy schema running on Postgres.
- **Pydantic:** a strict schema at the boundary.
- **LiteLLM:** provider-agnostic and optional. I used it for multi-model routing at Bizmetric.

The design is the pattern from my ADF-to-PySpark accelerator at Bizmetric: deterministic first, LLM for semantic gaps, validation before anything is trusted. There it cut manual effort by 90%. I make no claim about results here until the eval runs.

## How we'd know it works
- **Field accuracy** on the labeled set, per field and per extractor.
- **The metric that matters:** zero wrong values marked `ok`. A miss sent to review is acceptable. A confident wrong value is a failure.
- **Review rate:** the share of quotes needing a human, reported next to accuracy.
- **Tests:** unit tests for each validator and SKU mapping, an idempotency test for re-ingest, an append-only test (no UPDATE on events), and an end-to-end test from file to comparison view.
- `make eval` prints a per-field confusion table for mock and, if a key is set, the LLM.

## Risks and open questions
- Real dealer files are surely messier than my synthetic ones. Which formats does Stoa actually see?
- How does Stoa define SKU and configuration (NIC, storage, CPU)? I kept the catalog small on purpose.
- Should currency conversion ever happen at intake, or always be flagged?
- Should ambiguous quotes be returned to the dealer, rather than resolved internally?
- About me: I'm based in Bengaluru with 5 years of experience. I would need US visa sponsorship. I'm open to relocating to SF or working remote.

## Build plan
1. Scaffold the repo, Makefile, Pydantic schema and SKU catalog.
2. Write the synthetic generator plus ground-truth labels.
3. Build the spreadsheet parser and alias mapping, with tests.
4. Add the rule-based email extractor and the mock LLM extractor.
5. Add validators and statuses, with tests.
6. Add the event store, dedupe and derived quotes view.
7. Add the review queue with reason-required edits.
8. Build the FastAPI pages: inbox, extraction, review, comparison, audit.
9. Add the eval script and the optional LiteLLM extractor.
10. Write a README with a two-minute demo script.

## Out of scope for the prototype
Auth, KYB, real dealer integrations, PDF test reports, price marks, awards, Stripe or settlement reconciliation, deployment and monitoring.
