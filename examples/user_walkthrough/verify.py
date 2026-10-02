"""Independent analytic check: nonnegative square, zero only at x=3."""

import json
import sys
from pathlib import Path

run_id = sys.argv[1]
result = json.loads(Path("raw_results.json").read_text(encoding="utf-8"))
solution = result["solution"]
error = max(
    abs(solution["x"] - 3),
    abs(solution["score"]),
    abs(result["results"][0]["value"] - solution["score"]),
)
Path("measurements.json").write_text(
    json.dumps(
        {
            "schema_version": "1.0",
            "run_id": run_id,
            "observations": [
                {
                    "obligation_id": "VAL-Q2",
                    "metrics": [
                        {
                            "metric_id": "analytic_error",
                            "value": error,
                            "unit": "1",
                            "locator": "verify.py: independent nonnegative-square minimum and reported value",
                        }
                    ],
                }
            ],
        },
        indent=2,
    ),
    encoding="utf-8",
)
print(f"independent analytic discrepancy={error}")
raise SystemExit(0 if error == 0 else 1)
