from __future__ import annotations

import zipfile

from pharmcow.star.parse import parse_results


def test_parse_results_reads_zip(tmp_path):
    gene_dir = tmp_path / "CYP2C19.pipeline"
    gene_dir.mkdir()
    with zipfile.ZipFile(gene_dir / "results.zip", "w") as zf:
        zf.writestr(
            "tmp123/data.tsv",
            "\tGenotype\tPhenotype\tHaplotype1\tHaplotype2\n"
            "S1\t*2/*3\tPoor Metabolizer\t*2\t*3\n",
        )

    out = parse_results(tmp_path, ["S1"], genes=["CYP2C19"])

    assert out["S1"]["CYP2C19"]["genotype"] == "*2/*3"
    assert out["S1"]["CYP2C19"]["phenotype"] == "Poor Metabolizer"
    assert out["S1"]["CYP2C19"]["callable"] is True


def test_parse_results_marks_missing_gene_as_not_callable(tmp_path):
    out = parse_results(tmp_path, ["S1"], genes=["CYP2D6"])

    assert out["S1"]["CYP2D6"]["genotype"] == "No call"
    assert out["S1"]["CYP2D6"]["callable"] is False
