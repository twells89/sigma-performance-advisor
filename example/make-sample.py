#!/usr/bin/env python3
"""Emit a synthetic sample-rows.json (fictional 'Northwind Trading Co.' — no real data)
shaped exactly like the output of sql/sigma_cost.sql. Render the example with:

    python3 example/make-sample.py
    python3 scripts/analyze.py --from-rows example/sample-rows.json --credit-price 3 \\
        --goal both --out example
    python3 scripts/render-html.py --inv example/inventory.json \\
        --out example/sample-report.html --customer "Northwind Trading Co. (sample)"
"""
import json, os
HERE = os.path.dirname(__file__)
U = "https://app.sigmacomputing.com/northwind"


def row(obj, el, runs, credits, avg, mx, mb, url):
    return {"ORG": "northwind", "OBJECT": obj, "ELEMENT": el, "RUNS": runs,
            "CREDITS": credits, "AVG_SEC": avg, "MAX_SEC": mx,
            "TOTAL_SEC": round(avg * runs, 1), "MAX_BYTES": mb, "SAMPLE_URL": url}


rows = [
    # clear materialize — data model, heavy cumulative cost, repetitive
    row("/data-model/Sales-Mart-DM-aaa111", "(workbook load)", 240, 18.4, 2.1, 6.0,
        4_000_000_000, f"{U}/data-model/Sales-Mart-DM-aaa111"),
    # materialize — workbook element, slow + frequent
    row("/workbook/Exec-Revenue-Daily-bbb222", "master", 132, 9.6, 4.8, 9.1,
        2_500_000_000, f"{U}/workbook/Exec-Revenue-Daily-bbb222?:displayNodeId=master"),
    # materialize — frequent + cumulative cost even if fast per run
    row("/workbook/Ops-Live-Tiles-ccc333", "kpi-row", 410, 5.2, 0.7, 1.9,
        300_000_000, f"{U}/workbook/Ops-Live-Tiles-ccc333?:displayNodeId=kpi-row"),
    # improve — very slow + huge scan but infrequent (don't cache; fix the model)
    row("/workbook/Adhoc-Cohort-Explorer-ddd444", "cohort-tbl", 5, 1.1, 14.7, 22.0,
        9_500_000_000, f"{U}/workbook/Adhoc-Cohort-Explorer-ddd444?:displayNodeId=cohort-tbl"),
    # improve — large scan, low frequency
    row("/data-model/Web-Events-DM-eee555", "(workbook load)", 7, 0.9, 8.2, 12.4,
        6_200_000_000, f"{U}/data-model/Web-Events-DM-eee555"),
    # monitor — cheap & fast
    row("/workbook/Marketing-Overview-fff666", "chart-1", 64, 0.18, 0.4, 0.9,
        40_000_000, f"{U}/workbook/Marketing-Overview-fff666?:displayNodeId=chart-1"),
    row("/workbook/HR-Headcount-ggg777", "table-main", 22, 0.09, 0.3, 0.7,
        12_000_000, f"{U}/workbook/HR-Headcount-ggg777?:displayNodeId=table-main"),
    row("/workbook/Finance-Snapshot-hhh888", "master", 9, 0.21, 1.1, 2.0,
        80_000_000, f"{U}/workbook/Finance-Snapshot-hhh888?:displayNodeId=master"),
]
out = os.path.join(HERE, "sample-rows.json")
json.dump(rows, open(out, "w"), indent=2)
print("wrote", out, f"({len(rows)} rows)")
