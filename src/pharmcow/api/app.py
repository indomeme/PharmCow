from __future__ import annotations

import hashlib
import logging
import uuid
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sqlalchemy import select

from pharmcow import __version__
from pharmcow.db import SessionLocal, init_db
from pharmcow.jobs.runner import enqueue, reset_stale_runs
from pharmcow.models import Report, Run, Sample
from pharmcow.settings import settings

log = logging.getLogger(__name__)

BASE_DIR = Path(__file__).resolve().parent.parent
TEMPLATES_DIR = BASE_DIR / "web" / "templates"
STATIC_DIR = BASE_DIR / "web" / "static"

STAGES = [
    ("qc", "Quality control"),
    ("star", "Star alleles"),
    ("parse", "Parse results"),
    ("recommend", "Recommendations"),
    ("report", "Report"),
    ("done", "Done"),
]


@asynccontextmanager
async def lifespan(_: FastAPI):
    init_db()
    reset_stale_runs()
    yield


app = FastAPI(title="PharmCOW", version=__version__, lifespan=lifespan)
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))


def _save_upload(upload: UploadFile, dest: Path) -> tuple[int, str]:
    digest = hashlib.sha256()
    size = 0
    dest.parent.mkdir(parents=True, exist_ok=True)
    with dest.open("wb") as fh:
        while chunk := upload.file.read(1024 * 1024):
            fh.write(chunk)
            digest.update(chunk)
            size += len(chunk)
    return size, digest.hexdigest()


def _run_context(db, run: Run) -> dict:
    samples = db.scalars(
        select(Sample).where(Sample.run_id == run.id).order_by(Sample.barcode)
    ).all()
    reports = {
        r.sample_id: r
        for r in db.scalars(select(Report).where(Report.run_id == run.id)).all()
    }
    keys = [key for key, _ in STAGES]
    if run.status == "done":
        stage_index = len(STAGES) - 1
    elif run.status == "queued":
        stage_index = 0
    elif run.stage in keys:
        stage_index = keys.index(run.stage)
    else:
        stage_index = -1
    totals = {
        "samples": len(samples),
        "drugs": sum(len(s.recs or []) for s in samples),
        "level_a": sum(
            1
            for s in samples
            for d in (s.recs or [])
            if str(d.get("cpic_level", "")).upper() == "A"
        ),
    }
    return {
        "run": run,
        "samples": samples,
        "reports": reports,
        "stages": STAGES,
        "stage_index": stage_index,
        "totals": totals,
    }


@app.get("/", response_class=HTMLResponse)
def index(request: Request):
    with SessionLocal() as db:
        runs = db.scalars(select(Run).order_by(Run.created_at.desc()).limit(50)).all()
    return templates.TemplateResponse(
        request, "index.html", {"runs": runs, "version": __version__}
    )


@app.post("/upload")
def upload(
    vcf: UploadFile = File(...),
    tbi: UploadFile | None = File(None),
    assembly: str = Form("auto"),
):
    run_id = uuid.uuid4().hex
    run_dir = settings.uploads_dir / run_id
    dest = run_dir / "sample.vcf.gz"
    size, sha = _save_upload(vcf, dest)
    if size == 0:
        raise HTTPException(status_code=400, detail="Empty VCF upload.")

    tbi_path = None
    if tbi is not None and tbi.filename:
        tbi_path = Path(str(dest) + ".tbi")
        _save_upload(tbi, tbi_path)

    assembly_value = "" if assembly == "auto" else assembly
    with SessionLocal() as db:
        db.add(
            Run(
                id=run_id,
                filename=vcf.filename or "sample.vcf.gz",
                sha256=sha,
                assembly=assembly_value,
                status="queued",
                stage="queued",
                params={
                    "vcf_path": str(dest),
                    "index_path": str(tbi_path) if tbi_path else None,
                    "bytes": size,
                },
            )
        )
        db.commit()

    enqueue(run_id)
    return RedirectResponse(url=f"/runs/{run_id}", status_code=303)


@app.get("/runs/{run_id}", response_class=HTMLResponse)
def run_detail(request: Request, run_id: str):
    with SessionLocal() as db:
        run = db.get(Run, run_id)
        if not run:
            raise HTTPException(status_code=404, detail="Run not found")
        ctx = _run_context(db, run)
    return templates.TemplateResponse(request, "run.html", ctx)


@app.get("/runs/{run_id}/status", response_class=HTMLResponse)
def run_status(request: Request, run_id: str):
    with SessionLocal() as db:
        run = db.get(Run, run_id)
        if not run:
            raise HTTPException(status_code=404, detail="Run not found")
        ctx = _run_context(db, run)
    return templates.TemplateResponse(request, "_status.html", ctx)


def _report_paths(run_id: str, sample_id: str) -> tuple[Path, Path | None]:
    with SessionLocal() as db:
        report = db.scalar(
            select(Report).where(
                Report.run_id == run_id, Report.sample_id == sample_id
            )
        )
        if not report:
            raise HTTPException(status_code=404, detail="Report not ready")
        return Path(report.html_path), (Path(report.pdf_path) if report.pdf_path else None)


@app.get("/runs/{run_id}/report/{sample_id}", response_class=HTMLResponse)
def report_view(request: Request, run_id: str, sample_id: str):
    with SessionLocal() as db:
        run = db.get(Run, run_id)
        sample = db.get(Sample, sample_id)
        report = db.scalar(
            select(Report).where(
                Report.run_id == run_id, Report.sample_id == sample_id
            )
        )
        if not run or not sample or not report:
            raise HTTPException(status_code=404, detail="Report not ready")
        has_pdf = bool(report.pdf_path)
    return templates.TemplateResponse(
        request,
        "report_view.html",
        {
            "run": run,
            "sample": sample,
            "has_pdf": has_pdf,
        },
    )


@app.get("/runs/{run_id}/report/{sample_id}/raw", response_class=HTMLResponse)
def report_raw(run_id: str, sample_id: str):
    html_path, _ = _report_paths(run_id, sample_id)
    if not html_path.exists():
        raise HTTPException(status_code=404, detail="HTML report missing")
    return FileResponse(html_path, media_type="text/html")


@app.get("/runs/{run_id}/report/{sample_id}/pdf")
def report_pdf(run_id: str, sample_id: str):
    _, pdf_path = _report_paths(run_id, sample_id)
    if not pdf_path or not pdf_path.exists():
        raise HTTPException(status_code=404, detail="PDF report missing")
    return FileResponse(
        pdf_path,
        media_type="application/pdf",
        filename=f"{sample_id}.pdf",
    )


@app.get("/healthz")
def healthz():
    return {"ok": True, "version": __version__}
