"""Generate the synthetic sample dataset (seeded, reproducible).

Writes:
  data/samples/*      25 dealer files: 10 CSV (one exact duplicate), 8 XLSX, 7 emails
  data/labels.json    ground truth for every field of every quote, by file and order
  data/rfqs.json      3 synthetic RFQs and the dataset's as-of date

All dealers, people, domains, prices and quotes are invented.
"""

from __future__ import annotations

import csv
import io
import json
import random
import shutil
import sys
import zipfile
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from pathlib import Path

from openpyxl import Workbook
from openpyxl.styles import Alignment, Font

ROOT = Path(__file__).resolve().parents[1]
AS_OF = date(2026, 11, 2)
SEED = 20261102

DEALERS = {
    "northwind": ("Northwind Compute", "Dallas, TX"),
    "helix": ("Helix Systems", "San Jose, CA"),
    "ridgeline": ("Ridgeline Hardware", "Ashburn, VA"),
    "bluefin": ("Bluefin Servers", "Ashburn, VA"),
    "cobalt": ("Cobalt Racks", "Phoenix, AZ"),
    "meridian": ("Meridian GPU Supply", "San Jose, CA"),
    "oakline": ("Oakline Technologies", "Reno, NV"),
    "parallax": ("Parallax Data Gear", "Chicago, IL"),
    "quarry": ("Quarry Compute", "Columbus, OH"),
    "sablewood": ("Sablewood IT", "Frankfurt, DE"),
    "tidewater": ("Tidewater Systems", "Seattle, WA"),
    "vantage": ("Vantage Node Co", "Atlanta, GA"),
}

SKU_TEXT = {
    "H100-SXM5-80GB": ["H100 SXM5 80GB", "h100-sxm", "NVIDIA H100 SXM5 80G", "H100 SXM"],
    "H100-PCIE-80GB": ["H100 PCIe 80GB", "h100-pcie", "NVIDIA H100 PCIe"],
    "H200-SXM-141GB": ["H200 SXM 141GB", "H200", "NVIDIA H200"],
    "A100-SXM4-80GB": ["A100 80GB SXM4", "a100-80g", "A100 SXM4 80GB"],
    "A100-SXM4-40GB": ["A100 40GB SXM4", "a100-40g"],
    "B200-SXM-192GB": ["B200", "NVIDIA B200 HGX"],
    "L40S-PCIE-48GB": ["L40S", "L40S 48GB"],
}

# USD per 8-GPU node, by (sku, condition). 4-GPU nodes are priced at ~52%.
PRICE_RANGES = {
    ("H100-SXM5-80GB", "new"): (200_000, 240_000),
    ("H100-SXM5-80GB", "refurbished"): (165_000, 185_000),
    ("H100-PCIE-80GB", "new"): (150_000, 175_000),
    ("H200-SXM-141GB", "new"): (285_000, 320_000),
    ("H200-SXM-141GB", "used"): (240_000, 260_000),
    ("A100-SXM4-80GB", "new"): (110_000, 125_000),
    ("A100-SXM4-80GB", "refurbished"): (75_000, 90_000),
    ("A100-SXM4-80GB", "used"): (65_000, 78_000),
    ("A100-SXM4-40GB", "new"): (60_000, 70_000),
    ("A100-SXM4-40GB", "used"): (45_000, 55_000),
    ("A100-SXM4-40GB", "refurbished"): (50_000, 58_000),
    ("B200-SXM-192GB", "new"): (430_000, 480_000),
    ("L40S-PCIE-48GB", "new"): (70_000, 82_000),
}

rng = random.Random(SEED)


@dataclass
class Spec:
    dealer_key: str
    sku: str
    condition: str
    nodes: int
    gpn: int = 8
    ambiguous_sku: str | None = None  # raw text that matches several SKUs
    missing_condition: bool = False
    mismatch: bool = False  # rendered total != unit x nodes
    eur: bool = False
    expired: bool = False
    lead_range: str | None = None
    ambiguous_date: str | None = None
    # filled in by finish()
    unit: int = 0
    total: int = 0
    lead: int = 0
    valid: date = field(default_factory=lambda: AS_OF)
    sku_text: str = ""

    @property
    def dealer(self) -> str:
        return DEALERS[self.dealer_key][0]

    @property
    def location(self) -> str:
        return DEALERS[self.dealer_key][1]


