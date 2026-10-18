"""Finite DAG admission plus persisted winning-control execution of the hand-defined two-audit episode, exact deadlines and declared bounded failures."""

import argparse
import json
from pathlib import Path
import subprocess
import sys


ROOT = Path(__file__).resolve().parent


def build_steps(args):
    output = (ROOT / args.output).resolve()
    return [
        ["-m", "obligationshield", "prepare", "--count", "200", "--seed", "17", "--output", str(output / "workload.jsonl")],
        ["-m", "obligationshield", "suite", "--data", str(output / "workload.jsonl"), "--output", str(output / "admission")],
        ["-m", "obligationshield.runtime", "--case", "examples/two_audits.json", "--ledger", str(output / "ledger.sqlite"), "--executor", "finite", "--effects", str(output / "effects.sqlite"), "--bucket", "1", "--output", str(output / "execution.json")],
    ]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", default='runs/fixed-setting')
    parser.add_argument("--plan", action="store_true", help="Print commands without creating data, fitting, inference or evaluation")

    args = parser.parse_args()
    output = (ROOT / args.output).resolve()
    if not args.plan and output.exists():
        parser.error("Choose a fresh --output directory")
    for step in build_steps(args):
        command = [sys.executable, *step]
        if args.plan:
            print(json.dumps(command))
        else:
            subprocess.run(command, cwd=ROOT, check=True)


if __name__ == "__main__":
    main()
