import csv
from pathlib import Path
from .utils import stable_job_id

REQUIRED = {"title", "company"}


def read_jobs(csv_path):
    path = Path(csv_path)
    if not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("job_id,title,company,location,url,description,posted_date,source\n", encoding="utf-8")
        return []
    jobs = []
    with path.open(newline="", encoding="utf-8-sig") as f:
        for row in csv.DictReader(f):
            row = {k: (v or "").strip() for k, v in row.items()}
            if not row.get("title") or not row.get("company"):
                continue
            row["job_id"] = stable_job_id(row)
            jobs.append(row)
    return jobs


def append_discovered_jobs(csv_path, discovered):
    """Append unique public job records to the CSV, preserving existing imports."""
    path = Path(csv_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fields = ["job_id", "title", "company", "location", "url", "description", "posted_date", "source"]
    existing = read_jobs(path)
    known = {job["job_id"] for job in existing}
    added = 0
    needs_header = not path.exists() or path.stat().st_size == 0
    with path.open("a", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
        if needs_header:
            writer.writeheader()
        for job in discovered:
            job_id = job.get("job_id") or stable_job_id(job)
            if job_id in known:
                continue
            row = {key: job.get(key, "") for key in fields}
            row["job_id"] = job_id
            writer.writerow(row)
            known.add(job_id)
            added += 1
    return added