def q(dealer_key, sku, condition, nodes, **kw) -> Spec:
    s = Spec(dealer_key, sku, condition, nodes, **kw)
    lo, hi = PRICE_RANGES[(sku, condition)]
    unit = rng.randrange(lo, hi + 1, 500)
    if s.gpn == 4:
        unit = round(unit * 0.52 / 500) * 500
    s.unit = unit
    s.total = unit * nodes + (rng.choice([12_000, 25_500, -18_000]) if s.mismatch else 0)
    s.lead = rng.choice([14, 21, 28, 35, 42])
    if s.expired:
        s.valid = AS_OF - timedelta(days=rng.randrange(14, 45))
    else:
        s.valid = date(2026, rng.choice([11, 12]), rng.randrange(13, 29))
        if rng.random() < 0.3:
            s.valid = date(2027, 1, rng.randrange(13, 29))
        if s.valid <= AS_OF + timedelta(days=7):
            s.valid = AS_OF + timedelta(days=20)
    s.sku_text = s.ambiguous_sku or rng.choice(SKU_TEXT[sku])
    return s


def label(s: Spec) -> dict:
    ok = lambda v: {"value": v, "status": "ok"}  # noqa: E731
    flagged = lambda st: {"value": None, "status": st}  # noqa: E731
    return {
        "gpu_sku": flagged("ambiguous") if s.ambiguous_sku else ok(s.sku),
        "gpus_per_node": ok(s.gpn),
        "node_count": ok(s.nodes),
        "condition": {"value": "unknown", "status": "missing"} if s.missing_condition else ok(s.condition),
        "location": ok(s.location),
        "unit_price_usd": flagged("invalid") if s.eur else ok(float(s.unit)),
        "total_price_usd": flagged("invalid") if (s.eur or s.mismatch) else ok(float(s.total)),
        "lead_time_days": flagged("ambiguous") if s.lead_range else ok(s.lead),
        "dealer": ok(s.dealer),
        "valid_until": (flagged("invalid") if s.expired else
                        flagged("ambiguous") if s.ambiguous_date else ok(s.valid.isoformat())),
    }


# ---------------------------------------------------------------- CSV

def csv_v1(specs: list[Spec]) -> str:
    """Vendor column, plain numbers, ISO dates, lead time in days."""
    out = io.StringIO()
    w = csv.writer(out, lineterminator="\n")
    w.writerow(["Vendor", "GPU", "GPUs/Node", "Nodes", "Condition", "Location",
                "Unit Price (USD)", "Total (USD)", "Lead Time (days)", "Valid Until"])
    for s in specs:
        w.writerow([s.dealer, s.sku_text, s.gpn, s.nodes, "" if s.missing_condition else s.condition.title(),
                    s.location, s.unit, s.total, s.lead_range or s.lead, s.ambiguous_date or s.valid.isoformat()])
    return out.getvalue()


def csv_v2(specs: list[Spec]) -> str:
    """Dealer in a preamble line, currency column, formatted prices, an unmapped column."""
    out = io.StringIO()
    w = csv.writer(out, lineterminator="\n")
    w.writerow([f"Dealer: {specs[0].dealer}"])
    w.writerow([])
    w.writerow(["Model", "GPU Count", "Qty", "Cond", "Ships From", "Price/Node", "Extended Price",
                "Lead Time", "Expires", "Currency", "Warranty"])
    for s in specs:
        lead = s.lead_range or (f"{s.lead // 7} weeks" if s.lead % 7 == 0 and rng.random() < 0.5 else f"{s.lead} days")
        w.writerow([s.sku_text, s.gpn, s.nodes, "" if s.missing_condition else s.condition,
                    s.location, f"${s.unit:,.2f}", f"${s.total:,.2f}", lead,
                    s.ambiguous_date or s.valid.strftime("%b %d, %Y"), "EUR" if s.eur else "USD",
                    rng.choice(["1 year", "3 years", "90 days"])])
    return out.getvalue()


