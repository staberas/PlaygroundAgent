#!/usr/bin/env python3
"""Rewrite Unsplash image URLs in a CSV using keywords from existing URLs."""

from __future__ import annotations

import argparse
import csv
import json
import os
import random
import sys
from typing import Optional
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qs, unquote, urlencode, urlparse
from urllib.request import Request, urlopen

DEFAULT_ACCESS_KEY = "81ZMhK1x3PZp6ORQZipFA-zrOScdv5C73Vc2HGU5b84"
DEFAULT_SECRET = "gjEo0ik96RGP1IzZN5MWLluw4AsPM_JomvZBTFFVmkw"
DEFAULT_APP_ID = "931205"
UNSPLASH_SEARCH_URL = "https://api.unsplash.com/search/photos"


def extract_keywords(image_value: str) -> Optional[str]:
    if not image_value:
        return None

    parsed = urlparse(image_value)
    raw_query = parsed.query.strip()
    if not raw_query:
        return None

    if "=" not in raw_query:
        cleaned = unquote(raw_query).replace(",", " ").replace("+", " ").strip()
        return " ".join(cleaned.split()) if cleaned else None

    params = parse_qs(raw_query, keep_blank_values=False)

    preferred_keys = ["query", "q", "keywords", "term"]
    for key in preferred_keys:
        values = params.get(key)
        if values:
            cleaned = " ".join(values).replace(",", " ").replace("+", " ").strip()
            normalized = " ".join(cleaned.split())
            if normalized:
                return normalized

    all_values = " ".join(v for values in params.values() for v in values)
    normalized = " ".join(all_values.replace(",", " ").replace("+", " ").split())
    return normalized or None


def search_unsplash_photo(query: str, access_key: str, timeout: int = 20) -> Optional[dict]:
    # Pull a batch and pick one result randomly so repeated runs are less repetitive.
    params = {
        "query": query,
        "page": random.randint(1, 5),
        "per_page": 30,
        "orientation": "landscape",
    }
    url = f"{UNSPLASH_SEARCH_URL}?{urlencode(params)}"

    req = Request(
        url,
        headers={
            "Accept-Version": "v1",
            "Authorization": f"Client-ID {access_key}",
        },
        method="GET",
    )

    with urlopen(req, timeout=timeout) as resp:
        payload = resp.read()

    data = json.loads(payload)
    results = data.get("results") or []
    if not results:
        return None
    return random.choice(results)


def build_sized_image_url(photo: dict, width: int = 800, height: int = 600) -> Optional[str]:
    urls = photo.get("urls") or {}
    raw_url = urls.get("raw")
    if not raw_url:
        return None

    params = {
        "w": width,
        "h": height,
        "fit": "max",
        "auto": "format",
    }
    return f"{raw_url}&{urlencode(params)}"


def process_csv(
    input_csv: str,
    output_csv: str,
    access_key: str,
    image_column: str,
) -> tuple[int, int, int]:
    with open(input_csv, "r", newline="", encoding="utf-8") as infile:
        reader = csv.DictReader(infile)
        if reader.fieldnames is None:
            raise ValueError("Input CSV has no header row.")
        if image_column not in reader.fieldnames:
            raise ValueError(
                f"Column '{image_column}' not found. Available columns: {reader.fieldnames}"
            )

        rows = list(reader)
        fieldnames = reader.fieldnames

    total_rows = len(rows)
    updated_rows = 0
    skipped_rows = 0

    for idx, row in enumerate(rows, start=1):
        # Some CSVs may contain unquoted commas inside URL values.
        # csv.DictReader stores overflow columns under key None.
        extras = row.pop(None, None)
        if extras and image_column in row:
            base = row.get(image_column) or ""
            row[image_column] = ",".join([base, *extras]).strip(",")

        original = (row.get(image_column) or "").strip()
        if not original:
            skipped_rows += 1
            print(f"[row {idx}] Skipped: empty '{image_column}' value")
            continue

        keywords = extract_keywords(original)
        if not keywords:
            skipped_rows += 1
            print(f"[row {idx}] Skipped: no keywords parsed from URL query")
            continue

        try:
            photo = search_unsplash_photo(query=keywords, access_key=access_key)
        except (HTTPError, URLError, TimeoutError, json.JSONDecodeError) as exc:
            skipped_rows += 1
            print(f"[row {idx}] Skipped: API error for '{keywords}': {exc}")
            continue

        if not photo:
            skipped_rows += 1
            print(f"[row {idx}] Skipped: no results for '{keywords}'")
            continue

        new_url = build_sized_image_url(photo, width=800, height=600)
        if not new_url:
            skipped_rows += 1
            print(f"[row {idx}] Skipped: result missing raw image URL")
            continue

        row[image_column] = new_url
        updated_rows += 1
        print(f"[row {idx}] Updated '{keywords}'")

    with open(output_csv, "w", newline="", encoding="utf-8") as outfile:
        writer = csv.DictWriter(outfile, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)

    return total_rows, updated_rows, skipped_rows


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Read CSV rows, extract keywords from the 'Image' URL query, "
            "search Unsplash, and replace with a new 800x600 image URL."
        )
    )
    parser.add_argument("input_csv", help="Path to input CSV")
    parser.add_argument("output_csv", help="Path to output CSV")
    parser.add_argument(
        "--image-column",
        default="Image",
        help="Column name that holds old Unsplash URLs (default: Image)",
    )
    parser.add_argument(
        "--access-key",
        default=os.getenv("UNSPLASH_ACCESS_KEY", DEFAULT_ACCESS_KEY),
        help="Unsplash Access Key (default: env UNSPLASH_ACCESS_KEY or provided key)",
    )
    parser.add_argument(
        "--secret",
        default=os.getenv("UNSPLASH_SECRET", DEFAULT_SECRET),
        help="Unsplash Secret (not required for this script, kept for completeness)",
    )
    parser.add_argument(
        "--app-id",
        default=os.getenv("UNSPLASH_APP_ID", DEFAULT_APP_ID),
        help="Unsplash App ID (not required for this script, kept for completeness)",
    )
    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()

    if not args.access_key:
        print("Error: access key is required.", file=sys.stderr)
        return 2

    _ = args.secret
    _ = args.app_id

    try:
        total, updated, skipped = process_csv(
            input_csv=args.input_csv,
            output_csv=args.output_csv,
            access_key=args.access_key,
            image_column=args.image_column,
        )
    except Exception as exc:
        print(f"Failed: {exc}", file=sys.stderr)
        return 1

    print("\nDone")
    print(f"Total rows:   {total}")
    print(f"Updated rows: {updated}")
    print(f"Skipped rows: {skipped}")
    print(f"Output file:  {args.output_csv}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
