# KT video script: gpu-quote-normalizer

Narration is written the way it should be spoken (respelled for text-to-speech: "skew" = SKU, "shah two fifty-six" =
SHA-256, "H one hundred" = H100, "R-F-Q" = RFQ, "L-L-M" = LLM, "e-val" = eval). On-screen text uses the real spelling.

Colour meaning: **blue** = incoming data · **amber** = needs a human · **red** = invalid / rejected · **green** = ok /
comparable · **violet** = stored state.

Runtime numbers (10 comparable, 13 excluded, the Helix row 6 values, eval 0 wrong-ok) were checked on 2026-11-01 by
seeding a throwaway SQLite database with `INTAKE_AS_OF=2026-11-02` and running `python -m intake.eval`.

---

## 01 · The problem

**Narration** (60 words)

> From the outside, GPU servers still seem to trade over email and forwarded spreadsheets. The founders say a buyer
> asking several dealers for similar nodes can get quotes from two hundred to two hundred forty thousand dollars. To
> compare them, someone has to turn each file into a record. And a wrong value that looks clean is worse than one that
> gets flagged.

**On screen**
- 0 s: Chapter label `01 / The problem`. Three blue document cards drift in from the left: `quote.csv`,
  `quotation.xlsx`, `RE: H100 pricing.eml`.
- At "two hundred to two hundred forty thousand": a horizontal price axis $200k → $240k fades in; five price dots
  settle along it. Small caption: "Source: Launch YC (public)".
- At "turn each file into a record": the three cards collapse into one structured record card with field rows.
- At "a wrong value that looks clean": two field rows side by side. The left one is green "ok" with a faint red ✗ that
  appears after a beat ("looks clean, is wrong"). The right one is amber "needs review" ("flagged"). Title text
  appears beneath: **Flag it. Don't guess.**

**Sources**
- "From the outside, it looks like GPU hardware still trades over phone calls, forwarded spreadsheets and email";
  a buyer asking several dealers for similar nodes "can get quotes from $200k to $240k" (the founders): `PRD.md:9`
  (links to Launch YC and Launch HN). Wording changed in Phase 6 to match the PRD's hedging.
- Someone has to turn spreadsheets into records: `PRD.md:11`
- "A wrong field that looks clean is worse than one that gets flagged": `PRD.md:11`; "Never guess": `PRD.md:20`

---

## 02 · Architecture at a glance

**Narration** (65 words)

> Here's the whole system: one pipeline. A file comes in, and its raw bytes and shah two fifty-six hash are stored
> first. A parser reads the spreadsheet or email. A normalizer maps each value to a strict schema. Validators check
> fields against each other. Every step is an event in an append-only log. And an L-L-M is optional; it only helps
> find text in emails.

**On screen**
- 0 s: Chapter label `02 / Architecture`. Empty stage with a faint baseline.
- At "a file comes in": blue `file` box appears on the left.
- At "raw bytes and hash": violet `raw_files (sha256)` box; arrow animates from `file`.
- At "a parser": `parse_file()` box with two small tags `spreadsheet` | `email`; arrow animates in.
- At "a normalizer": `normalize_quote()` box; arrow. Small sub-label "SKU catalog · numbers · money · dates".
- At "validators": `validate()` box; arrow.
- At "an event": violet `events (append-only)` box below the row; dashed arrows drop down from `ingest`, parser,
  normaliser and validator boxes into it. From `events`, arrow to `project()` then forks to `review queue` (amber) and
  `compare()` (green).
- At "an L-L-M is optional": a dashed-border box `gap-filler: mock | LLM` hangs off the email tag, labelled
  "optional · locates text only".

**Sources**
- Pipeline order file → raw_files → parser → normalizer → validators → events: `intake/pipeline.py:3-4`,
  `intake/pipeline.py:39-76`
- Raw bytes + SHA-256 stored before parsing: `intake/pipeline.py:41`, `intake/pipeline.py:49-53`
- Parser chosen by extension (spreadsheet or email): `intake/parsers/__init__.py:11-21`
- Normalizer → strict schema: `intake/normalize.py:169-170`, `intake/schema.py:35-46`
- Cross-field validators: `intake/validators.py:1-6`, `intake/validators.py:19-40`
- Append-only events: `intake/store.py:1-6`, `intake/store.py:96-102`
- State is replayed into review / compare: `intake/pipeline.py:123-138`, `intake/web/app.py:79-84`,
  `intake/web/app.py:108-116`
- LLM optional, only for email gaps: `intake/extractors.py:1-6`, `intake/extractors.py:88-92`,
  `intake/parsers/email.py:142-154`

