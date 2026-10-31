"""Evaluate extraction against the labeled synthetic set.

    python -m intake.eval          (mock gap extractor; also the LLM if LLM_PROVIDER is set)

For every field of every labeled quote we compare the predicted (value, status)
with the label:
  correct      predicted status == expected status, and for ok fields the value matches
  wrong-ok     predicted ok, but the value is wrong or the label says it should be flagged
               (the failure that matters: a confident wrong value)
  over-flagged predicted non-ok where the label is ok (costs review time, not correctness)
"""

from __future__ import annotations

import json
import os
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

from intake.extractors import llm_extract, mock_extract
from intake.normalize import normalize_quote
from intake.parsers import parse_file
from intake.parsers.email import parse_email
from intake.schema import QUOTE_FIELDS, Extractor, Status
from intake.validators import quote_status, validate

DATA = Path(__file__).resolve().parents[1] / "data"
STATUSES = [s.value for s in Status]


@dataclass
class Report:
    name: str
    confusion: dict[str, Counter] = field(default_factory=lambda: defaultdict(Counter))
    correct: Counter = field(default_factory=Counter)
    total: Counter = field(default_factory=Counter)
    wrong_ok: list[str] = field(default_factory=list)
    by_extractor: dict[str, Counter] = field(default_factory=lambda: defaultdict(Counter))
    quotes: int = 0
    needs_human: int = 0
    count_mismatch: list[str] = field(default_factory=list)


def _same(a, b) -> bool:
    if isinstance(a, (int, float)) and isinstance(b, (int, float)):
        return abs(float(a) - float(b)) < 0.01
    return a == b


def evaluate(name: str, gap_filler, data_dir: Path = DATA) -> Report:
    labels = json.loads((data_dir / "labels.json").read_text(encoding="utf-8"))
    as_of = date.fromisoformat(json.loads((data_dir / "rfqs.json").read_text(encoding="utf-8"))["as_of"])
    rep = Report(name)
    for fname, lab in labels.items():
        if lab["duplicate_of"]:
            continue
        content = (data_dir / "samples" / fname).read_bytes()
        if fname.endswith((".eml", ".txt")):
            parsed = parse_email(fname, content, gap_filler=gap_filler)
        else:
            parsed = parse_file(fname, content)
        if len(parsed.quotes) != len(lab["quotes"]):
            rep.count_mismatch.append(f"{fname}: {len(parsed.quotes)} found, {len(lab['quotes'])} labeled")
        for i, expected in enumerate(lab["quotes"]):
            rep.quotes += 1
            if i >= len(parsed.quotes):
                for f in QUOTE_FIELDS:
                    rep.total[f] += 1
                    rep.confusion[f][(expected[f]["status"], "no quote")] += 1
                rep.needs_human += 1
                continue
            fields = validate(normalize_quote(parsed.quotes[i]), as_of)
            if quote_status(fields)[0].value != "parsed":
                rep.needs_human += 1
            for f in QUOTE_FIELDS:
                got, exp = fields[f], expected[f]
                rep.total[f] += 1
                rep.confusion[f][(exp["status"], got.status.value)] += 1
                ok_value = got.status == Status.OK and _same(got.value, exp["value"])
                is_correct = got.status.value == exp["status"] and (exp["status"] != "ok" or ok_value)
                if is_correct:
                    rep.correct[f] += 1
                if got.status == Status.OK and not (exp["status"] == "ok" and ok_value):
                    rep.wrong_ok.append(f"{fname} #{i + 1} {f}: got {got.value!r}, expected "
                                        f"{exp['value']!r} ({exp['status']})")
                ext = got.extractor.value if got.extractor else "none"
                rep.by_extractor[ext]["fields"] += 1
                rep.by_extractor[ext]["correct"] += int(is_correct)
    return rep


def print_report(rep: Report) -> None:
    print(f"\n=== Extractor: {rep.name} ===")
    print(f"{rep.quotes} labeled quotes · {rep.needs_human} need a human "
          f"(review rate {rep.needs_human / max(rep.quotes, 1):.0%})")
    if rep.count_mismatch:
        print("Quote count mismatches:", *rep.count_mismatch, sep="\n  ")
    print("\nPer-field accuracy and confusion (rows: expected, columns: predicted)")
    head = f"{'field':<17}{'accuracy':>9}   " + "  ".join(f"{s:>9}" for s in STATUSES)
    print(head + "   <- predicted")
    print("-" * len(head))
    for f in QUOTE_FIELDS:
        acc = rep.correct[f] / max(rep.total[f], 1)
        rows = [(e, Counter({p: n for (ee, p), n in rep.confusion[f].items() if ee == e})) for e in STATUSES]
        first = True
        for exp, preds in rows:
            if not preds:
                continue
            label = f"{f:<17}{acc:>8.0%}" if first else " " * 25
            print(f"{label}   " + "  ".join(f"{preds.get(p, 0) or '·':>9}" for p in STATUSES) + f"   exp {exp}")
            first = False
    print("\nBy extractor (fields correct / fields)")
    for ext, c in sorted(rep.by_extractor.items()):
        print(f"  {ext:<9} {c['correct']:>4} / {c['fields']:<4}")
    print(f"\nWrong values marked ok: {len(rep.wrong_ok)}  (target: 0)")
    for w in rep.wrong_ok:
        print("  x", w)


def main() -> int:
    reports = [evaluate("mock", (Extractor.MOCK, mock_extract))]
    if os.environ.get("LLM_PROVIDER"):
        reports.append(evaluate("llm", (Extractor.LLM, llm_extract)))
    else:
        print("LLM_PROVIDER not set: evaluating the deterministic mock extractor only.")
    for rep in reports:
        print_report(rep)
    return 1 if any(r.wrong_ok for r in reports) else 0


if __name__ == "__main__":
    raise SystemExit(main())
