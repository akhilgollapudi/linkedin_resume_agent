import hashlib
import json
import re
from pathlib import Path


def load_json(path):
    with Path(path).open(encoding="utf-8") as f:
        return json.load(f)


def save_json(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def slug(value, limit=55):
    value = re.sub(r"[^a-zA-Z0-9]+", "_", str(value)).strip("_").lower()
    return (value or "job")[:limit]


def stable_job_id(job):
    if job.get("job_id"):
        return str(job["job_id"]).strip()
    raw = "|".join(str(job.get(k, "")) for k in ("title", "company", "location", "url"))
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:14]


def plain_text(value):
    value = re.sub(r"<[^>]+>", " ", str(value or ""))
    value = re.sub(r"\*\*(.*?)\*\*", r"\1", value)
    return re.sub(r"\s+", " ", value).strip()