---

## 03 · One row, end to end

**Narration** (101 words)

> Let's follow one real row: row six of the Helix sample sheet. Ingest hashes the file and logs it. The spreadsheet
> parser maps headers through an alias table: Model becomes G-P-U skew. Warranty has no match, so it's listed as
> unmapped, not dropped. The normalizer turns "H one hundred S-X-M" into exactly one catalog skew, and "three weeks"
> into twenty-one days. Then validate checks the math. Two hundred thirty-eight thousand, times sixteen nodes, is
> three million eight hundred eight thousand. The sheet says three million eight hundred twenty thousand. So the total
> is marked invalid, and the quote goes to review.

**On screen**
- 0 s: Chapter label `03 / One row, end to end`. Top: file path `data/samples/02_helix_rfq_response.csv`. A small
  grid shows the header row (A3:K3) and row 6, with row 6 highlighted blue.
- At "Ingest hashes the file": a blue row card lifts out of the grid and stops at station 1, `ingest()`. A violet chip
  `file_received · sha256 3f…` (truncated, illustrative) drops into an event rail at the bottom.
- At "alias table": station 2 `parse_spreadsheet()`. Header mapping list appears: `Model → gpu_sku`,
  `GPU Count → gpus_per_node`, `Qty → node_count`, `Price/Node → unit_price_usd`, `Extended Price → total_price_usd`…
- At "Warranty has no match": an amber pill `unmapped: Warranty`.
- At "the normalizer": station 3 `normalize_quote()`. Field rows flip from raw to normalized, each turning green:
  `"H100 SXM" → H100-SXM5-80GB (A6)`, `"3 weeks" → 21 (H6)`, `"$238,000.00" → 238000 (F6)`.
- At "Then validate": station 4. The stage switches to a **code focus** on `intake/validators.py`, lines 22–31
  (excerpt below). Lines 23–25 highlight at "checks the math".
- At "the sheet says": line 26–30 highlight; the total field `G6` turns red with the reason
  `total $3,820,000.00 ≠ unit $238,000.00 × 16 nodes = $3,808,000.00`.
- At "goes to review": the card gets an amber badge `needs_review · 1 field: total_price_usd`.

Code excerpt (`intake/validators.py:22-31`):
```python
    unit, nodes, total = out["unit_price_usd"], out["node_count"], out["total_price_usd"]
    if all(f.status == Status.OK for f in (unit, nodes, total)):
        expected = round(float(unit.value) * int(nodes.value), 2)
        if abs(float(total.value) - expected) > TOLERANCE_USD:
            out["total_price_usd"] = total.model_copy(update={
                "status": Status.INVALID,
                "code": "total_mismatch",
                "reason": (f"total ${float(total.value):,.2f} ≠ unit ${float(unit.value):,.2f} "
                           f"× {nodes.value} nodes = ${expected:,.2f}"),
            })
```

**Sources**
- Row 6 contents (`H100 SXM,8,16,new,"San Jose, CA","$238,000.00","$3,820,000.00",3 weeks,"Nov 22, 2026"`):
  `data/samples/02_helix_rfq_response.csv:6` (spreadsheet row 6, since the CSV has a title row and a blank row first)
- Ingest hashes and logs `file_received`: `intake/pipeline.py:41`, `intake/pipeline.py:50-53`
- Alias table, `model → gpu_sku`: `intake/parsers/spreadsheet.py:17-33` (line 19)
- Header row = first row with ≥3 known columns: `intake/parsers/spreadsheet.py:108-116`
- Unmapped columns are listed: `intake/parsers/spreadsheet.py:58-59`, `intake/parsers/spreadsheet.py:119`; runtime
  `unmapped_columns: ['Warranty']` (verified)
- "H100 SXM" → exactly one SKU (SXM, no PCIe): `intake/catalog.py:90-94`, `intake/catalog.py:84-86`
- "3 weeks" → 21 days: `intake/normalize.py:65-72`; runtime value 21 from H6 (verified)
- Total check with $1 tolerance: `intake/validators.py:15`, `intake/validators.py:22-31`
- Runtime reason `total $3,820,000.00 ≠ unit $238,000.00 × 16 nodes = $3,808,000.00` (verified)
- Any non-ok field → `needs_review`: `intake/validators.py:54-56`; runtime `1 field(s) need review: total_price_usd`
  (verified)

---

## 04 · Append-only log and human review

**Narration** (70 words)

> Quotes are never stored as rows you can edit. There are two tables: raw files, and events. Updates and deletes are
> blocked twice: by an O-R-M guard, and by a database trigger. To fix a field, a reviewer enters a value and a
> required reason. The value goes through the same parser. The edit becomes a new event, and the quote is validated
> again. The original stays in the log.

