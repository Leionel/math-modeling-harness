"""Teaching Q2: enumerate the integer minimum of (x - 3)^2 on [0, 8]."""

import json
from pathlib import Path

values = [(x, (x - 3) ** 2) for x in range(9)]
x, value = min(values, key=lambda pair: pair[1])
Path("raw_results.json").write_text(
    json.dumps(
        {
            "results": [
                {
                    "result_id": "R-Q2",
                    "question_id": "q2",
                    "name": "minimum_score",
                    "value": value,
                    "unit": "1",
                    "precision": 0,
                    "statistical_definition": "minimum quadratic score on integer domain 0..8",
                    "boundary": "teaching example only: x is an integer in 0..8",
                    "validation_status": "passed"
                    if x == 3 and value == 0
                    else "failed",
                }
            ],
            "solution": {"x": x, "score": value},
        },
        indent=2,
    ),
    encoding="utf-8",
)
print(f"enumerated {len(values)} candidates; x={x}, score={value}")
