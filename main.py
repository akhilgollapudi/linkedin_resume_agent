import argparse
import csv
import os
from pathlib import Path
import yaml
from dotenv import load_dotenv

from linkedin_assisted import run_linkedin_assisted
from linkedin_resume_agent.ingest import read_jobs
from linkedin_resume_agent.matcher import score_job, tailor_resume
from linkedin_resume_agent.pdf_generator import build_pdf
from linkedin_resume_agent.llm_analysis import tailor_summary_with_llm
from linkedin_resume_agent.storage import JobStore
from linkedin_resume_agent.utils import load_json, save_json, slug, stable_job_id

ROOT = Path(__file__).resolve().parent


def load_settings():
    with (ROOT / "config/settings.yaml").open(encoding="utf-8") as f:
        return yaml.safe_load(f)


def resolve(path):
    p = Path(path)
    return p if p.is_absolute() else ROOT / p


def save_job_csv(job, path):
    fields = ["job_id", "title", "company", "location", "url", "description", "posted_date", "source"]
    path.parent.mkdir(parents=True, exist_ok=True)
    existing = {}
    if path.exists():
        with path.open(newline="", encoding="utf-8-sig") as f:
            for row in csv.DictReader(f):
                if row.get("job_id"):
                    existing[row["job_id"]] = row
    row = {k: job.get(k, "") for k in fields}
    row["job_id"] = stable_job_id(job)
    existing[row["job_id"]] = row
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        writer.writerows(existing.values())


def process_captured_job(settings, job):
    """Process the job selected by the user in LinkedIn and generate its PDF."""
    if len((job.get("description") or "").strip()) < 200:
        print("STOPPED: full job description was not captured; no resume generated.")
        return None

    resume = load_json(resolve(settings["resume"]["master_json"]))
    job["job_id"] = stable_job_id(job)
    match = score_job(resume, job)

    # Explicitly selected jobs are processed regardless of heuristic score.
    tailored = tailor_resume(resume, job, match)
    llm_result = tailor_summary_with_llm(job, resume)
    tailored.setdefault("basics", {})["summary"] = llm_result["summary"]

    output_root = resolve(settings["resume"]["output_dir"])
    folder = output_root / f'{slug(job.get("company"))}_{slug(job.get("title"))}_{slug(job["job_id"], 20)}'
    folder.mkdir(parents=True, exist_ok=True)

    save_json(folder / "resume.json", tailored)
    (folder / "job_description.txt").write_text(job["description"], encoding="utf-8")
    report = {
        "job": {k: job.get(k, "") for k in ("job_id", "title", "company", "location", "url", "source")},
        "match": match,
        "llm_summary": {k: v for k, v in llm_result.items() if k != "summary"},
        "tailoring": {
            "summary": "LLM-generated when OPENAI_API_KEY is configured; otherwise master summary retained",
            "experience_bullets": "Preserved verbatim; projects are reordered by JD relevance",
            "skills": "Existing skills reordered by JD relevance",
            "master_resume_modified": False,
            "human_review_required": True
        }
    }
    save_json(folder / "match_report.json", report)

    try:
        pages = build_pdf(tailored, folder / "resume.pdf", settings["resume"].get("target_pages", 2))
    except Exception as exc:
        print(f"PDF generation failed: {type(exc).__name__}: {exc}")
        print("The tailored JSON and match report were retained for review.")
        return None

    save_job_csv(job, resolve(settings["jobs"]["csv_path"]))
    store = JobStore(resolve(settings["jobs"]["database_path"]))
    store.save(job, "processed", match["score"], str(folder))
    print("\n" + "=" * 68)
    print("TAILORED RESUME GENERATED")
    print("=" * 68)
    print(f'Role:       {job.get("title")} | {job.get("company")}')
    print(f'Match:      {match["score"]}% (keyword overlap indicator, not ATS probability)')
    print(f'LLM:        {"Used: " + str(llm_result.get("model")) if llm_result.get("used") else "Not used; " + llm_result.get("reason", "fallback")}')
    print(f'PDF:        {folder / "resume.pdf"}')
    print(f'JSON:       {folder / "resume.json"}')
    print(f'Report:     {folder / "match_report.json"}')
    print(f'Pages:      {pages}')
    print("Review the PDF before submitting it.")
    return folder / "resume.pdf"


def process_imported_jobs(settings, force=False):
    resume = load_json(resolve(settings["resume"]["master_json"]))
    jobs = read_jobs(resolve(settings["jobs"]["csv_path"]))
    store = JobStore(resolve(settings["jobs"]["database_path"]))
    done = 0
    for job in jobs:
        if store.is_processed(job["job_id"]) and not force:
            continue
        if len(job.get("description", "")) < 200:
            print(f'SKIP incomplete JD: {job.get("title")} at {job.get("company")}')
            continue
        pdf = process_captured_job(settings, job)
        if pdf:
            done += 1
    print(f"Completed {done} job(s).")


def main():
    load_dotenv(ROOT / ".env")
    settings = load_settings()
    parser = argparse.ArgumentParser(description="LinkedIn assisted job-to-tailored-resume workflow")
    parser.add_argument("--url", help="Optional LinkedIn search or job URL to open")
    parser.add_argument("--force", action="store_true", help="Reserved for reprocessing imported jobs")
    sub = parser.add_subparsers(dest="command")
    sub.add_parser("process-csv", help="Process complete jobs already in data/jobs.csv")
    args = parser.parse_args()

    if args.command == "process-csv":
        process_imported_jobs(settings, force=args.force)
        return

    urls = [args.url] if args.url else None
    print("=== LinkedIn Job → Tailored Resume ===")
    print("1) Browser opens with a persistent local profile.")
    print("2) Sign in manually, select a job, and wait for its details panel.")
    print("3) In the terminal choose option 1 to capture and generate the PDF.")
    print("4) No job title or company is hardcoded.")
    run_linkedin_assisted(
        search_urls=urls,
        on_job_captured=lambda job: process_captured_job(settings, job)
    )


if __name__ == "__main__":
    main()