def csv_v3(specs: list[Spec]) -> str:
    """'8x' / '8 GPUs' config strings, US slash dates, supplier column, notes column."""
    out = io.StringIO()
    w = csv.writer(out, lineterminator="\n")
    w.writerow(["Card", "Config", "Quantity", "State", "Warehouse", "Unit $", "Total $", "ETA",
                "Quote Valid Until", "Supplier", "Notes"])
    for s in specs:
        cfg = rng.choice([f"{s.gpn}x", f"{s.gpn} GPUs"])
        lead = s.lead_range or (f"{s.lead // 7} weeks" if s.lead % 7 == 0 else f"{s.lead} days")
        w.writerow([s.sku_text, cfg, s.nodes, "" if s.missing_condition else s.condition, s.location,
                    f"${s.unit:,}", f"${s.total:,}", lead, s.ambiguous_date or s.valid.strftime("%m/%d/%Y"),
                    s.dealer, rng.choice(["", "incl. rails", "NICs not included", "price firm"])])
    return out.getvalue()


# ---------------------------------------------------------------- XLSX

def xlsx_bytes(specs: list[Spec]) -> bytes:
    """Merged title row, blank rows, two-level merged headers, a footer note."""
    wb = Workbook()
    ws = wb.active
    ws.title = "Quote"
    cur = "EUR" if specs[0].eur else "USD"
    ws["A1"] = f"Quotation — Dealer: {specs[0].dealer}"
    ws["A1"].font = Font(bold=True, size=14)
    ws.merge_cells("A1:I1")
    ws["A3"] = f"Prepared {AS_OF - timedelta(days=rng.randrange(3, 10)):%Y-%m-%d} for RFQ desk"
    ws.merge_cells("A3:I3")
    groups = [("A5:B5", "Hardware"), ("C5:E5", "Configuration"), ("F5:G5", f"Pricing ({cur})"), ("H5:I5", "Terms")]
    for rng_ref, text in groups:
        ws[rng_ref.split(":")[0]] = text
        ws.merge_cells(rng_ref)
        ws[rng_ref.split(":")[0]].alignment = Alignment(horizontal="center")
    headers = ["GPU Model", "Condition", "GPUs per node", "Node count", "Location", "Unit", "Total",
               "Lead time (days)", "Valid until"]
    for i, h in enumerate(headers, start=1):
        ws.cell(row=6, column=i, value=h).font = Font(bold=True)
    row = 7
    for n, s in enumerate(specs):
        if n == 1:
            row += 1  # an extra blank row between data rows
        values = [s.sku_text, None if s.missing_condition else s.condition.capitalize(), s.gpn, s.nodes,
                  s.location, s.unit, s.total, s.lead_range or s.lead,
                  s.ambiguous_date or datetime(s.valid.year, s.valid.month, s.valid.day)]
        for i, v in enumerate(values, start=1):
            c = ws.cell(row=row, column=i, value=v)
            if i == 9 and isinstance(v, datetime):
                c.number_format = "yyyy-mm-dd"
        row += 1
    ws.cell(row=row + 1, column=1, value="Notes: prices exclude freight and import duties.")
    for col, width in zip("ABCDEFGHI", [22, 13, 14, 11, 16, 12, 14, 16, 13]):
        ws.column_dimensions[col].width = width
    buf = io.BytesIO()
    wb.save(buf)
    return _stable_zip(buf.getvalue())


def _stable_zip(data: bytes) -> bytes:
    """Rewrite the XLSX zip with fixed timestamps so the bytes (and hash) are reproducible."""
    src = zipfile.ZipFile(io.BytesIO(data))
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as dst:
        for info in src.infolist():
            content = src.read(info.filename)
            if info.filename == "docProps/core.xml":
                import re
                content = re.sub(rb"<dcterms:(created|modified)([^>]*)>[^<]*<",
                                 rb"<dcterms:\1\2>2026-10-20T00:00:00Z<", content)
            zi = zipfile.ZipInfo(info.filename, date_time=(2026, 10, 20, 0, 0, 0))
            zi.compress_type = zipfile.ZIP_DEFLATED
            dst.writestr(zi, content)
    return out.getvalue()


# ---------------------------------------------------------------- emails

def money(v: int, eur: bool = False) -> str:
    return f"€{v:,}" if eur else f"${v:,}"


