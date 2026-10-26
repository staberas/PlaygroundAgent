"""CSV storage, merging and non-destructive classification."""
import csv
import json
import os
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent
COLUMNS = ["path", "filename", "extension", "ignore", "yolo", "nude", "nsfw", "ocr", "caption", "new_file_name", "other"]
EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp", ".bmp", ".gif", ".tiff", ".tif"}

def normalize_path(value):
    p = Path(value).expanduser()
    return (p if p.is_absolute() else ROOT / p).resolve()

def read_rows(filename):
    filename = Path(filename)
    if not filename.exists():
        return [], COLUMNS.copy()
    with filename.open("r", encoding="utf-8-sig", newline="") as stream:
        reader = csv.DictReader(stream)
        columns = list(dict.fromkeys(COLUMNS + (reader.fieldnames or [])))
        return list(reader), columns

def write_rows(filename, rows, columns=None):
    filename = Path(filename)
    filename.parent.mkdir(parents=True, exist_ok=True)
    columns = list(dict.fromkeys((columns or COLUMNS) + [k for row in rows for k in row]))
    fd, temp = tempfile.mkstemp(prefix=".imgscan-", suffix=".tmp", dir=filename.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="") as stream:
            writer = csv.DictWriter(stream, fieldnames=columns, extrasaction="ignore")
            writer.writeheader()
            writer.writerows(rows)
        os.replace(temp, filename)
    finally:
        if os.path.exists(temp):
            os.unlink(temp)

def should_skip(row, stage, force=False):
    if str(row.get("ignore", "")).strip().lower() in {"1", "true", "yes", "on"}:
        return True
    return not force and bool(str(row.get(stage, "")).strip())

def scan(folder, csv_path, recursive=False):
    folder = Path(folder).expanduser().resolve()
    if not folder.is_dir():
        raise NotADirectoryError(folder)
    old, columns = read_rows(csv_path)
    previous = {row.get("path"): row for row in old}
    images = folder.rglob("*") if recursive else folder.iterdir()
    rows = []
    for image in sorted(images):
        if image.is_file() and image.suffix.lower() in EXTENSIONS:
            key = str(image.resolve())
            row = previous.get(key, {})
            row.update(path=key, filename=image.name, extension=image.suffix.lower())
            rows.append(row)
    write_rows(csv_path, rows, columns)
    return len(rows)

def rules(csv_path):
    rows, _ = read_rows(csv_path)
    output = []
    for row in rows:
        nude = {}
        try:
            nude = json.loads(row.get("nude", "") or row.get("nudenet", "") or "{}")
        except (ValueError, TypeError):
            pass
        nsfw = {}
        try:
            nsfw = json.loads(row.get("nsfw", "") or "{}")
        except (ValueError, TypeError):
            pass
        has_analysis = bool(row.get("nude", "").strip() or row.get("nudenet", "").strip() or row.get("nsfw", "").strip())
        explicit = bool(nude.get("nude")) or any(d.get("class") in {"FEMALE_BREAST_EXPOSED","FEMALE_GENITALIA_EXPOSED","MALE_GENITALIA_EXPOSED","BUTTOCKS_EXPOSED","ANUS_EXPOSED"} for d in nude.get("detections", [])) or max(float(nsfw.get("porn", 0)), float(nsfw.get("hentai", 0))) >= .65
        suggestive = bool(nude.get("sexy")) or any(d.get("class") in {"FEMALE_BREAST_COVERED","FEMALE_GENITALIA_COVERED","BUTTOCKS_COVERED"} for d in nude.get("detections", [])) or float(nsfw.get("sexy", 0)) >= .60
        output.append({"path": row.get("path", ""), "review": "explicit" if explicit else "suggestive" if suggestive else "unclassified" if not has_analysis else "not_flagged", "caption": row.get("caption", "")})
    target = Path(csv_path).with_suffix(".rules.json")
    target.write_text(json.dumps(output, ensure_ascii=False, indent=2), encoding="utf-8")
    return target
