import io
from datetime import datetime

from openpyxl import Workbook

from intake.normalize import normalize_quote
from intake.parsers import parse_file
from intake.parsers.spreadsheet import map_columns, normalize_header
from intake.schema import Status


def test_alias_table_maps_gpu_card_model_to_sku():
    for h in ["GPU", "Card", "Model"]:
        mapping, unmapped = map_columns([h, "Qty", "Unit Price (USD)"])
        assert mapping[0] == "gpu_sku" and not unmapped


def test_unmapped_columns_are_listed_not_dropped():
    mapping, unmapped = map_columns(["GPU", "Nodes", "Total", "Warranty", "NIC"])
    assert set(mapping.values()) == {"gpu_sku", "node_count", "total_price_usd"}
    assert unmapped == ["Warranty", "NIC"]


def test_header_currency_hint():
    assert normalize_header("Unit Price (USD)") == ("unit price", "USD")
    assert normalize_header("Unit $") == ("unit", "USD")
    assert normalize_header("Total (EUR)") == ("total", "EUR")


CSV = b"""Dealer: Acme Example Hardware

GPU,GPUs/Node,Nodes,Condition,Location,Unit Price (USD),Total (USD),Lead Time (days),Valid Until,Rack Units

H100 SXM5 80GB,8x,16,New,"Dallas, TX",220000,3520000,21,2026-12-15,4U
H100,8 GPUs,16,,"Dallas, TX",210000,3360000,14,2026-12-15,4U
Total,,,,,,6880000,,,
"""


def test_csv_preamble_blank_rows_and_summary_row():
    p = parse_file("q.csv", CSV)
    assert p.error is None
    assert len(p.quotes) == 2  # blank rows and the "Total" row are skipped
    assert p.unmapped_columns == ["Rack Units"]
    first = normalize_quote(p.quotes[0])
    assert all(f.status == Status.OK for f in first.values())
    assert first["dealer"].value == "Acme Example Hardware" and first["dealer"].source == "A1"
    assert first["gpus_per_node"].value == 8 and first["gpu_sku"].source == "A5"
    second = normalize_quote(p.quotes[1])
    assert second["gpu_sku"].status == Status.AMBIGUOUS
    assert second["condition"].status == Status.MISSING and second["condition"].source == "D6"


def test_no_header_is_an_error():
    p = parse_file("junk.csv", b"hello,world\n1,2\n")
    assert p.error and not p.quotes


def _xlsx(currency: str) -> bytes:
    wb = Workbook()
    ws = wb.active
    ws["A1"] = "Quotation — Dealer: Example Racks"
    ws.merge_cells("A1:F1")
    ws["C3"] = f"Pricing ({currency})"
    ws.merge_cells("C3:D3")
    for i, h in enumerate(["GPU Model", "Node count", "Unit", "Total", "Condition", "Valid until"], 1):
        ws.cell(row=4, column=i, value=h)
    ws.append(["A100 80GB SXM4", 32, 80000, 2560000, "Refurbished", datetime(2026, 12, 20)])
    ws.append([])
    ws.append(["B200", 4, 450000, 1800000, "New", datetime(2026, 12, 20)])
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def test_xlsx_merged_headers_carry_currency_and_blank_rows_skipped():
    p = parse_file("q.xlsx", _xlsx("USD"))
    assert p.quote_labels == ["row 5", "row 7"]
    f = normalize_quote(p.quotes[0])
    assert f["unit_price_usd"].value == 80000.0 and f["unit_price_usd"].status == Status.OK
    assert f["valid_until"].value == "2026-12-20"
    assert f["dealer"].value == "Example Racks"


def test_xlsx_eur_prices_are_flagged():
    f = normalize_quote(parse_file("q.xlsx", _xlsx("EUR")).quotes[0])
    assert f["unit_price_usd"].status == Status.INVALID and f["unit_price_usd"].code == "non_usd"
    assert f["total_price_usd"].status == Status.INVALID
