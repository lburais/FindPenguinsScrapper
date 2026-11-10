#!/usr/bin/env python3
"""Generate one Pelican RST article per exported reminder."""

import argparse
import hashlib
import json
from pathlib import Path


def _metadata(value):
    return " ".join(str(value).split())


def convert(output, content):
    source = Path(output) / "reminders.json"
    with source.open(encoding="utf-8") as handle:
        reminders = json.load(handle)
    if not isinstance(reminders, list):
        raise ValueError(f"Expected an array of reminders in {source}")
    seen = set()
    articles = []
    for reminder in reminders:
        if not isinstance(reminder, dict):
            raise ValueError("Each reminder must be an object")
        identifier = reminder.get("id")
        name = reminder.get("name")
        if not isinstance(identifier, str) or not identifier or not isinstance(name, str) or not name.strip():
            raise ValueError("Every reminder must have a nonempty id and name")
        if identifier in seen:
            raise ValueError(f"Duplicate reminder id: {identifier}")
        seen.add(identifier)
        slug = "reminder-" + hashlib.sha256(identifier.encode("utf-8")).hexdigest()
        fields = [
            ("Title", name),
            ("Slug", slug),
            ("Category", "reminder"),
            ("Template", "article"),
            ("Date", reminder.get("creation_date") or reminder.get("due_date") or reminder.get("completion_date")),
            ("List", reminder.get("list_name")),
            ("Reminder-status", "completed" if reminder.get("completed") else "incomplete"),
            ("Due", reminder.get("due_date")),
            ("Priority", reminder.get("priority_label")),
            ("Tags", ", ".join(reminder.get("tags") or [])),
            ("Link", reminder.get("url")),
        ]
        text = "\n".join(f":{key}: {_metadata(value)}" for key, value in fields if value)
        body = reminder.get("body")
        if body:
            if not isinstance(body, str):
                raise ValueError(f"Reminder {identifier} has a non-string body")
            text += "\n\n::\n\n" + "\n".join("    " + line for line in body.splitlines())
        articles.append((slug, text + "\n"))
    destination = Path(content)
    destination.mkdir(parents=True, exist_ok=True)
    for slug, text in articles:
        (destination / f"{slug}.rst").write_text(text, encoding="utf-8")
    print(f"Generated {len(articles)} reminder article(s) in {destination}")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True, help="Reminder export directory")
    parser.add_argument("--content", default="../website/content/articles/reminders",
                        help="Pelican articles directory")
    args = parser.parse_args()
    convert(args.output, args.content)


if __name__ == "__main__":
    main()
