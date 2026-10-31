"""FastAPI app with server-rendered pages."""

from __future__ import annotations

from pathlib import Path
from urllib.parse import quote as urlquote

from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from intake.compare import compare, load_rfqs, quote_sort_key
from intake.extractors import active_extractor
from intake.parsers import parse_file
from intake.pipeline import (ReviewError, get_as_of, inbox, ingest, project, quote_events, reject_quote,
                             review_field)
from intake.schema import FIELD_LABELS, QUOTE_FIELDS, QuoteStatus
from intake.store import RawFile, make_engine, make_session_factory

HERE = Path(__file__).parent


def money(v) -> str:
    return "—" if v is None else f"${float(v):,.0f}"


def create_app(db_url: str | None = None) -> FastAPI:
    app = FastAPI(title="GPU Quote Intake (prototype)")
    sessions = make_session_factory(make_engine(db_url))
    templates = Jinja2Templates(directory=HERE / "templates")
    templates.env.filters["money"] = money
    templates.env.globals.update(FIELD_LABELS=FIELD_LABELS, QUOTE_FIELDS=QUOTE_FIELDS, as_of=get_as_of,
                                 extractor_name=lambda: active_extractor()[0].value)
    app.mount("/static", StaticFiles(directory=HERE / "static"), name="static")

    def render(request: Request, name: str, **ctx):
        with sessions() as s:
            ctx.setdefault("review_count", sum(1 for v in project(s).values() if v.status != QuoteStatus.PARSED
                                               and not v.rejected_reason))
        return templates.TemplateResponse(request, name, ctx)

    @app.get("/", response_class=HTMLResponse)
    def inbox_page(request: Request, msg: str | None = None):
        with sessions() as s:
            rows = inbox(s)
            views = project(s)
        totals = {st.value: sum(1 for v in views.values() if v.status == st) for st in QuoteStatus}
        return render(request, "inbox.html", rows=rows, totals=totals, n_quotes=len(views),
                      n_files=sum(1 for r in rows if not r.duplicate_of),
                      n_dupes=sum(1 for r in rows if r.duplicate_of), msg=msg, page="inbox")

    @app.post("/upload")
    async def upload(file: UploadFile = File(...)):
        content = await file.read()
        if not content:
            return RedirectResponse("/?msg=" + urlquote("Empty file, nothing ingested."), status_code=303)
        with sessions() as s:
            r = ingest(s, file.filename or "upload", content)
        if r.status == "duplicate":
            return RedirectResponse("/?msg=" + urlquote(f"{file.filename}: {r.message}"), status_code=303)
        return RedirectResponse(f"/files/{r.file_id}", status_code=303)

    @app.get("/files/{file_id}", response_class=HTMLResponse)
    def file_page(request: Request, file_id: int):
        with sessions() as s:
            raw = s.get(RawFile, file_id)
            if raw is None:
                raise HTTPException(404, "file not found")
            views = sorted((v for v in project(s).values() if v.file_id == file_id),
                           key=lambda v: quote_sort_key(v.quote_id))
            parsed_ev = next(e for e in quote_events(s, views[0].quote_id) if e.type == "file_parsed").data \
                if views else None
        parsed = parse_file(raw.filename, raw.content)  # deterministic: re-render the raw view
        return render(request, "file.html", raw=raw, parsed=parsed, views=views, meta=parsed_ev or {
            "unmapped_columns": parsed.unmapped_columns, "column_map": parsed.column_map,
            "notes": parsed.notes, "error": parsed.error}, page="inbox")

    @app.get("/review", response_class=HTMLResponse)
    def review_page(request: Request, error: str | None = None, q: str | None = None):
        with sessions() as s:
            views = [v for v in project(s).values() if v.status != QuoteStatus.PARSED and not v.rejected_reason]
        views.sort(key=lambda v: quote_sort_key(v.quote_id))
        return render(request, "review.html", views=views, error=error, error_q=q, page="review")

    @app.post("/review/{quote_id}/reject")
    def reject(quote_id: str, reason: str = Form("")):
        with sessions() as s:
            try:
                reject_quote(s, quote_id, reason)
            except ReviewError as e:
                return RedirectResponse(f"/review?q={quote_id}&error={urlquote(str(e))}#{quote_id}", status_code=303)
        return RedirectResponse("/review", status_code=303)

    @app.post("/review/{quote_id}/{field}")
    def resolve(quote_id: str, field: str, value: str = Form(""), reason: str = Form("")):
        with sessions() as s:
            try:
                review_field(s, quote_id, field, value, reason)
            except ReviewError as e:
                return RedirectResponse(f"/review?q={quote_id}&error={urlquote(str(e))}#{quote_id}", status_code=303)
        return RedirectResponse(f"/review#{quote_id}", status_code=303)

    @app.get("/compare")
    def compare_default():
        return RedirectResponse(f"/compare/{load_rfqs()['rfqs'][0]['id']}", status_code=307)

    @app.get("/compare/{rfq_id}", response_class=HTMLResponse)
    def compare_page(request: Request, rfq_id: str):
        rfqs = load_rfqs()["rfqs"]
        rfq = next((r for r in rfqs if r["id"] == rfq_id), None)
        if rfq is None:
            raise HTTPException(404, "RFQ not found")
        with sessions() as s:
            result = compare(project(s), rfq)
        return render(request, "compare.html", rfqs=rfqs, rfq=rfq, c=result, page="compare")

    @app.get("/quotes/{quote_id}", response_class=HTMLResponse)
    def quote_page(request: Request, quote_id: str):
        with sessions() as s:
            view = project(s).get(quote_id)
            if view is None:
                raise HTTPException(404, "quote not found")
            events = quote_events(s, quote_id)
        return render(request, "quote.html", v=view, events=events, page="")

    @app.get("/healthz")
    def healthz():
        return {"ok": True}

    return app