def email_prose_single(s: Spec) -> str:
    return f"""From: {s.dealer} <quotes@bluefin-servers.example>
To: rfq-desk@buyer.example
Subject: RE: RFQ-1001 H100 nodes
Date: Mon, 26 Oct 2026 09:14:00 -0500

Hi team,

Thanks for sending the RFQ over. We can offer {s.nodes} x {s.gpn}-GPU {s.sku_text} nodes, brand new,
at {money(s.unit)} per node. Total for the order is {money(s.total)}.
Lead time is {s.lead // 7} weeks from PO.
Ships from {s.location}.
This quote is valid until {s.valid:%B %d, %Y}.

Best,
Dana Whitfield
{s.dealer}
"""


def email_two_quotes(a: Spec, b: Spec) -> str:
    return f"""From: {a.dealer} <sales@cobalt-racks.example>
To: rfq-desk@buyer.example
Subject: Two configs for your RFQs
Date: Tue, 27 Oct 2026 16:02:00 -0700

Hello,

Two options for you below.

Option A: {a.nodes} x {a.gpn}-GPU {a.sku_text} nodes, {a.condition}, {money(a.unit)} per node, total {money(a.total)}, lead time {a.lead} days.
Option B: {b.nodes} x {b.gpn}-GPU {b.sku_text} nodes, {b.condition}, {money(b.unit)} per node, total {money(b.total)}, lead time {b.lead} days.

Both options ship from {a.location} and are valid through {a.valid:%b %d, %Y}.

Regards,
Luis Moreno
{a.dealer}
"""


def email_inline_table(specs: list[Spec]) -> str:
    rows = "\n".join(
        f"| {s.sku_text} | {s.gpn} | {s.nodes} | {s.condition} | {s.unit:,} | {s.total:,} | {s.lead} days | {s.valid.isoformat()} |"
        for s in specs)
    return f"""From: {specs[0].dealer} <desk@meridian-gpu.example>
To: rfq-desk@buyer.example
Subject: Pricing as discussed
Date: Wed, 28 Oct 2026 11:30:00 -0700

Hi,

Pricing as discussed on the call:

| GPU | GPUs/node | Nodes | Condition | Unit price (USD) | Total (USD) | Lead time | Valid until |
|-----|-----------|-------|-----------|------------------|-------------|-----------|-------------|
{rows}

All units ship from {specs[0].location}.

Thanks,
Ari Sato
{specs[0].dealer}
"""


def email_forwarded(s: Spec) -> str:
    return f"""From: Priya (RFQ desk) <rfq-desk@buyer.example>
To: ops-intake@buyer.example
Subject: Fwd: RE: RFQ-1001
Date: Thu, 29 Oct 2026 08:45:00 -0700

FYI, forwarding this one for intake. Original below.

---------- Forwarded message ---------
From: {s.dealer} <sales@tidewater-systems.example>
Date: Wed, 28 Oct 2026 17:20:00 -0700
Subject: RE: RFQ-1001

> Hi Priya,
>
> Quote for RFQ-1001: {s.nodes} x {s.gpn}-GPU {s.sku_text} nodes, new units.
> Unit price: {money(s.unit)} per node
> Total: {money(s.total)}
> Lead time: {s.lead} days
> Ships from {s.location}.
> Valid until {s.valid.isoformat()}.
>
> Sam Okafor
> {s.dealer}
"""


def email_words(s: Spec) -> str:
    words = {14: "two", 21: "three", 28: "four", 35: "five", 42: "six"}
    return f"""From: {s.dealer} <hello@oakline-tech.example>
To: rfq-desk@buyer.example
Subject: H200 availability
Date: Thu, 29 Oct 2026 13:05:00 -0700

Hi there,

Good news on the H200 side. We have {s.nodes} x {s.gpn}-GPU {s.sku_text} nodes, new, at {money(s.unit)} per node
(total {money(s.total)}). We can deliver in about {words[s.lead]} weeks.
Everything is staged at our {s.location} facility.
Valid until {s.valid:%d %B %Y}.

Cheers,
Morgan Lee
{s.dealer}
"""