**On screen**
- 0 s: Chapter label `04 / Event log & review`. A data-model diagram: violet table `raw_files` (`id`, `filename`,
  `sha256 UNIQUE`, `content`) linked 1→many to violet table `events` (`id`, `file_id`, `quote_id`, `type`, `payload`).
- At "blocked twice": an `UPDATE events …` arrow flies at the `events` table and stops at two shields: `ORM guard
  (before_flush)` and `DB trigger (SQLite / PostgreSQL)`. The arrow turns red and fades.
- At "a reviewer enters": switch to a **code focus** on `intake/pipeline.py` lines 159–175 (excerpt below). Line 159–160
  highlights at "required reason"; line 166 at "same parser"; lines 170–175 at "new event … validated again".
- At "the original stays in the log": the event rail for Q2.3 slides in at the bottom: `file_received` ·
  `file_parsed` · `quote_extracted` · `quote_normalized` · `quote_validated`, then two new chips appear:
  `field_reviewed (before → after, reason)` and `quote_validated`. The earlier chips stay unchanged.

Code excerpt (`intake/pipeline.py:159-175`, lines 161–165 and 169 collapsed to `…` to keep it under 15 lines):
```python
    if not (reason or "").strip():
        raise ReviewError("a reason is required for every manual edit")
    …
    new = normalize_reviewer_value(field_name, value)
    if new.status != Status.OK:
        raise ReviewError(f"value not accepted: {new.reason}")
    …
    append(session, "field_reviewed", {
        "field": field_name, "before": view.fields[field_name].model_dump(mode="json"),
        "after": new.model_dump(mode="json"), "reason": reason.strip(), "reviewer": reviewer,
    }, file_id=view.file_id, quote_id=quote_id)
    fields = dict(view.fields, **{field_name: new})
    _record_validation(session, view.file_id, quote_id, fields, as_of, cause="review", rejected_reason=view.rejected_reason)
```

**Sources**
- Quotes not stored as mutable rows; state is a replay: `intake/store.py:3-5`, `intake/pipeline.py:123-138`
- Two tables `raw_files`, `events`: `intake/store.py:25-44`
- ORM guard: `intake/store.py:55-59`; DB triggers for SQLite and PostgreSQL: `intake/store.py:62-73`, applied in
  `intake/store.py:80-84`; tested in `tests/test_store_review.py:43-60`
- Reason required: `intake/pipeline.py:159-160`
- Reviewer value goes through the same parser: `intake/pipeline.py:166`, `intake/normalize.py:173-179`
- New `field_reviewed` event, then re-validation: `intake/pipeline.py:170-175`
- Original kept: nothing in the code updates events (append only, `intake/store.py:96-102`);
  `tests/test_store_review.py:62` (`test_flagged_quote_goes_to_review_and_edit_is_a_new_event`)
- Event sequence for Q2.3 (verified at runtime): `file_received, file_parsed, quote_extracted, quote_normalized,
  quote_validated`

---

## 05 · Emails, and a gap-filler that can't lie

**Narration** (81 words)

> Emails are messier. Line-based rules run first. For fields they miss, a gap-filler steps in: a deterministic mock
> by default, or a real L-L-M if you configure one. Either way, it only returns a span of text and a line number. The
> ground function keeps the span only if it's really on that line, and the normal parser decides the value. A made-up
> span is dropped. So the model can point at text, but never mark a field okay by itself.

**On screen**
- 0 s: Chapter label `05 / Emails & the gap-filler`. Left half: the body of `25_oakline_h200.eml`, lines 8–11, with
  line numbers (no headers or addresses shown):
  ```
   8  Good news on the H200 side. We have 8 x 8-GPU NVIDIA H200 nodes, new, at $318,500 per node
   9  (total $2,548,000). We can deliver in about four weeks.
  10  Everything is staged at our Reno, NV facility.
  11  Valid until 17 November 2026.
  ```
- At "Line-based rules run first": SKU, count, condition, unit and total on lines 8–9 turn blue → green, tagged `rule`.
- At "a gap-filler steps in": a dashed box `gap-filler (mock)` appears; it returns `{"lead_time_days": {"span":
  "about four weeks", "line": 9}}`.
- At "only if it's really on that line": split into **with / without** panels.
  - Left (green): span `about four weeks` is found on line 9 → `parse_lead_time` → `28 days · mock · L9 · ok`.
  - Right (red): an invented span `{"span": "2 weeks", "line": 9}` → "not found on line 9; ignored" → field stays
    `missing`.
