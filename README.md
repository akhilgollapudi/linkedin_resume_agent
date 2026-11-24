# LinkedIn Job → Tailored Resume Agent

This version uses a user-assisted browser session. It does not hardcode a job title, company, or job ID.

## Main workflow

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
playwright install chromium
cp .env.example .env
python main.py
```

1. A persistent local Chromium profile opens at LinkedIn Jobs.
2. Sign in manually if needed. The script does not collect your password.
3. Search/navigate normally and click the job you want.
4. Return to the terminal, choose **1. Confirm selected job + generate tailored PDF**, and confirm the displayed role.
5. The selected job's title, company, URL and visible job description are extracted.
6. A local keyword relevance score is calculated; selected jobs are not rejected by this heuristic.
7. Existing projects and skills are reordered by relevance. Existing experience bullets and metrics remain unchanged.
8. If `GROQ_API_KEY` is configured, Groq creates a role-targeted summary using only the supplied resume evidence. Otherwise, role-relevant achievements are selected from the master resume.
9. A two-page PDF, tailored JSON, job description and match report are saved under `output/<company>_<role>_<jobid>/`.
10. The job is saved to `data/jobs.csv` and SQLite history.

## LLM use

Set `GROQ_API_KEY` in `.env` to enable hosted LLM summary tailoring through GroqCloud. `GROQ_MODEL` defaults to `openai/gpt-oss-20b`, which was verified against the live Groq API. Check the Groq console for active model availability and your account's free-tier limits; usage on the free tier is rate-limited. The prompt prioritizes relevant job-description terminology only when supported by the supplied resume, and requests a concise, plain-text, ATS-readable summary. If the LLM is unavailable or its output fails validation, the summary is built from up to two exact, role-relevant achievements in the master resume. Project and bullet ordering, skills, and the clearly marked target-role headline are tailored per job; no unsupported qualifications are added. Dates, employers, metrics, and achievement wording remain grounded in the master resume. The reported local match percentage is calculated against the final tailored resume, but remains only a keyword-overlap heuristic, not an ATS score; no prompt can guarantee a 100% ATS match or hiring outcome. Always review the generated PDF for factual accuracy.

Without an API key, the pipeline still works: it reorders existing experience and skills using local JD vocabulary matching and creates the PDF.

## Commands

```bash
python main.py
python main.py --url "https://www.linkedin.com/jobs/search/?keywords=AI"
python main.py process-csv
```

`process-csv` displays the complete records already in `data/jobs.csv` and prompts you to select and confirm exactly one job. Press Enter or decline confirmation to cancel without processing. The main browser workflow is the default; collecting search listings does not generate resumes, and browser-based generation requires confirming the selected role.

## LinkedIn safety and reliability

The browser profile is stored locally in `browser_profile/`; do not share that directory or the browser session. Sign in yourself. If LinkedIn presents a security check, complete it manually; the collector stops if a challenge remains. Do not use this tool to bypass access controls or automate applications.

LinkedIn changes its page structure periodically. If the selected job description or title cannot be extracted, no PDF is generated; use the diagnostic option and inspect the selected job panel. Location may be blank when LinkedIn does not expose it reliably.

## Output integrity

- `data/master_resume.json` is the master source and is never modified by tailoring.
- Each job gets its own output folder.
- PDF generation requires exactly two pages; if the layout exceeds two pages, the PDF is not retained and the error is printed.
- Match percentage is a heuristic vocabulary overlap indicator, not an ATS score or hiring probability.
- Human review is required before submitting any resume.