def email_eur(s: Spec) -> str:
    return f"""From: {s.dealer} <angebote@sablewood-it.example>
To: rfq-desk@buyer.example
Subject: Angebot / quote H200
Date: Fri, 30 Oct 2026 10:00:00 +0100

Hello,

As requested: {s.nodes} x {s.gpn}-GPU {s.sku_text} nodes, new, {money(s.unit, True)} per node,
total {money(s.total, True)}. Lead time {s.lead} days. Ships from {s.location}.
Valid until {s.valid.isoformat()}.

Kind regards,
Jonas Becker
{s.dealer}
"""


def email_ambiguous(s: Spec) -> str:
    return f"""From: {s.dealer} <rfq@quarry-compute.example>
To: rfq-desk@buyer.example
Subject: quick quote
Date: Fri, 30 Oct 2026 15:40:00 -0400

hey - quick one before the weekend.
{s.nodes} x {s.gpn}-GPU {s.sku_text} nodes, new, {money(s.unit)} per node, total {money(s.total)}.
lead time {s.lead_range}. ships from {s.location}. valid until {s.valid:%b %d, %Y}.

- Chris
{s.dealer}
"""


# ---------------------------------------------------------------- dataset

H1, H1P, H2, A80, A40, B2, L4 = ("H100-SXM5-80GB", "H100-PCIE-80GB", "H200-SXM-141GB",
                                 "A100-SXM4-80GB", "A100-SXM4-40GB", "B200-SXM-192GB", "L40S-PCIE-48GB")


def build() -> tuple[dict[str, bytes], dict]:
    files: dict[str, bytes] = {}
    labels: dict[str, dict] = {}

    def add(name: str, content: str | bytes, specs: list[Spec]):
        files[name] = content.encode("utf-8") if isinstance(content, str) else content
        labels[name] = {"duplicate_of": None, "quotes": [label(s) for s in specs]}

    csvs = [
        ("01_northwind_quote.csv", csv_v1, [q("northwind", H1, "new", 16), q("northwind", A80, "refurbished", 32),
                                           q("northwind", L4, "new", 4)]),
        ("02_helix_rfq_response.csv", csv_v2, [q("helix", H1, "new", 16), q("helix", H2, "new", 8),
                                               q("helix", H1, "new", 16, mismatch=True)]),
        ("03_ridgeline_pricing.csv", csv_v3, [q("ridgeline", H1, "new", 16, ambiguous_sku="H100"),
                                              q("ridgeline", B2, "new", 4), q("ridgeline", A40, "used", 10)]),
        ("04_parallax_quote.csv", csv_v1, [q("parallax", H1, "new", 16, expired=True), q("parallax", H1P, "new", 16),
                                          q("parallax", A80, "refurbished", 32)]),
        ("05_vantage_quote.csv", csv_v2, [q("vantage", H1, "new", 16, missing_condition=True),
                                          q("vantage", H2, "new", 8), q("vantage", L4, "new", 6, gpn=4)]),
        ("06_quarry_offer.csv", csv_v3, [q("quarry", H1, "refurbished", 16, lead_range="3-4 weeks"),
                                         q("quarry", A80, "refurbished", 32, ambiguous_date="03/01/2027"),
                                         q("quarry", B2, "new", 2)]),
        ("07_tidewater_quote.csv", csv_v1, [q("tidewater", H1, "new", 16, gpn=4), q("tidewater", H2, "new", 8, expired=True),
                                            q("tidewater", A80, "used", 32)]),
        ("08_meridian_quote.csv", csv_v2, [q("meridian", H1, "new", 16), q("meridian", A40, "new", 12)]),
        ("09_oakline_pricing.csv", csv_v3, [q("oakline", H1, "new", 16), q("oakline", H1P, "new", 8),
                                            q("oakline", L4, "new", 8)]),
    ]
    for name, render, specs in csvs:
        add(name, render(specs), specs)

    xlsxs = [
        ("11_bluefin_quotation.xlsx", [q("bluefin", H1, "new", 16), q("bluefin", H2, "new", 8), q("bluefin", B2, "new", 4)]),
        ("12_cobalt_quotation.xlsx", [q("cobalt", A80, "refurbished", 32, ambiguous_sku="A100 SXM4"),
                                      q("cobalt", A80, "refurbished", 32), q("cobalt", H1, "refurbished", 16)]),
        ("13_helix_quotation.xlsx", [q("helix", H1, "new", 16), q("helix", H1, "new", 16, expired=True),
                                     q("helix", L4, "new", 10, gpn=4)]),
        ("14_northwind_quotation.xlsx", [q("northwind", H2, "new", 8, missing_condition=True),
                                         q("northwind", A80, "refurbished", 32), q("northwind", H1P, "new", 16)]),
        ("15_ridgeline_quotation.xlsx", [q("ridgeline", H1, "new", 16), q("ridgeline", A80, "new", 32, mismatch=True),
                                         q("ridgeline", B2, "new", 8)]),
        ("16_sablewood_angebot.xlsx", [q("sablewood", H1, "new", 16, eur=True), q("sablewood", H2, "new", 8, eur=True),
                                       q("sablewood", A80, "refurbished", 32, eur=True)]),
        ("17_parallax_quotation.xlsx", [q("parallax", H2, "new", 8), q("parallax", L4, "new", 16),
                                        q("parallax", A40, "refurbished", 20)]),
        ("18_vantage_quotation.xlsx", [q("vantage", H1, "new", 16), q("vantage", A80, "refurbished", 32),
                                       q("vantage", H2, "used", 8)]),
    ]
    for name, specs in xlsxs:
        add(name, xlsx_bytes(specs), specs)

    s = q("bluefin", H1, "new", 16)
    s.lead = 21
    add("21_bluefin_reply.eml", email_prose_single(s), [s])
    a, b = q("cobalt", H2, "new", 8), q("cobalt", A80, "refurbished", 32)
    b.valid = a.valid  # one shared validity line covers both options
    add("22_cobalt_two_options.eml", email_two_quotes(a, b), [a, b])
    m = [q("meridian", H2, "new", 8), q("meridian", B2, "new", 4), q("meridian", L4, "new", 8)]
    add("23_meridian_inline_table.txt", email_inline_table(m), m)
    s = q("tidewater", H1, "new", 16)
    add("24_fwd_tidewater.eml", email_forwarded(s), [s])
    s = q("oakline", H2, "new", 8)
    add("25_oakline_h200.eml", email_words(s), [s])
    s = q("sablewood", H2, "new", 8, eur=True)
    add("26_sablewood_eur.eml", email_eur(s), [s])
    s = q("quarry", H1, "new", 16, ambiguous_sku="H100", lead_range="3-4 weeks")
    add("27_quarry_quick_quote.txt", email_ambiguous(s), [s])

    # An exact byte-for-byte resend of file 01 under a new name.
    files["10_northwind_quote_resend.csv"] = files["01_northwind_quote.csv"]
    labels["10_northwind_quote_resend.csv"] = {"duplicate_of": "01_northwind_quote.csv", "quotes": []}
    return dict(sorted(files.items())), dict(sorted(labels.items()))


