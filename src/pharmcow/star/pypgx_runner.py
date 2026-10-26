from __future__ import annotations

import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path

from pharmcow.star.genes import GENES
from pharmcow.star.qc import QcError


@dataclass
class GeneRun:
    gene: str
    ok: bool
    returncode: int
    log: str


@dataclass
class StarRun:
    outdir: Path
    results: list[GeneRun]

    @property
    def failed(self) -> list[GeneRun]:
        return [r for r in self.results if not r.ok]


def _pypgx_available() -> bool:
    try:
        import pypgx  # noqa: F401
    except Exception:  # noqa: BLE001
        return False
    return True


def _run_gene(gene: str, vcf: Path, outdir: Path, assembly: str) -> GeneRun:
    gene_out = outdir / f"{gene}.pipeline"
    log_path = outdir / f"{gene}.log"
    cmd = [
        sys.executable,
        "-m",
        "pypgx",
        "run-chip-pipeline",
        gene,
        str(gene_out),
        str(vcf),
        "--assembly",
        assembly,
        "--force",
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=1800)
    log_path.write_text(
        f"$ {' '.join(cmd)}\n\n[stdout]\n{proc.stdout}\n[stderr]\n{proc.stderr}\n"
    )
    return GeneRun(
        gene=gene,
        ok=proc.returncode == 0 and (gene_out / "results.zip").exists(),
        returncode=proc.returncode,
        log=str(log_path),
    )


def run_star(
    vcf: Path,
    outdir: Path,
    assembly: str,
    threads: int = 4,
    genes: list[str] | None = None,
) -> StarRun:
    if not _pypgx_available():
        raise QcError(
            "pypgx is not installed. Install the star extra: `uv sync --extra star`."
        )

    genes = genes or GENES
    outdir.mkdir(parents=True, exist_ok=True)
    workers = max(1, min(threads, len(genes)))

    with ThreadPoolExecutor(max_workers=workers) as pool:
        results = list(
            pool.map(lambda g: _run_gene(g, vcf, outdir, assembly), genes)
        )

    return StarRun(outdir=outdir, results=results)
