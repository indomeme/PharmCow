from __future__ import annotations

import shutil
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

import pysam


class QcError(Exception):
    """Raised when the VCF cannot be processed."""


@dataclass
class QcResult:
    path: Path
    assembly: str
    samples: list[str]
    phased: bool
    missing: bool
    method: str
    notes: list[str] = field(default_factory=list)


_ASSEMBLY_BY_CHR1 = {
    248956422: "GRCh38",
    249250621: "GRCh37",
}


def detect_assembly(contigs: dict[str, int], hint: str = "auto", header_text: str = "") -> str:
    if hint and hint.upper() in {"GRCH37", "GRCH38"}:
        return hint.upper().replace("GRCH", "GRCh")
    length = contigs.get("chr1") or contigs.get("1")
    if length in _ASSEMBLY_BY_CHR1:
        return _ASSEMBLY_BY_CHR1[length]
    # Fall back to chr2 length as a second signal.
    length2 = contigs.get("chr2") or contigs.get("2")
    if length2 == 242193529:
        return "GRCh38"
    if length2 == 243199373:
        return "GRCh37"
    # Chip VCFs often omit contig lengths; use the header text instead.
    low = header_text.lower()
    if "grch38" in low or "hg38" in low or "ncbi38" in low or "genome-version-ncbi(38)" in low:
        return "GRCh38"
    if "grch37" in low or "hg19" in low or "b37" in low or "genome-version-ncbi(37)" in low:
        return "GRCh37"
    raise QcError(
        "Cannot detect assembly from the VCF header; choose GRCh37 or GRCh38."
    )


def ensure_index(vcf: Path) -> Path:
    for suffix in (".tbi", ".csi"):
        idx = Path(str(vcf) + suffix)
        if idx.exists():
            return idx
    try:
        pysam.tabix_index(str(vcf), preset="vcf", force=True)
    except Exception as exc:  # noqa: BLE001 - report actionable message
        raise QcError(
            "VCF is not bgzipped/indexed. Re-upload a bgzipped VCF or its .tbi index."
        ) from exc
    for suffix in (".tbi", ".csi"):
        idx = Path(str(vcf) + suffix)
        if idx.exists():
            return idx
    raise QcError("Failed to create a tabix index for the VCF.")


def _check_with_bcftools(vcf: Path) -> tuple[bool, bool]:
    """Return (phased, missing). Streams GT per sample; stops at first violation."""
    proc = subprocess.Popen(
        # Square brackets are required for per-sample FORMAT fields; plain %GT
        # is interpreted as INFO/GT and makes bcftools fail on multi-sample VCFs.
        ["bcftools", "query", "-f", "[%GT\n]", str(vcf)],
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        text=True,
    )
    assert proc.stdout is not None
    phased = True
    missing = False
    seen = 0
    try:
        for line in proc.stdout:
            gt = line.strip()
            if not gt:
                continue
            seen += 1
            if gt in {".", "./.", ".|."} or "." in gt:
                missing = True
            if "/" in gt:
                phased = False
            if missing or not phased:
                proc.kill()
                break
    finally:
        returncode = proc.wait(timeout=10)
    if seen == 0 and returncode not in (0, -9):
        raise QcError("bcftools failed to read the VCF; check that it is valid/indexed.")
    return phased, missing


def _check_with_pysam(vcf: Path, limit: int = 2000) -> tuple[bool, bool]:
    phased = True
    missing = False
    with pysam.VariantFile(str(vcf)) as vf:
        for i, rec in enumerate(vf):
            if i >= limit:
                break
            for sample in rec.samples.values():
                alleles = sample.get("GT")
                if alleles is None or any(a is None for a in alleles):
                    missing = True
                if not sample.phased:
                    phased = False
            if missing or not phased:
                break
    return phased, missing


def qc_vcf(vcf: Path, assembly_hint: str = "auto") -> QcResult:
    if not vcf.exists():
        raise QcError(f"VCF not found: {vcf}")
    ensure_index(vcf)

    with pysam.VariantFile(str(vcf)) as vf:
        header = vf.header
        samples = list(header.samples)
        contigs = {
            name: rec.length for name, rec in header.contigs.items() if rec.length
        }
        header_text = str(header)
    if not samples:
        raise QcError("VCF has no samples.")
    if len(samples) > 96:
        raise QcError("Too many samples in one VCF (max 96).")

    assembly = detect_assembly(contigs, assembly_hint, header_text)

    notes: list[str] = []
    if shutil.which("bcftools"):
        phased, missing = _check_with_bcftools(vcf)
        method = "bcftools"
    else:
        phased, missing = _check_with_pysam(vcf)
        method = "pysam (first 2000 records)"
        notes.append("bcftools not found; phase/missing check is sampled, not exhaustive.")

    if missing:
        raise QcError(
            "VCF contains missing genotypes. Filter/re-impute the VCF so every "
            "genotype is called before uploading."
        )
    if not phased:
        raise QcError(
            "VCF is not fully phased. This build has no Beagle/Java; "
            "phase the VCF before uploading (imputed VCFs are usually phased)."
        )

    return QcResult(
        path=vcf,
        assembly=assembly,
        samples=samples,
        phased=phased,
        missing=missing,
        method=method,
        notes=notes,
    )