RFQS = {
    "as_of": AS_OF.isoformat(),
    "rfqs": [
        {"id": "RFQ-1001", "title": "16× 8-GPU H100 SXM5 nodes, new", "gpu_sku": H1, "gpus_per_node": 8,
         "node_count": 16, "condition": "new"},
        {"id": "RFQ-1002", "title": "8× 8-GPU H200 nodes, new", "gpu_sku": H2, "gpus_per_node": 8,
         "node_count": 8, "condition": "new"},
        {"id": "RFQ-1003", "title": "32× 8-GPU A100 80GB nodes, refurbished", "gpu_sku": A80, "gpus_per_node": 8,
         "node_count": 32, "condition": "refurbished"},
    ],
}


def write(out_dir: Path = ROOT / "data") -> None:
    files, labels = build()
    samples = out_dir / "samples"
    if samples.exists():
        shutil.rmtree(samples)
    samples.mkdir(parents=True)
    for name, content in files.items():
        (samples / name).write_bytes(content)
    (out_dir / "labels.json").write_text(json.dumps(labels, indent=1) + "\n", encoding="utf-8")
    (out_dir / "rfqs.json").write_text(json.dumps(RFQS, indent=1) + "\n", encoding="utf-8")
    n_quotes = sum(len(v["quotes"]) for v in labels.values())
    print(f"wrote {len(files)} files, {n_quotes} labeled quotes to {out_dir}")


if __name__ == "__main__":
    write(Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / "data")
