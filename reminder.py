#!/usr/bin/env python3
"""Export an Apple Reminders list with the rem command."""

import argparse
import json
from pathlib import Path
import shutil
import subprocess
from output_safety import validate_clear_directory


def export_reminders(output, list_name, all_reminders=False, force=False):
    # command = ["rem", "export", "--list", list_name, "--format", "json"]
    # if not all_reminders:
    #     command.append("--incomplete")
    # try:
    #     result = subprocess.run(command, capture_output=True, text=True)
    # except FileNotFoundError as error:
    #     raise RuntimeError("The rem command is required to export Apple Reminders") from error
    # if result.returncode:
    #     raise RuntimeError(
    #         f"rem export failed ({result.returncode}): {result.stderr.strip()}"
    #     )
    # reminders = json.loads(result.stdout)
    # if not isinstance(reminders, list) or not all(isinstance(item, dict) for item in reminders):
    #     raise ValueError("rem did not return a JSON array of reminders")

    directory = Path(output)
    if force:
        validate_clear_directory(directory)
    if force and directory.exists():
        if not directory.is_dir():
            raise ValueError(f"Output is not a directory: {directory}")
        shutil.rmtree(directory)
    directory.mkdir(parents=True, exist_ok=True)
    # destination = directory / "reminders.json"
    # with destination.open("w", encoding="utf-8") as handle:
    #     json.dump(reminders, handle, ensure_ascii=False, indent=2)
    #     handle.write("\n")
    # print(f"Exported {len(reminders)} reminder(s) to {destination}")

    print(f'command to run in terminal: rem export --list "{list_name}" --format json --incomplete > "{directory}/reminders.json"')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True, help="Output directory")
    parser.add_argument("--list", required=True, dest="list_name", help="Reminders list name")
    parser.add_argument("--all", action="store_true", help="Include completed reminders")
    parser.add_argument("--force", action="store_true", help="Delete the output directory first")
    args = parser.parse_args()
    export_reminders(args.output, args.list_name, args.all, args.force)


if __name__ == "__main__":
    main()
