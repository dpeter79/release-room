#!/usr/bin/env python3
"""Stands in for the sales program named by SALES_PROBE (docs/setup.md). All numbers are invented, and the same for a given day on every run."""
import json
import random
import sys

day = sys.argv[3]
rng = random.Random(day)
downloads, pro = rng.randint(2, 14), rng.choice([0, 0, 0, 1, 1, 2])
proceeds = f"{pro * 8.4:.2f}"
print(json.dumps({"status": "report", "day": day, "currency": "EUR", "total": proceeds, "unconverted": {}, "refundedUnits": 0,
                  "provenance": "invented demo data",
                  "products": [{"title": "DemoCam: Virtual Camera", "units": downloads, "proceeds": "0"},
                               {"title": "DemoCam Pro", "units": pro, "proceeds": proceeds}]}))
