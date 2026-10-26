from __future__ import annotations

from pharmcow.report.render import build_report_data, render_report


def test_render_report_writes_html(tmp_path):
    data = build_report_data(
        run_id="r1",
        barcode="S1",
        filename="sample.vcf.gz",
        assembly="GRCh38",
        star={
            "CYP2C19": {
                "genotype": "*2/*3",
                "phenotype": "Poor Metabolizer",
                "callable": True,
            }
        },
        recs=[
            {
                "drug": "clopidogrel",
                "genes": [{"gene": "CYP2C19", "phenotype": "Poor Metabolizer"}],
                "recommendation": "Use an alternative antiplatelet.",
                "cpic_level": "A",
                "cpic_status": "Final",
                "guideline": "https://cpicpgx.org/",
            }
        ],
    )

    html_path, pdf_path = render_report(data, tmp_path, make_pdf=False)

    text = html_path.read_text(encoding="utf-8")
    assert "S1" in text
    assert "clopidogrel" in text
    assert "Not for clinical use" in text
    assert "Gene results" in text
    assert "Drug recommendations" in text
    assert "CPIC level A" in text
    assert data["summary"]["genes_called"] == 1
    assert pdf_path is None
