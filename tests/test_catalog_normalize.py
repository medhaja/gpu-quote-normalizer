from datetime import date

import pytest

from intake.catalog import Sku, match_sku
from intake.normalize import normalize_field, parse_date, parse_int, parse_lead_time, parse_money
from intake.schema import FieldResult, RawCell, Status
from intake.validators import quote_status, validate


@pytest.mark.parametrize("raw,sku", [
    ("H100 SXM5 80G", Sku.H100_SXM5_80GB),
    ("h100-sxm", Sku.H100_SXM5_80GB),
    ("NVIDIA H100 PCIe 80GB", Sku.H100_PCIE_80GB),
    ("H200", Sku.H200_SXM_141GB),
    ("A100 80GB SXM4", Sku.A100_SXM4_80GB),
    ("a100-40g", Sku.A100_SXM4_40GB),
    ("B200 HGX", Sku.B200_SXM_192GB),
    ("L40S", Sku.L40S_PCIE_48GB),
])
def test_sku_variants_map_to_one_canonical_sku(raw, sku):
    m = match_sku(raw)
    assert m.status == "ok" and m.sku == sku


@pytest.mark.parametrize("raw", ["H100", "H100 80GB", "A100 SXM4", "H100 or H200"])
def test_sku_ambiguous_when_several_candidates(raw):
    m = match_sku(raw)
    assert m.status == "ambiguous" and m.sku is None and len(m.candidates) > 1


def test_ambiguous_reason_names_candidates():
    assert match_sku("H100").reason == "matches H100-SXM5-80GB and H100-PCIE-80GB"


@pytest.mark.parametrize("raw", ["L40", "MI300X", "GH200", ""])
def test_unknown_sku_is_invalid(raw):
    assert match_sku(raw).status == "invalid"


@pytest.mark.parametrize("raw", ["8", "8x", "8 GPUs", "8 gpu", "8.0"])
def test_gpu_count_formats(raw):
    assert parse_int(raw) == (8, Status.OK, None)


def test_quantity_must_be_positive():
    assert parse_int("0")[1] == Status.INVALID
    assert parse_int("eight-ish")[1] == Status.INVALID


@pytest.mark.parametrize("raw,amount,cur", [
    ("$245,000", 245000.0, "USD"),
    ("245000", 245000.0, None),
    ("USD 1,234.50", 1234.5, "USD"),
    ("€230,000", 230000.0, "EUR"),
    ("$245k", 245000.0, "USD"),
])
def test_parse_money(raw, amount, cur):
    assert parse_money(raw) == (amount, cur, None)


def test_parse_money_rejects_junk():
    assert parse_money("call us")[2] is not None
    assert parse_money("$1,23")[2] is not None


@pytest.mark.parametrize("raw,days", [("14", 14), ("14 days", 14), ("3 weeks", 21), ("three weeks", 21), ("about 2 weeks", 14)])
def test_lead_time(raw, days):
    assert parse_lead_time(raw) == (days, Status.OK, None)


def test_lead_time_range_is_ambiguous():
    assert parse_lead_time("3-4 weeks")[1] == Status.AMBIGUOUS
    assert parse_lead_time("10 business days")[1] == Status.AMBIGUOUS


@pytest.mark.parametrize("raw", ["2026-12-15", "Dec 15, 2026", "December 15 2026", "15 Dec 2026", "12/15/2026", "15/12/2026"])
def test_dates(raw):
    assert parse_date(raw) == ("2026-12-15", Status.OK, None)


def test_slash_date_ambiguous_when_both_parts_could_be_month():
    assert parse_date("03/04/2027")[1] == Status.AMBIGUOUS


def cell(text, **kw):
    return RawCell(text=text, source="B2", **kw)


def test_currency_must_be_usd():
    eur = normalize_field("unit_price_usd", cell("230000", currency_hint="EUR"))
    assert eur.status == Status.INVALID and eur.code == "non_usd" and eur.value is None
    unstated = normalize_field("unit_price_usd", cell("230000"))
    assert unstated.status == Status.AMBIGUOUS
    usd_col = normalize_field("unit_price_usd", cell("230000"), RawCell(text="USD", source="H2"))
    assert usd_col.status == Status.OK and usd_col.value == 230000.0
    clash = normalize_field("unit_price_usd", cell("$230000", currency_hint="EUR"))
    assert clash.status == Status.AMBIGUOUS


def test_condition_never_inferred():
    missing = normalize_field("condition", None)
    assert missing.value == "unknown" and missing.status == Status.MISSING
    vague = normalize_field("condition", cell("excellent"))
    assert vague.status == Status.AMBIGUOUS and vague.value is None
    assert normalize_field("condition", cell("Refurb")).value == "refurbished"


def _ok(value, source="X1"):
    return FieldResult(value=value, raw=str(value), status=Status.OK, source=source)


def good_fields(**overrides):
    f = {
        "gpu_sku": _ok("H100-SXM5-80GB"), "gpus_per_node": _ok(8), "node_count": _ok(16),
        "condition": _ok("new"), "location": _ok("Dallas, TX"), "unit_price_usd": _ok(220000.0),
        "total_price_usd": _ok(3520000.0), "lead_time_days": _ok(21), "dealer": _ok("Helix Systems"),
        "valid_until": _ok("2026-12-15"),
    }
    f.update({k: _ok(v) for k, v in overrides.items()})
    return f


AS_OF = date(2026, 11, 2)


def test_valid_quote_passes():
    out = validate(good_fields(), AS_OF)
    assert quote_status(out)[0].value == "parsed"


def test_total_within_one_dollar_is_ok():
    out = validate(good_fields(total_price_usd=3520000.75), AS_OF)
    assert out["total_price_usd"].status == Status.OK


def test_total_mismatch_flagged_but_value_kept():
    out = validate(good_fields(total_price_usd=3600000.0), AS_OF)
    t = out["total_price_usd"]
    assert t.status == Status.INVALID and t.code == "total_mismatch" and t.value == 3600000.0
    assert quote_status(out)[0].value == "needs_review"
    # A later fix to the unit price clears the flag on revalidation.
    fixed = dict(out, unit_price_usd=_ok(225000.0))
    assert validate(fixed, AS_OF)["total_price_usd"].status == Status.OK


def test_expired_quote_is_rejected():
    out = validate(good_fields(valid_until="2026-10-01"), AS_OF)
    assert out["valid_until"].code == "expired"
    status, reason = quote_status(out)
    assert status.value == "rejected" and "expired" in reason


def test_reviewer_rejection_wins():
    assert quote_status(good_fields(), "duplicate of an earlier quote")[0].value == "rejected"
