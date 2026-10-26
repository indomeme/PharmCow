from __future__ import annotations

import csv
import io
import zipfile
from pathlib import Path

from pharmcow.star.genes import GENES


def _read_results_zip(path: Path) -> list[dict[str, str]]:
    with zipfile.ZipFile(path) as zf:
        tsv_names = [n for n in zf.namelist() if n.endswith("/data.tsv")]
        if not tsv_names:
            raise ValueError(f"data.tsv not found in {path}")
        text = zf.read(tsv_names[0]).decode("utf-8")

    rows = list(csv.reader(io.StringIO(text), delimiter="\t"))
    if not rows:
        return []
    header = rows[0]
    # First column has no name (sample index).
    header = [h or "sample" for h in header]
    out: list[dict[str, str]] = []
    for raw in rows[1:]:
        if not raw or not raw[0]:
            continue
        out.append(dict(zip(header, raw)))
    return out


def _pick(row: dict[str, str], *names: str) -> str:
    for name in names:
        if name in row and row[name]:
            return row[name]
    return ""


def parse_results(
    outdir: Path,
    samples: list[str],
    genes: list[str] | None = None,
) -> dict[str, dict[str, dict[str, object]]]:
    """Return {barcode: {gene: {genotype, phenotype, callable}}}."""
    genes = genes or GENES
    wanted = set(genes)
    sample_set = set(samples)
    parsed: dict[str, dict[str, dict[str, object]]] = {
        barcode: {} for barcode in samples
    }

    for gene in genes:
        zip_path = outdir / f"{gene}.pipeline" / "results.zip"
        if not zip_path.exists():
            continue
        try:
            rows = _read_results_zip(zip_path)
        except Exception:  # noqa: BLE001 - a broken gene should not stop the run
            continue
        for row in rows:
            raw_sample = _pick(row, "sample", "Sample", "Unnamed: 0")
            sample = raw_sample.removesuffix("_PyPGx")
            if sample not in sample_set:
                continue
            genotype = _pick(row, "Genotype")
            phenotype = _pick(row, "Phenotype")
            callable_ = bool(genotype) and genotype not in {"Indeterminate", "No call"}
            parsed[sample][gene] = {
                "genotype": genotype or "No call",
                "phenotype": phenotype or "Indeterminate",
                "callable": callable_,
            }

    for barcode, genes_map in parsed.items():
        for gene in wanted:
            genes_map.setdefault(
                gene,
                {"genotype": "No call", "phenotype": "Indeterminate", "callable": False},
            )
    return parsed
