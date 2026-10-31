#!/usr/bin/env python3
"""a stand-in for dead software: reads a batch file, writes a report.

the point is not the program. the point is that the fixture proves the whole
path - input seeded, app run in the guest, output harvested, expectation met -
so replacing this stub with the real binary is the only change needed.
"""
import pathlib
import sys

src = pathlib.Path(sys.argv[1])
out = pathlib.Path(sys.argv[2])
lines = [ln.strip() for ln in src.read_text().splitlines() if ln.strip()]
report = "\n".join(f"{i}. {ln}" for i, ln in enumerate(lines, start=1))
out.write_text(report + "\n")
print(f"wrote {len(lines)} rows")
