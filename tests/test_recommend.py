from __future__ import annotations

import pytest


def test_recommendations_from_public_pypgx_tables():
    pypgx = pytest.importorskip("pypgx")
    from pharmcow.recommend.engine import build_recommendations

    table = pypgx.load_recommendation_table()
    row = None
    for candidate in table.to_dict("records"):
        gene2 = str(candidate.get("Gene2") or "None")
        if gene2 == "None":
            row = candidate
            break
    assert row is not None

    gene = str(row["Gene1"])
    phenotype = str(row["Phenotype1"])
    star = {
        "S1": {
            gene: {
                "genotype": "*1/*1",
                "phenotype": phenotype,
                "callable": True,
            }
        }
    }

    recs = build_recommendations(star)

    assert any(r["drug"] == row["Drug"] for r in recs["S1"])