- At "the ground function": a small **code focus** on `intake/extractors.py:95-107` (excerpt below), with lines 102–104
  highlighted.
- At "never mark a field okay by itself": footer chips: `LLM_PROVIDER unset → mock` · `LLM error → fields stay
  missing`.

Code excerpt (`intake/extractors.py:95-107`):
```python
def ground(found: dict[str, dict], lines: Lines, extractor: Extractor) -> tuple[dict[str, RawCell], list[str]]:
    """Keep only spans that appear verbatim on the cited line."""
    by_no = dict(lines)
    cells: dict[str, RawCell] = {}
    notes: list[str] = []
    for field, hit in found.items():
        text = by_no.get(hit["line"], "")
        span = hit["span"].strip()
        if span and span.lower() in text.lower():
            cells[field] = RawCell(text=span, source=f"L{hit['line']}", extractor=extractor)
        else:
            notes.append(f"{extractor.value} span for {field} not found on line {hit['line']}; ignored")
    return cells, notes
```

**Sources**
- Rules first, gap-filler only for missing fields: `intake/parsers/email.py:1-6`, `intake/parsers/email.py:142-154`
- Mock by default, LLM when `LLM_PROVIDER` is set: `intake/extractors.py:88-92`
- Returns only `{span, line}`: `intake/extractors.py:3-6`, `intake/extractors.py:37-48`, `intake/extractors.py:51-57`
- `ground()` checks the span is on the cited line (case-insensitive substring): `intake/extractors.py:95-107`
- The normal parser decides value and status: grounded cells become `RawCell`s (`intake/extractors.py:104`) and then
  pass through `normalize_quote` (`intake/pipeline.py:71`)
- Oakline lead time `about four weeks` on line 9 → 28 days, extractor `mock` (verified at runtime);
  `data/samples/25_oakline_h200.eml:9`; "about" stripped in `intake/normalize.py:61`
- Made-up span dropped: `tests/test_email.py:103` (`test_hallucinated_llm_span_is_dropped`)
- LLM failure leaves fields missing: `intake/parsers/email.py:145-149`; `tests/test_email.py:121`
- The "2 weeks" span in the right-hand panel is an illustrative example, not taken from the tests.

---

## 06 · Like-for-like comparison, and running it

**Narration** (72 words)

> Now the comparison. A quote is comparable only if its skew, GPUs per node, and condition match the R-F-Q, and
> every field is okay. For R-F-Q ten-oh-one, sixteen H one hundred nodes, ten quotes qualify. Thirteen related quotes
> are excluded, each with a reason: wrong form factor, four GPUs per node, refurbished, euros, expired, or an
> ambiguous skew. To try it, install the requirements and run python dash m intake dot demo.

**On screen**
- 0 s: Chapter label `06 / Compare & run`. A green-outlined RFQ card: `RFQ-1001 · 16× 8-GPU H100 SXM5 nodes, new`, with
  three match keys underlined: `gpu_sku`, `gpus_per_node`, `condition`.
- At "every field is okay": a fourth key `all fields ok`.
- At "ten quotes qualify": a green table builds row by row, 10 rows ranked by price per node; the first and last are
  labelled `$205,000` and `$236,500`.
- At "Thirteen related quotes are excluded": a second list with 13 rows slides in beneath, rows coloured amber/red, each with its reason:
  `H100-PCIE-80GB; RFQ wants H100-SXM5-80GB` · `4 GPUs/node; RFQ wants 8` · `condition is refurbished` ·
  `quoted in EUR` · `quote expired on 2026-10-19` · `matches H100-SXM5-80GB and H100-PCIE-80GB`. Row `Q2.3` shows
  `total $3,820,000.00 ≠ …` (the row from scene 3).
- At "To try it": a terminal panel slides up:
  ```
  pip install -r requirements.txt && python -m intake.demo
  Seeded 25 files (as of 2026-11-02).
  Open http://127.0.0.1:8000
  ```
  Then five page chips: `Inbox` · `Extraction` · `Review` · `Compare` · `Audit log`. Footnote: "No API keys needed."

**Sources**
- Comparable rule (SKU, GPUs/node, condition + every field ok): `intake/compare.py:3-5`, `intake/compare.py:46-67`,
  `intake/compare.py:78-83`
- Related = same GPU family: `intake/compare.py:71-77`
- RFQ-1001 definition: `data/rfqs.json:5-10`
- 10 comparable, $205,000–$236,500, 13 excluded, and the listed reasons: verified at runtime (`compare()` on a
  freshly seeded database, as_of 2026-11-02)
