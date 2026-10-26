from __future__ import annotations

import logging
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path

from pharmcow.db import SessionLocal
from pharmcow.models import Report, Run, Sample
from pharmcow.recommend.engine import build_recommendations
from pharmcow.report.render import build_report_data, render_report
from pharmcow.settings import settings
from pharmcow.star.parse import parse_results
from pharmcow.star.pypgx_runner import run_star
from pharmcow.star.qc import QcError, qc_vcf

log = logging.getLogger(__name__)

_executor = ThreadPoolExecutor(max_workers=settings.max_workers)


def enqueue(run_id: str) -> None:
    _executor.submit(process_run, run_id)


def _update(run_id: str, **fields: object) -> None:
    with SessionLocal() as db:
        run = db.get(Run, run_id)
        if not run:
            return
        for key, value in fields.items():
            setattr(run, key, value)
        db.commit()


def _fail(run_id: str, message: str) -> None:
    log.error("run %s failed: %s", run_id, message)
    _update(
        run_id,
        status="failed",
        error=message,
        finished_at=datetime.now(timezone.utc),
    )


def process_run(run_id: str) -> None:
    with SessionLocal() as db:
        run = db.get(Run, run_id)
        if not run:
            return
        params = dict(run.params or {})
        assembly_hint = run.assembly or "auto"
        filename = run.filename

    vcf_path = Path(str(params.get("vcf_path", "")))
    try:
        _update(run_id, status="running", stage="qc", error=None)
        qc = qc_vcf(vcf_path, assembly_hint)
        _update(
            run_id,
            assembly=qc.assembly,
            n_samples=len(qc.samples),
            phased=qc.phased,
            stage="star",
        )

        work_dir = settings.data_dir / "work" / run_id
        star_run = run_star(
            qc.path,
            work_dir,
            qc.assembly,
            threads=settings.pypgx_threads,
            genes=settings.gene_list,
        )
        if not star_run.results:
            raise RuntimeError("pypgx did not run for any gene.")

        _update(run_id, stage="parse")
        star = parse_results(work_dir, qc.samples, genes=settings.gene_list)
        called = sum(
            1
            for genes in star.values()
            for call in genes.values()
            if call.get("callable")
        )
        if called == 0:
            failed = ", ".join(r.gene for r in star_run.failed[:5]) or "unknown"
            raise RuntimeError(
                f"pypgx produced no callable genotypes (failed genes: {failed}). "
                "Check the VCF overlaps the gene regions and is phased."
            )

        _update(run_id, stage="recommend")
        recs = build_recommendations(star)

        _update(run_id, stage="report")
        report_dir = settings.reports_dir / run_id
        sample_ids: dict[str, str] = {}
        with SessionLocal() as db:
            db.query(Report).filter(Report.run_id == run_id).delete()
            db.query(Sample).filter(Sample.run_id == run_id).delete()
            db.commit()
            for barcode, genes in star.items():
                sample = Sample(
                    id=uuid.uuid4().hex,
                    run_id=run_id,
                    barcode=barcode,
                    star=genes,
                    recs=recs.get(barcode, []),
                )
                db.add(sample)
                db.flush()
                sample_ids[barcode] = sample.id
                db.add(
                    Report(
                        id=uuid.uuid4().hex,
                        run_id=run_id,
                        sample_id=sample.id,
                    )
                )
            db.commit()

        for barcode, genes in star.items():
            data = build_report_data(
                run_id=run_id,
                barcode=barcode,
                filename=filename,
                assembly=qc.assembly,
                star=genes,
                recs=recs.get(barcode, []),
            )
            html_path, pdf_path = render_report(data, report_dir)
            with SessionLocal() as db:
                report = (
                    db.query(Report)
                    .filter(Report.sample_id == sample_ids[barcode])
                    .first()
                )
                if report:
                    report.html_path = str(html_path)
                    report.pdf_path = str(pdf_path) if pdf_path else None
                    db.commit()

        _update(
            run_id,
            status="done",
            stage="done",
            finished_at=datetime.now(timezone.utc),
        )
    except QcError as exc:
        _fail(run_id, str(exc))
    except Exception as exc:  # noqa: BLE001 - background job must record failure
        log.exception("unexpected error in run %s", run_id)
        _fail(run_id, f"{type(exc).__name__}: {exc}")


def reset_stale_runs() -> None:
    with SessionLocal() as db:
        stale = (
            db.query(Run)
            .filter(Run.status.in_(["queued", "running"]))
            .all()
        )
        for run in stale:
            run.status = "failed"
            run.error = "Server restarted while this run was in progress."
            run.finished_at = datetime.now(timezone.utc)
        if stale:
            db.commit()
