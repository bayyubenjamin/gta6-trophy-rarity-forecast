"""Entrypoint: turn every case file in the input directory into a forecast.

The grader runs `python3 -P -s /bot/main.py` with the repository
read-only at /bot and one case file in /input, expecting <id>.out in
/output. -P keeps this file's own directory off sys.path, so the first
thing here is to put it back, which is what lets `import model` find
the model module shipped beside this file.

Outside the grader, the same run is:

    mkdir -p out && MAKEFUN_INPUT_DIR=input MAKEFUN_OUTPUT_DIR=out python3 main.py

Each input file is JSON in the makefun/gta6-trophies-case/v1 schema:
55 trophies and a history of Exophase reads. Each output file is one
compact JSON object, {"trophies": [{"id": n, "q": [q05, q25, q50, q75,
q95]}, ...]}, one row per trophy in the case's order, each id exactly
once, no other keys, and a trailing newline. The work of forecasting
lives in model.py; this file only moves bytes in and out.

Determinism: input files are handled in sorted name order, the output
order follows the case's trophy order, and nothing here reads the
clock, the environment beyond the two directories, or any random
source, so two runs on the same input write identical bytes.
"""

import json
import os
import sys
from pathlib import Path

# -P leaves this file's directory off sys.path; restore it first so the
# model module beside this file can be imported. Do not write bytecode
# next to the sources either: the grader's repository is read-only, and
# a stray __pycache__ does not belong in the entry.
sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parent))

import model

INPUT_DIR = Path(os.environ.get("MAKEFUN_INPUT_DIR", "/input"))
OUTPUT_DIR = Path(os.environ.get("MAKEFUN_OUTPUT_DIR", "/output"))


def run() -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    for case_path in sorted(INPUT_DIR.glob("*.in")):
        try:
            with open(case_path, encoding="utf-8") as handle:
                case = json.load(handle)
            forecast = model.forecast_all_trophies(case)
        except Exception as exc:  # one bad case must not sink the rest
            print(f"skipping {case_path.name}: {exc}", file=sys.stderr)
            continue
        text = json.dumps(forecast, separators=(",", ":")) + "\n"
        out_path = OUTPUT_DIR / (case_path.stem + ".out")
        with open(out_path, "w", encoding="utf-8") as handle:
            handle.write(text)


if __name__ == "__main__":
    run()
