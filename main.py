import argparse
import csv
from pathlib import Path
import yaml
from dotenv import load_dotenv

from linkedin_assisted import run_linkedin_assisted
from linkedin_resume_agent.ingest import read_jobs
from linkedin_resume_agent.matcher import analyze_job_alignment, score_job, tailor_resume
from linkedin_resume_agent.pdf_generator import build_pdf
from linkedin_resume_agent.llm_analysis import (
    tailor_experience_with_llm,
    generate_jd_bullet_proposals,
    tailor_summary_with_llm,
)
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


def include_preapproved_jd_bullet_proposals(proposals):
    """Include proposals under the user's standing authorization."""
    for proposal in proposals:
        proposal["status"] = "ai_generated_user_preapproved"
        proposal["approved"] = True
        proposal["approval_basis"] = "User authorized automatic inclusion"
    return proposals


def process_captured_job(settings, job):
    """Process the job selected by the user in LinkedIn and generate its PDF."""
    if len((job.get("description") or "").strip()) < 200:
        print("STOPPED: full job description was not captured; no resume generated.")
        return None

    resume = load_json(resolve(settings["resume"]["master_json"]))
    job["job_id"] = stable_job_id(job)
    match = score_job(resume, job)
    jd_alignment = analyze_job_alignment(job, resume)
    resume_for_tailoring, experience_result = tailor_experience_with_llm(job, resume)
    proposals, proposal_result = generate_jd_bullet_proposals(job, resume)
    included_proposals = include_preapproved_jd_bullet_proposals(proposals)
    for proposal in included_proposals:
        resume_for_tailoring["work"][proposal["role_index"]].setdefault(
            "highlights",
            [],
        ).append(proposal["bullet"])

    # Explicitly selected jobs are processed regardless of heuristic score.
    tailored = tailor_resume(resume_for_tailoring, job, match)
    llm_result = tailor_summary_with_llm(job, resume_for_tailoring)
    tailored.setdefault("basics", {})["summary"] = llm_result["summary"]
    match = score_job(tailored, job)
    tailored["targeting"]["match_score"] = match["score"]

    output_root = resolve(settings["resume"]["output_dir"])
    folder = output_root / f'{slug(job.get("company"))}_{slug(job.get("title"))}_{slug(job["job_id"], 20)}'
    folder.mkdir(parents=True, exist_ok=True)

    save_json(folder / "resume.json", tailored)
    (folder / "job_description.txt").write_text(job["description"], encoding="utf-8")
    report = {
        "job": {k: job.get(k, "") for k in ("job_id", "title", "company", "location", "url", "source")},
        "match": match,
        "llm_summary": {k: v for k, v in llm_result.items() if k != "summary"},
        "llm_experience": experience_result,
        "llm_jd_proposals": proposal_result,
        "jd_bullet_proposals": proposals,
        "jd_alignment_before_tailoring": jd_alignment,
        "jd_alignment_after_tailoring": analyze_job_alignment(
            job,
            resume_for_tailoring,
        ),
        "tailoring": {
            "summary": "LLM-generated when available; otherwise exact role-relevant achievements are selected from the master resume",
            "experience_bullets": "LLM-rewritten and relevance-ordered from existing source bullets; JD-based proposals are automatically included under user authorization",
            "responsibility_mapping": "JD statements are mapped to existing resume evidence; unmatched responsibilities are AI-generated additions marked in the report",
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
    jobs = read_jobs(resolve(settings["jobs"]["csv_path"]))
    if not jobs:
        print("No imported jobs with complete records are available.")
        return

    print("\nAvailable imported jobs:")
    for index, job in enumerate(jobs, start=1):
        print(f'{index}. {job.get("title", "(untitled)")} | {job.get("company", "(unknown company)")} | ID {job["job_id"]}')

    selection = input("\nEnter the number of the one job to process (or press Enter to cancel): ").strip()
    if not selection:
        print("Cancelled; no imported jobs were processed.")
        return
    try:
        selected_index = int(selection) - 1
    except ValueError:
        print("Invalid selection; no imported jobs were processed.")
        return
    if selected_index < 0 or selected_index >= len(jobs):
        print("Selection is out of range; no imported jobs were processed.")
        return

    job = jobs[selected_index]
    store = JobStore(resolve(settings["jobs"]["database_path"]))
    if store.is_processed(job["job_id"]) and not force:
        print("This job was already processed. Use --force to regenerate it.")
        return
    if len(job.get("description", "")) < 200:
        print(f'SKIP incomplete JD: {job.get("title")} at {job.get("company")}')
        return

    confirmation = input(
        f'Process only "{job.get("title")}" at {job.get("company")}? [y/N]: '
    ).strip().lower()
    if confirmation not in {"y", "yes"}:
        print("Cancelled; no imported jobs were processed.")
        return

    process_captured_job(settings, job)


def main():
    load_dotenv(ROOT / ".env")
    settings = load_settings()
    parser = argparse.ArgumentParser(description="LinkedIn assisted job-to-tailored-resume workflow")
    parser.add_argument("--url", help="Optional LinkedIn search or job URL to open")
    parser.add_argument("--force", action="store_true", help="Reserved for reprocessing imported jobs")
    sub = parser.add_subparsers(dest="command")
    sub.add_parser("process-csv", help="Select and process one complete job from data/jobs.csv")
    args = parser.parse_args()

    if args.command == "process-csv":
        process_imported_jobs(settings, force=args.force)
        return

    urls = [args.url] if args.url else None
    print("=== LinkedIn Job → Tailored Resume ===")
    print("Browser opens with a persistent local profile.")
    print("Sign in manually if required. A job ID in --url is processed automatically.")
    print("On a general jobs page, select a job after login; it starts processing automatically.")
    print("After each job finishes, the browser stays open and waits for another selection.")
    print("Press Ctrl+C to stop.")
    run_linkedin_assisted(
        search_urls=urls,
        on_job_captured=lambda job: process_captured_job(settings, job)
    )


if __name__ == "__main__":
    main()
