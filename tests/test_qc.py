from __future__ import annotations

import pysam
import pytest

from pharmcow.star.qc import QcError, qc_vcf

HEADER = """##fileformat=VCFv4.2
##contig=<ID=chr1,length=248956422>
##FORMAT=<ID=GT,Number=1,Type=String,Description="Genotype">
#CHROM\tPOS\tID\tREF\tALT\tQUAL\tFILTER\tINFO\tFORMAT\tS1
"""


def _write_vcf(tmp_path, gt: str):
    txt = tmp_path / "in.vcf"
    txt.write_text(HEADER + f"chr1\t100\t.\tA\tG\t.\tPASS\t.\tGT\t{gt}\n")
    gz = tmp_path / "in.vcf.gz"
    pysam.tabix_compress(str(txt), str(gz), force=True)
    pysam.tabix_index(str(gz), preset="vcf", force=True)
    return gz


def test_qc_accepts_phased_complete_vcf(tmp_path):
    vcf = _write_vcf(tmp_path, "0|1")
    qc = qc_vcf(vcf, "auto")
    assert qc.assembly == "GRCh38"
    assert qc.phased is True
    assert qc.missing is False


def test_qc_rejects_missing_genotype(tmp_path):
    vcf = _write_vcf(tmp_path, "./.")
    with pytest.raises(QcError, match="missing genotypes"):
        qc_vcf(vcf, "auto")


def test_qc_rejects_unphased_genotype(tmp_path):
    vcf = _write_vcf(tmp_path, "0/1")
    with pytest.raises(QcError, match="not fully phased"):
        qc_vcf(vcf, "auto")
