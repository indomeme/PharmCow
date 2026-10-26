from __future__ import annotations

from typing import Any


def _text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, float) and value != value:  # NaN
        return ""
    return str(value).strip()


def _norm(value: str) -> str:
    return " ".join(value.lower().split())


def _cpic_index(rows: list[dict[str, Any]]) -> dict[tuple[str, str], dict[str, str]]:
    index: dict[tuple[str, str], dict[str, str]] = {}
    for row in rows:
        drug = _norm(_text(row.get("Drug")))
        gene = _text(row.get("Gene")).upper()
        if not drug or not gene:
            continue
        index.setdefault(
            (drug, gene),
            {
                "level": _text(row.get("CPICLevel")),
                "status": _text(row.get("CPICLevelStatus")),
                "guideline": _text(row.get("Guideline")),
                "pharmgkb": _text(row.get("PharmGKBLevel")),
            },
        )
    return index


def build_recommendations(
    star_by_sample: dict[str, dict[str, dict[str, Any]]],
) -> dict[str, list[dict[str, Any]]]:
    """Map pypgx phenotype calls to public CPIC recommendations."""
    import pypgx

    rec_rows = pypgx.load_recommendation_table().to_dict("records")
    cpic_rows = pypgx.load_cpic_table().to_dict("records")
    cpic = _cpic_index(cpic_rows)

    result: dict[str, list[dict[str, Any]]] = {}
    for barcode, genes in star_by_sample.items():
        seen: set[tuple[str, str, str, str, str]] = set()
        found: list[dict[str, Any]] = []

        for row in rec_rows:
            drug = _text(row.get("Drug"))
            gene1 = _text(row.get("Gene1")).upper()
            pheno1 = _text(row.get("Phenotype1"))
            gene2 = _text(row.get("Gene2"))
            pheno2 = _text(row.get("Phenotype2"))
            if not drug or gene1 not in genes:
                continue

            call1 = genes[gene1]
            actual1 = _text(call1.get("phenotype"))
            if not call1.get("callable") or not actual1 or actual1 == "Indeterminate":
                continue
            if _norm(actual1) != _norm(pheno1):
                continue

            actual2 = ""
            if gene2 and gene2 != "None":
                if gene2 not in genes:
                    continue
                call2 = genes[gene2]
                actual2 = _text(call2.get("phenotype"))
                if not call2.get("callable") or not actual2 or actual2 == "Indeterminate":
                    continue
                if _norm(actual2) != _norm(pheno2):
                    continue

            key = (drug.lower(), gene1, _norm(actual1), gene2, _norm(actual2))
            if key in seen:
                continue
            seen.add(key)

            recommendation = _text(row.get("Recommendation"))
            try:
                if gene2 and gene2 != "None":
                    recommendation = pypgx.get_recommendation(
                        drug, gene1, actual1, gene2, actual2
                    )
                else:
                    recommendation = pypgx.get_recommendation(drug, gene1, actual1)
            except Exception:  # noqa: BLE001 - fall back to the table row
                pass

            meta = cpic.get((drug.lower(), gene1), {})
            pairs = [{"gene": gene1, "phenotype": actual1}]
            if actual2:
                pairs.append({"gene": gene2, "phenotype": actual2})
            found.append(
                {
                    "drug": drug,
                    "genes": pairs,
                    "recommendation": recommendation,
                    "cpic_level": meta.get("level", ""),
                    "cpic_status": meta.get("status", ""),
                    "guideline": meta.get("guideline", ""),
                }
            )

        found.sort(key=lambda x: (x["drug"].lower(), x["genes"][0]["gene"]))
        result[barcode] = found

    return result