- Ranked by price per node: `intake/compare.py:84`
- Run command: `README.md:4`; seeds every sample file then serves on port 8000: `intake/demo.py:19-29`,
  `intake/demo.py:34`, `intake/demo.py:70-71`; "Seeded 25 files" verified at runtime (25 sample files, 1 is a
  duplicate)
- Five pages: `intake/web/app.py:43`, `:64`, `:79`, `:108`, `:118`
- No API keys needed: `intake/extractors.py:88-92` (mock default), `README.md:7`

---

## 07 · Gotchas and limitations

**Narration** (77 words)

> A few gotchas. Validity is checked against a pinned dataset date. Without it, the code uses today's date, and the
> samples will expire over time. The e-val shows zero wrong values marked okay, but the rules and the data generator
> were written together, so that says little about real files. The catalog has seven skews and ignores C-P-U, network
> and storage. Non-dollar prices are always flagged, never converted. And the quote view is replayed on every request.

**On screen**
- 0 s: Chapter label `07 / Gotchas & limits`. Left column of cards, each appearing at its phrase:
  1. At "pinned dataset date": `INTAKE_AS_OF = 2026-11-02` (code font) · "unset → date.today()" with a small calendar
     icon going amber.
  2. At "zero wrong values": `eval: 0 wrong-ok · 598/598 rule fields` with an amber caveat line "synthetic data,
     written with the rules".
  3. At "seven skews": seven small SKU chips; three grey "missing" chips: `CPU`, `NIC`, `storage`.
  4. At "Non-dollar prices": `€ → flagged (non_usd)`, red.
  5. At "replayed on every request": `project()` replays all events → "fine for hundreds, not millions".
- Last ~3 s: right column "Next steps" fades in: "real (redacted) dealer files → rebuild the eval" · "full node
  config" · "measure the LLM vs the mock" · "materialized projection + reviewer identity".

**Sources**
- Pinned date: `intake/pipeline.py:25-28` (falls back to `date.today()`), `intake/demo.py:44-46`, `data/rfqs.json:2`
- Eval 0 wrong-ok and 598/598 rule fields, 2/2 mock fields: verified with `python -m intake.eval`; exit code depends on
  it: `intake/eval.py:117`, `intake/eval.py:130`
- Rules and generator written together: `README.md:104-107`
- Seven SKUs: `intake/catalog.py:15-22`; ignores CPU, NIC, storage, chassis: `README.md:113-114`
- Non-USD flagged, not converted: `intake/normalize.py:156-158`, `README.md:117`
- Replay on every request: `intake/pipeline.py:123-138`, called per page in `intake/web/app.py:37-41`;
  `README.md:119`
- Next steps: `README.md:124-129`
- Not narrated but true (on screen only if room): email rules are English and line-based, location must look like
  `City, ST`, reviewer is always `ops` (`README.md:115-118`, `intake/pipeline.py:156`).

---

## 08 · Recap

**Narration** (41 words)

> To recap. Raw bytes and hash are stored first. Deterministic parsers decide every value. Anything unclear goes to
> review with a reason, never a guess. Every change is an event, and state is a replay. And only like-for-like quotes are compared.

**On screen**
- Chapter label `08 / Recap`. Five takeaways appear one per sentence, each with its colour dot:
  1. violet: Raw bytes + SHA-256 stored first
  2. green: Deterministic parsers decide every value
  3. amber: Unclear → review with a reason, never a guess
  4. violet: Every change is an event; state is a replay
  5. green: Compare only like-for-like
- Bottom, mono: `python -m intake.demo`

**Sources**: as cited in scenes 02–06.

---

## 09 · Closing card

**Narration** (4 words)

> Thank you for watching.

**On screen**
- No chapter label. Centred: **Thank you** (display font, large); beneath it, smaller: **Made by Medhaja H L**.
- Fades in as the narration starts; holds fully visible for ~3 s after the narration ends; the video ends on it.

**Sources**: none (closing card).

---

## Totals

| Scene | Words |
|---|---|
| 01 The problem | 60 |
| 02 Architecture | 65 |
| 03 One row, end to end | 101 |
| 04 Event log & review | 70 |
| 05 Emails & the gap-filler | 81 |
| 06 Compare & run | 72 |
| 07 Gotchas & limits | 77 |
| 08 Recap | 41 |
| 09 Closing | 4 |
| **Total** | **571** |

At 145 wpm that's about 3:55 of speech. With 0.6 s padding per scene and the ~3 s closing hold, it comes to about
4:05. (Kokoro's `af_heart` usually reads a little faster than 145 wpm, so the real total will probably land at 3:40–4:00.)
