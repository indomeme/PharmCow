from __future__ import annotations

import json
import logging
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape

log = logging.getLogger(__name__)

TEMPLATES_DIR = Path(__file__).resolve().parent.parent / "web" / "templates"

env = Environment(
    loader=FileSystemLoader(str(TEMPLATES_DIR)),
    autoescape=select_autoescape(["html", "xml"]),
)

_LEVEL_ORDER = ["A", "B", "C", "D"]


def _tone(phenotype: str, callable_: bool) -> str:
    if not callable_:
        return "unknown"
    text = phenotype.lower()
    if "normal" in text:
        return "normal"
    if "intermediate" in text:
        return "intermediate"
    if "poor" in text or "ultrarapid" in text or "rapid" in text:
        return "high"
    return "unknown"


def build_report_data(
    *,
    run_id: str,
    barcode: str,
    filename: str,
    assembly: str,
    star: dict[str, dict[str, object]],
    recs: list[dict[str, object]],
) -> dict[str, object]:
    genes = []
    for gene, call in sorted(star.items()):
        callable_ = bool(call.get("callable", False))
        phenotype = str(call.get("phenotype", "Indeterminate"))
        genes.append(
            {
                "gene": gene,
                "genotype": str(call.get("genotype", "No call")),
                "phenotype": phenotype,
                "callable": callable_,
                "tone": _tone(phenotype, callable_),
            }
        )

    callable_genes = [g for g in genes if g["callable"]]
    indeterminate = [g["gene"] for g in genes if not g["callable"]]

    level_counts = Counter(
        str(d.get("cpic_level") or "Other").upper() for d in recs
    )
    drug_groups = []
    used_levels = set()
    for level in _LEVEL_ORDER:
        drugs = [
            d
            for d in recs
            if str(d.get("cpic_level") or "").upper() == level
        ]
        if drugs:
            used_levels.add(level)
            drug_groups.append({"level": level, "drugs": drugs})
    other = [
        d for d in recs if str(d.get("cpic_level") or "").upper() not in used_levels
    ]
    if other:
        drug_groups.append({"level": "Other", "drugs": other})

    summary = {
        "genes_total": len(genes),
        "genes_called": len(callable_genes),
        "indeterminate": indeterminate,
        "drug_count": len(recs),
        "level_counts": dict(level_counts),
    }

    notes: list[str] = []
    if indeterminate:
        notes.append(
            "Genes marked 'not callable' could not be interpreted from this VCF "
            "(indeterminate or insufficient markers)."
        )
    if not recs:
        notes.append("No CPIC recommendation matched the called phenotypes.")
    notes.append(
        "HLA alleles and CNV/SV calling are outside this pipeline; drugs that "
        "depend on them are not evaluated."
    )
    notes.append(
        "Results depend on public pypgx star-allele definitions and CPIC tables; "
        "they are not a substitute for clinical testing."
    )

    return {
        "run_id": run_id,
        "barcode": barcode,
        "filename": filename,
        "assembly": assembly,
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
        "genes": genes,
        "drugs": recs,
        "drug_groups": drug_groups,
        "summary": summary,
        "notes": notes,
    }


def render_report(
    data: dict[str, object], out_dir: Path, *, make_pdf: bool = True
) -> tuple[Path, Path | None]:
    out_dir.mkdir(parents=True, exist_ok=True)
    barcode = str(data["barcode"])
    html = env.get_template("report.html").render(**data)

    html_path = out_dir / f"{barcode}.html"
    html_path.write_text(html, encoding="utf-8")

    # Also keep a machine-readable copy for debugging.
    (out_dir / f"{barcode}.json").write_text(
        json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    pdf_path: Path | None = None
    if make_pdf:
        try:
            from weasyprint import HTML

            pdf_path = out_dir / f"{barcode}.pdf"
            HTML(string=html, base_url=str(TEMPLATES_DIR)).write_pdf(str(pdf_path))
        except Exception as exc:  # noqa: BLE001 - HTML is still useful without PDF
            log.warning("PDF render failed for %s: %s", barcode, exc)
            pdf_path = None
    return html_path, pdf_path
