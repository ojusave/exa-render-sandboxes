"""Trusted invocation wrapper. The host sends this program only to Render."""

# Each process receives one JSON case on standard input. It imports only the candidate
# module in /workspace, calls one function, and serializes a real Polars result.
import json
import runpy
import sys

case = json.load(sys.stdin)
try:
    module = runpy.run_path("/workspace/solution.py")
    if case["op"] == "align":
        table = module["align_metrics"](case["days"], case["counts"])
        result = {"rows": table.to_dicts(), "schema": [str(t) for t in table.dtypes]}
    elif case["op"] == "categories":
        series = module["decode_categories"](case["codes"], case["labels"])
        result = {"values": series.to_list(), "dtype": str(series.dtype)}
    elif case["op"] == "dates":
        series = module["parse_dates"](case["values"])
        result = {"values": series.to_list(), "dtype": str(series.dtype)}
    else:
        raise ValueError("Unknown fixture operation")
    # Dates become ISO strings, such as 2026-10-13. Other types must serialize normally.
    print(json.dumps({"result": result}, default=lambda value: value.isoformat()))
except Exception as exc:
    # A failing candidate is evidence for the model. No credentials exist in this process.
    print(json.dumps({"error": type(exc).__name__, "message": str(exc)[:2000]}))
