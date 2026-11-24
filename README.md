# LinkedIn Job → Tailored Resume Agent

This version uses a user-assisted browser session. It does not hardcode a job title, company, or job ID.

## Main workflow

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
playwright install chromium
cp .env.example .env
cp data/master_resume.example.json data/master_resume.json
python main.py
```

Replace the placeholder contents of `data/master_resume.json` with your own resume. `.env`, `data/master_resume.json`, and locally captured LinkedIn job history are ignored by Git; do not commit credentials or personal resume data.

1. A persistent local Chromium profile opens at LinkedIn Jobs.
2. Sign in manually if needed. The script does not collect your password.
3. If the URL supplied with `--url` includes a selected job (`currentJobId` or `/jobs/view/<id>`), that requested job is processed on load, even if LinkedIn redirects during sign-in. For a general `/jobs/` URL, the app ignores any remembered job on the landing page and waits for you to select one after login. Later selections are detected through the click or LinkedIn's `currentJobId` change.
4. The selected job's title, company, ID, URL and visible description are checked for stability before processing; incomplete descriptions are rejected.
5. A local keyword relevance score is calculated; selected jobs are not rejected by this heuristic.
6. Existing projects and skills are reordered by relevance.
7. The match report maps JD statements to the closest existing resume evidence and marks unsupported statements as gaps.
8. If an LLM provider key is configured, the app tailors the summary, rewrites/reorders existing experience bullets in batches of five, and generates up to two JD-based responsibility bullets. It defaults to OpenRouter's `openrouter/free` router, which chooses an available free model. Set `LLM_PROVIDER=groq` to use Groq instead. Empty or incomplete summaries fall back to complete resume evidence; provider failures are recorded in the match report. JD additions are capped to preserve the two-page output target and marked in the report. Without a configured provider key, source bullets remain unchanged and are locally reordered by relevance.
9. A two-page PDF, tailored JSON, job description and match report are saved under `output/<company>_<role>_<jobid>/`.
10. The job is saved to `data/jobs.csv` and SQLite history.
11. After each job finishes, the browser remains open and the terminal reports that it is ready for another job selection.

## LLM use

Set `OPENROUTER_API_KEY` in `.env` to enable hosted tailoring; by default the app uses OpenRouter's `openrouter/free` router. Free-model availability and rate limits vary. To choose another OpenRouter model, set `OPENROUTER_MODEL`. To use Groq, set `LLM_PROVIDER=groq` and configure `GROQ_API_KEY` plus optional `GROQ_MODEL`. Under the user's standing authorization, the model automatically tailors supported experience and generates JD-based responsibility bullets for inclusion without a per-job prompt. Generated additions are marked as AI-generated in the match report. The model must not introduce unsupported metrics, technologies, employers, or dates. If the LLM is unavailable or validation fails, original bullets are retained and locally reordered. Project ordering and skills are tailored per job; the candidate's existing headline is preserved. The reported local match percentage is a keyword-overlap heuristic, not an ATS score; no prompt can guarantee a 100% ATS match or hiring outcome. Always review the generated PDF for factual accuracy.

Without an API key, the pipeline still works: it reorders existing experience and skills using local JD vocabulary matching and creates the PDF without generating JD-only additions.

## Commands

```bash
python main.py
python main.py --url "https://www.linkedin.com/jobs/search/?keywords=AI"
python main.py process-csv
```

`process-csv` displays complete records in `data/jobs.csv` and prompts you to select and confirm one job. In the browser workflow, no job menu or second ID prompt is needed: clicking a job starts processing it automatically. Press Ctrl+C in the terminal to stop monitoring.

## LinkedIn safety and reliability

The browser profile is stored locally in `browser_profile/`; do not share that directory or the browser session. Sign in yourself. If LinkedIn presents a security check, complete it manually; the collector stops if a challenge remains. Do not use this tool to bypass access controls or automate applications.

LinkedIn changes its page structure periodically. If the selected job description or title cannot be extracted, no PDF is generated; inspect the selected job panel and retry the click. Location may be blank when LinkedIn does not expose it reliably.

## Output integrity

- `data/master_resume.json` is the master source and is never modified by tailoring.
- Each job gets its own output folder.
- PDF generation requires exactly two pages; if the layout exceeds two pages, the PDF is not retained and the error is printed.
- Match percentage is a heuristic vocabulary overlap indicator, not an ATS score or hiring probability.
- Human review is required before submitting any resume.
