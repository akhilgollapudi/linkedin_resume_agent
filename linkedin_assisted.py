
from __future__ import annotations

import argparse
import csv
import json
import re
import sys
import time
from pathlib import Path
from urllib.parse import urlparse, parse_qs

from playwright.sync_api import sync_playwright


# ============================================================
# CONFIGURATION
# ============================================================

ROOT = Path(__file__).resolve().parent
PROFILE_DIR = ROOT / "browser_profile"
DATA_DIR = ROOT / "data"

CSV_PATH = DATA_DIR / "linkedin_jobs.csv"
JSON_PATH = DATA_DIR / "linkedin_jobs.json"

DATA_DIR.mkdir(parents=True, exist_ok=True)

DEFAULT_SEARCH_URL = "https://www.linkedin.com/jobs/"

CSV_FIELDS = [
    "job_id",
    "title",
    "company",
    "location",
    "url",
    "description",
    "source",
    "captured_at",
]

INVALID_TITLES = {
    "0 notifications",
    "send feedback",
    "privacy & terms",
    "ad choices",
    "home",
    "jobs",
    "messaging",
    "notifications",
    "about the job",
}


# ============================================================
# GENERAL HELPERS
# ============================================================

def clean(value: str | None) -> str:
    return re.sub(r"\s+", " ", value or "").strip()


def get_job_id(url: str) -> str:
    if not url:
        return ""

    parsed = urlparse(url)
    query = parse_qs(parsed.query)

    job_id = query.get("currentJobId", [None])[0]

    if not job_id:
        match = re.search(r"/jobs/view/(\d+)", url)
        if match:
            job_id = match.group(1)

    return job_id or ""


def normalize_job_url(url: str) -> str:
    job_id = get_job_id(url)

    if job_id:
        return f"https://www.linkedin.com/jobs/view/{job_id}/"

    return url.split("#")[0]


def is_linkedin_url(url: str) -> bool:
    return "linkedin.com" in urlparse(url).netloc.lower()


def is_valid_title(title: str) -> bool:
    value = clean(title)

    if len(value) < 5 or len(value) > 250:
        return False

    if value.lower() in INVALID_TITLES:
        return False

    if "privacy" in value.lower() or "notifications" in value.lower():
        return False

    return True


def is_valid_company(company: str) -> bool:
    value = clean(company)

    if len(value) < 2 or len(value) > 150:
        return False

    invalid = {
        "linkedin",
        "privacy & terms",
        "ad choices",
        "send feedback",
        "notifications",
    }

    return value.lower() not in invalid


def is_linkedin_challenge(page) -> bool:
    url = page.url.lower()

    challenge_terms = (
        "checkpoint",
        "challenge",
        "captcha",
        "authwall",
    )

    if any(term in url for term in challenge_terms):
        return True

    try:
        body = page.locator("body").inner_text(timeout=3000).lower()

        challenge_text = (
            "security verification",
            "verify your identity",
            "unusual activity",
            "captcha",
        )

        return any(term in body for term in challenge_text)

    except Exception:
        return False


# ============================================================
# JOB CARD EXTRACTION
# ============================================================

def extract_visible_job_cards(page) -> list[dict]:
    """
    Extract job cards from the visible search results.

    Intentionally avoids broad ancestor fallbacks. Those fallbacks
    previously picked up navigation/footer text as job titles.
    """

    return page.evaluate("""
    () => {
        const clean = value =>
            (value || '').replace(/\\\\s+/g, ' ').trim();

        const visible = el => {
            if (!el) return false;
            const rect = el.getBoundingClientRect();
            const style = getComputedStyle(el);
            return rect.width > 0 &&
                   rect.height > 0 &&
                   style.display !== 'none' &&
                   style.visibility !== 'hidden';
        };

        const invalid = new Set([
            '0 notifications',
            'send feedback',
            'privacy & terms',
            'ad choices',
            'home',
            'jobs',
            'messaging',
            'notifications'
        ]);

        const anchors = [
            ...document.querySelectorAll(
                'a[href*="/jobs/view/"]'
            )
        ].filter(visible);

        const results = [];
        const seen = new Set();

        for (const anchor of anchors) {
            const href = anchor.href || '';
            const match = href.match(/\\/jobs\\/view\\/(\\d+)/);

            if (!match) continue;

            const jobId = match[1];

            if (seen.has(jobId)) continue;

            // Find a compact list item/card, not an arbitrary ancestor.
            let card = anchor.closest(
                'li, ' +
                '.job-card-container, ' +
                '.jobs-search-results__list-item, ' +
                '.scaffold-layout__list-item'
            );

            if (!card) continue;

            const titleCandidates = [
                anchor.innerText,
                anchor.getAttribute('aria-label'),
                anchor.getAttribute('title'),
                card.querySelector(
                    '.job-card-list__title'
                )?.innerText,
                card.querySelector(
                    '.artdeco-entity-lockup__title'
                )?.innerText
            ];

            let title = '';

            for (const candidate of titleCandidates) {
                const value = clean(candidate);

                if (
                    value &&
                    value.length >= 5 &&
                    value.length <= 250 &&
                    !invalid.has(value.toLowerCase())
                ) {
                    title = value;
                    break;
                }
            }

            if (!title) continue;

            const companyCandidates = [
                card.querySelector(
                    '.artdeco-entity-lockup__subtitle'
                )?.innerText,
                card.querySelector(
                    '.job-card-container__primary-description'
                )?.innerText,
                card.querySelector(
                    '.job-card-container__company-name'
                )?.innerText,
                card.querySelector(
                    '[class*="company-name"]'
                )?.innerText
            ];

            let company = '';

            for (const candidate of companyCandidates) {
                const value = clean(candidate);

                if (
                    value &&
                    value.length >= 2 &&
                    value.length <= 150 &&
                    !invalid.has(value.toLowerCase())
                ) {
                    company = value;
                    break;
                }
            }

            const locationCandidates = [
                card.querySelector(
                    '.artdeco-entity-lockup__caption'
                )?.innerText,
                card.querySelector(
                    '.job-card-container__metadata-item'
                )?.innerText,
                card.querySelector(
                    '[class*="metadata"]'
                )?.innerText
            ];

            let jobLocation = '';

            for (const candidate of locationCandidates) {
                const value = clean(candidate);

                if (value && value.length <= 200) {
                    jobLocation = value;
                    break;
                }
            }

            // Do not save records that have only an ID or URL.
            if (!company) continue;

            seen.add(jobId);

            results.push({
                job_id: jobId,
                title,
                company,
                location: jobLocation,
                url: 'https://www.linkedin.com/jobs/view/' +
                     jobId + '/'
            });
        }

        return results;
    }
    """)


# ============================================================
# SELECTED JOB DETAIL EXTRACTION
# ============================================================




def extract_current_job(page) -> dict:
    """Extract the currently selected LinkedIn job."""

    page.wait_for_timeout(1000)

    # Expand the About the job section.
    try:
        page.evaluate("""
        () => {
            const clean = el =>
                (el?.innerText || '').replace(/\\s+/g, ' ').trim();

            const heading = [...document.querySelectorAll('h2')]
                .find(el => clean(el) === 'About the job');

            if (!heading) return;

            const top = heading.getBoundingClientRect().top;

            const more = [...document.querySelectorAll(
                'button, a, [role="button"], span'
            )].find(el => {
                const r = el.getBoundingClientRect();
                return clean(el).toLowerCase() === 'more' &&
                    r.width > 0 && r.height > 0 &&
                    r.left > window.innerWidth * 0.35 &&
                    Math.abs(r.top - top) < 500;
            });

            if (more) more.click();
        }
        """)
    except Exception:
        pass

    page.wait_for_timeout(1000)

    data = page.evaluate("""
    () => {
        const clean = el =>
            (el?.innerText || '').replace(/\\s+/g, ' ').trim();

        const visible = el => {
            const r = el.getBoundingClientRect();
            const s = getComputedStyle(el);
            return r.width > 0 && r.height > 0 &&
                s.display !== 'none' && s.visibility !== 'hidden';
        };

        const right = el =>
            visible(el) &&
            el.getBoundingClientRect().left >
                window.innerWidth * 0.35;

        const about = [...document.querySelectorAll('h2')]
            .find(el => clean(el) === 'About the job');

        let description = '';

        if (about) {
            description = clean(
                about.parentElement?.parentElement
            ).replace(/^About the job\\s*/i, '');
        }

        // LinkedIn document title is a reliable fallback.
        const pageTitle = document.title
            .replace(/\\s*\\|\\s*LinkedIn\\s*$/i, '')
            .trim();

        let title = '';
        let company = '';

        const titleParts = pageTitle.split(/\\s*\\|\\s*/);

        if (titleParts.length >= 2) {
            title = titleParts[0].trim();
            company = titleParts[1].trim();
        }

        // Prefer actual job header elements when available.
        const companySelectors = [
            '.job-details-jobs-unified-top-card__company-name',
            '.jobs-unified-top-card__company-name',
            'a[href*="/company/"]'
        ];

        for (const selector of companySelectors) {
            const el = [...document.querySelectorAll(selector)]
                .find(right);

            if (el && clean(el)) {
                company = clean(el);
                break;
            }
        }

        const titleSelectors = [
            '.job-details-jobs-unified-top-card__job-title',
            '.jobs-unified-top-card__job-title'
        ];

        for (const selector of titleSelectors) {
            const el = [...document.querySelectorAll(selector)]
                .find(right);

            if (el && clean(el)) {
                title = clean(el);
                break;
            }
        }

        // Extract location from the primary job header.
        let jobLocation = '';

        const locationSelectors = [
            '.job-details-jobs-unified-top-card__primary-description-container',
            '.jobs-unified-top-card__primary-description'
        ];

        for (const selector of locationSelectors) {
            const el = [...document.querySelectorAll(selector)]
                .find(right);

            if (el) {
                jobLocation = clean(el);
                break;
            }
        }

        // Find current job ID.
        const match =
            location.href.match(/[?&]currentJobId=(\\d+)/) ||
            location.href.match(/\\/jobs\\/view\\/(\\d+)/);

        return {
            job_id: match ? match[1] : '',
            title,
            company,
            location: jobLocation,
            description,
            url: location.href,
            page_title: pageTitle,
            error: !title || !company || !description
                ? 'Some required job fields are missing'
                : ''
        };
    }
    """)

    # Reject obviously incorrect metadata.
    invalid = [
        'people you can reach out to',
        'show all',
        '0 notifications',
        'about the job'
    ]

    if any(x in data.get('title', '').lower() for x in invalid):
        data['title'] = ''

    if any(x in data.get('location', '').lower() for x in invalid):
        data['location'] = ''

    return data




# ============================================================
# STORAGE AND VALIDATION
# ============================================================

def make_job_record(data: dict) -> dict:
    url = clean(data.get("url"))
    job_id = clean(data.get("job_id")) or get_job_id(url)

    if job_id:
        url = normalize_job_url(url)

    return {
        "job_id": job_id,
        "title": clean(data.get("title")),
        "company": clean(data.get("company")),
        "location": clean(data.get("location")),
        "url": url,
        "description": clean(data.get("description")),
        "source": "linkedin_user_assisted",
        "captured_at": time.strftime("%Y-%m-%d %H:%M:%S"),
    }


def is_valid_job_record(record: dict) -> bool:
    return (
        bool(record.get("job_id") or record.get("url"))
        and is_valid_title(record.get("title", ""))
        and is_valid_company(record.get("company", ""))
    )


def load_existing_jobs() -> dict[str, dict]:
    """
    Load only valid existing records.

    This also filters the previously polluted CSV entries where
    navigation/footer text was accidentally saved as job metadata.
    """

    jobs = {}

    if not CSV_PATH.exists():
        return jobs

    with CSV_PATH.open(
        "r",
        encoding="utf-8-sig",
        newline=""
    ) as file:
        reader = csv.DictReader(file)

        for row in reader:
            record = make_job_record(row)

            if not is_valid_job_record(record):
                continue

            key = record["job_id"] or record["url"]
            jobs[key] = record

    return jobs


def save_jobs(jobs: dict[str, dict]) -> None:
    valid_rows = [
        row for row in jobs.values()
        if is_valid_job_record(row)
    ]

    with CSV_PATH.open(
        "w",
        encoding="utf-8",
        newline=""
    ) as file:
        writer = csv.DictWriter(
            file,
            fieldnames=CSV_FIELDS
        )
        writer.writeheader()
        writer.writerows(valid_rows)

    JSON_PATH.write_text(
        json.dumps(
            valid_rows,
            indent=2,
            ensure_ascii=False
        ),
        encoding="utf-8"
    )

    print(f"\nSaved {len(valid_rows)} valid jobs.")
    print(f"CSV:  {CSV_PATH}")
    print(f"JSON: {JSON_PATH}")


def add_or_update_job(
    jobs: dict[str, dict],
    data: dict
) -> bool:
    record = make_job_record(data)

    if not is_valid_job_record(record):
        print("\nRejected invalid job record:")
        print("Title:", record["title"] or "(missing)")
        print("Company:", record["company"] or "(missing)")
        return False

    key = record["job_id"] or record["url"]
    existing = jobs.get(key, {})

    # Preserve previously captured description if the new
    # extraction does not expose it.
    if not record["description"]:
        record["description"] = existing.get("description", "")

    # Preserve metadata if a newer capture is incomplete.
    for field in ("title", "company", "location", "url"):
        if not record[field]:
            record[field] = existing.get(field, "")

    jobs[key] = record
    return True


# ============================================================
# DISPLAY AND DIAGNOSTICS
# ============================================================

def print_job_cards(cards: list[dict]) -> None:
    print("\n" + "=" * 70)
    print(f"VALID JOB CARDS FOUND: {len(cards)}")
    print("=" * 70)

    for index, job in enumerate(cards, start=1):
        print(f"\n{index}. {job['title']}")
        print(f"   Company:  {job['company']}")
        print(f"   Location: {job['location']}")
        print(f"   Job ID:   {job['job_id']}")
        print(f"   URL:      {job['url']}")


def debug_linkedin_page(page) -> None:
    """
    Print visible headings and job-related DOM elements.
    Useful if LinkedIn changes its page structure again.
    """

    result = page.evaluate("""
    () => {
        const clean = el =>
            (el.innerText || '').replace(/\\\\s+/g, ' ').trim();

        const visible = el => {
            const r = el.getBoundingClientRect();
            const s = getComputedStyle(el);
            return r.width > 0 &&
                   r.height > 0 &&
                   s.display !== 'none' &&
                   s.visibility !== 'hidden';
        };

        const headings = [
            ...document.querySelectorAll('h1,h2,h3,[role="heading"]')
        ]
        .filter(visible)
        .map(el => ({
            tag: el.tagName,
            className: String(el.className || ''),
            text: clean(el)
        }))
        .filter(x => x.text);

        const jobElements = [
            ...document.querySelectorAll('[class*="job"],[class*="Job"]')
        ]
        .filter(visible)
        .map(el => ({
            tag: el.tagName,
            className: String(el.className || ''),
            text: clean(el).slice(0, 350)
        }))
        .filter(x => x.text.length > 20)
        .slice(0, 40);

        return {
            url: location.href,
            title: document.title,
            headings,
            jobElements
        };
    }
    """)

    print("\n===== LINKEDIN DOM DIAGNOSTIC =====")
    print(json.dumps(result, indent=2, ensure_ascii=False))


# ============================================================
# SEARCH RESULTS CAPTURE
# ============================================================

def collect_search_results(page, jobs: dict[str, dict]) -> int:
    if is_linkedin_challenge(page):
        print("LinkedIn security check detected. Capture stopped.")
        return 0

    page.wait_for_timeout(1500)

    print("\nCurrent page:", page.url)

    cards = extract_visible_job_cards(page)
    print_job_cards(cards)

    saved = 0

    for card in cards:
        if add_or_update_job(jobs, card):
            saved += 1

    save_jobs(jobs)

    print(f"New/updated valid cards: {saved}")
    print(
        "\nNote: search cards usually do not contain the full JD. "
        "Click a job to capture its description and generate a resume."
    )

    return saved


# ============================================================
# INDIVIDUAL JOB CAPTURE
# ============================================================

def capture_current_job(
    page,
    jobs: dict[str, dict],
    on_job_captured=None,
    expected_job_id: str | None = None,
):
    if is_linkedin_challenge(page):
        print("Security check detected. Capture stopped.")
        return

    data = {}
    previous_snapshot = None
    stable_reads = 0
    for _ in range(15):
        page.wait_for_timeout(700)
        data = extract_current_job(page)
        if expected_job_id and data.get("job_id") != expected_job_id:
            continue

        if (
            not is_valid_title(data.get("title", ""))
            or not is_valid_company(data.get("company", ""))
            or len((data.get("description") or "").strip()) < 200
        ):
            stable_reads = 0
            previous_snapshot = None
            continue

        snapshot = (
            data["job_id"],
            data["title"],
            data["company"],
            data["description"],
        )
        if snapshot == previous_snapshot:
            stable_reads += 1
            if stable_reads >= 2:
                break
        else:
            previous_snapshot = snapshot
            stable_reads = 1

    if stable_reads < 2:
        print(
            f"\nCould not load stable, complete details for selected job "
            f"{expected_job_id or '(unknown)'}. No resume was generated."
        )
        return

    print("\nSelected job detected:")
    print("Title:", data["title"])
    print("Company:", data["company"])
    print("Job ID:", data["job_id"])

    if add_or_update_job(jobs, data):
        save_jobs(jobs)

        print("\nJob successfully captured:")
        print("Title:", data["title"])
        print("Company:", data["company"])
        print("Location:", data.get("location", ""))
        print("Description characters:", len(data["description"]))
        if on_job_captured:
            print("\nStarting resume tailoring and PDF generation...")
            on_job_captured(make_job_record(data))
        return make_job_record(data)
    return None


def enqueue_selected_job(job_id: str, selected_job_ids: list[str]) -> None:
    if re.fullmatch(r"\d+", str(job_id or "")) and job_id not in selected_job_ids:
        selected_job_ids.append(job_id)
        print(f"\nDetected selection of LinkedIn job {job_id}; loading its details...")


def detect_url_job_selection(
    page,
    previous_job_id: str,
    selected_job_ids: list[str],
) -> str:
    current_job_id = get_job_id(page.url)
    if current_job_id and current_job_id != previous_job_id:
        enqueue_selected_job(current_job_id, selected_job_ids)
    return current_job_id or previous_job_id


def enqueue_requested_job_url(search_url: str, selected_job_ids: list[str]) -> str:
    job_id = get_job_id(search_url)
    if job_id:
        enqueue_selected_job(job_id, selected_job_ids)
    return job_id


def process_queued_job_selections(
    page,
    jobs: dict[str, dict],
    selected_job_ids: list[str],
    processed_job_ids: set[str],
    on_job_captured=None,
) -> None:
    processed_selection = False
    while selected_job_ids:
        job_id = selected_job_ids.pop(0)
        if not job_id or job_id in processed_job_ids:
            continue

        processed_selection = True
        result = capture_current_job(
            page,
            jobs,
            on_job_captured=on_job_captured,
            expected_job_id=job_id,
        )
        if result:
            processed_job_ids.add(job_id)

    if processed_selection:
        print(
            f"\nReady for another job. Select a different LinkedIn job "
            f"to generate its resume; monitoring remains active."
        )


def install_job_click_listener(page, selected_job_ids: list[str]) -> None:
    def enqueue_job_click(_source, job_id):
        enqueue_selected_job(job_id, selected_job_ids)

    page.expose_binding(
        "notifyLinkedInJobClick",
        enqueue_job_click,
    )
    listener_script = """
    (() => {
        if (window.__linkedinJobClickListenerInstalled) return;
        window.__linkedinJobClickListenerInstalled = true;

        const jobIdFromUrl = value => {
            try {
                const url = new URL(value, location.href);
                return url.searchParams.get('currentJobId') ||
                    (url.pathname.match(/\\/jobs\\/view\\/(\\d+)/) || [])[1] ||
                    '';
            } catch {
                return '';
            }
        };

        document.addEventListener('click', event => {
            const path = event.composedPath();
            let jobId = '';

            for (const node of path) {
                if (!(node instanceof Element)) continue;
                const link = node.closest(
                    'a[href*="/jobs/view/"], a[href*="currentJobId="]'
                );
                if (link) {
                    jobId = jobIdFromUrl(link.href);
                    if (jobId) break;
                }

                const card = node.closest(
                    '[data-job-id], [data-occludable-job-id], ' +
                    '.job-card-container, .jobs-search-results__list-item'
                );
                if (card) {
                    jobId = card.getAttribute('data-job-id') ||
                        card.getAttribute('data-occludable-job-id') || '';
                    if (!/^\\d+$/.test(jobId)) {
                        const cardLink = card.querySelector(
                            'a[href*="/jobs/view/"], a[href*="currentJobId="]'
                        );
                        if (cardLink) jobId = jobIdFromUrl(cardLink.href);
                    }
                    if (/^\\d+$/.test(jobId)) break;
                }
            }

            if (!/^\\d+$/.test(jobId)) return;
            const now = Date.now();
            if (window.__linkedinLastClickedJobId === jobId &&
                now - window.__linkedinLastJobClickAt < 1200) return;

            window.__linkedinLastClickedJobId = jobId;
            window.__linkedinLastJobClickAt = now;
            window.notifyLinkedInJobClick(jobId);
        }, true);
    })();
    """
    page.add_init_script(listener_script)
    page.evaluate(listener_script)


# ============================================================
# SEARCH URL HANDLING
# ============================================================

def resolve_search_url() -> str:
    if len(sys.argv) > 1 and not sys.argv[1].startswith("--"):
        return sys.argv[1].strip()
    return DEFAULT_SEARCH_URL


# ============================================================
# PLAYWRIGHT WORKFLOW
# ============================================================

def run_linkedin_assisted(
    search_urls: list[str] | None = None,
    on_job_captured=None
) -> list[dict]:

    jobs = load_existing_jobs()

    if search_urls is None:
        search_urls = [resolve_search_url()]

    with sync_playwright() as playwright:
        context = playwright.chromium.launch_persistent_context(
            user_data_dir=str(PROFILE_DIR),
            headless=False,
            viewport={
                "width": 1440,
                "height": 950
            },
        )

        page = (
            context.pages[0]
            if context.pages
            else context.new_page()
        )
        selected_job_ids = []
        install_job_click_listener(page, selected_job_ids)
        processed_job_ids = set()

        try:
            for search_url in search_urls:
                if not is_linkedin_url(search_url):
                    print("Skipping non-LinkedIn URL:", search_url)
                    continue

                print("\nOpening supplied LinkedIn URL...")

                page.goto(
                    search_url,
                    wait_until="domcontentloaded",
                    timeout=60000
                )

                print(
                    "\nSign in manually if required."
                    "\nNo password is collected by this script."
                )

                if is_linkedin_challenge(page):
                    print(
                        "\nLinkedIn security check detected."
                        "\nComplete it manually in the browser."
                    )
                    while is_linkedin_challenge(page):
                        page.wait_for_timeout(1000)

                requested_job_id = enqueue_requested_job_url(
                    search_url,
                    selected_job_ids,
                )
                if requested_job_id and get_job_id(page.url) != requested_job_id:
                    page.goto(
                        search_url,
                        wait_until="domcontentloaded",
                        timeout=60000,
                    )
                    while is_linkedin_challenge(page):
                        page.wait_for_timeout(1000)

                last_url_job_id = get_job_id(page.url)
                print(
                    "\nThe job ID in the URL you supplied will be processed automatically."
                    "\nFor a general jobs page, choose a job after login; press Ctrl+C to stop."
                )
                while True:
                    page.wait_for_timeout(500)
                    last_url_job_id = detect_url_job_selection(
                        page,
                        last_url_job_id,
                        selected_job_ids,
                    )
                    process_queued_job_selections(
                        page,
                        jobs,
                        selected_job_ids,
                        processed_job_ids,
                        on_job_captured,
                    )

        except KeyboardInterrupt:
            print("\nInterrupted by user.")

        finally:
            save_jobs(jobs)
            context.close()

    return list(jobs.values())


# ============================================================
# SAMPLE EXTRACTION TEST
# ============================================================

def run_sample_test() -> None:
    sample = {
        "job_id": "4489747790",
        "title": "Senior Manager, Agentic AI Engineering",
        "company": "Optum India",
        "location": "Hyderabad, Telangana, India",
        "url": "https://www.linkedin.com/jobs/view/4489747790/",
        "description": (
            "Lead Agentic AI engineering initiatives, "
            "design enterprise AI systems, and build "
            "production-grade AI applications."
        ),
    }

    record = make_job_record(sample)

    assert record["job_id"] == "4489747790"
    assert record["title"] == "Senior Manager, Agentic AI Engineering"
    assert record["company"] == "Optum India"
    assert is_valid_job_record(record)

    invalid = make_job_record({
        "job_id": "4490288535",
        "title": "0 notifications",
        "company": "Privacy & Terms",
        "url": "https://www.linkedin.com/jobs/view/4490288535/",
    })

    assert not is_valid_job_record(invalid)

    print("Sample normalization and validation tests PASSED.")
    print(json.dumps(record, indent=2))


# ============================================================
# ENTRY POINT
# ============================================================

if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Assisted LinkedIn job discovery"
    )

    parser.add_argument(
        "--test",
        action="store_true",
        help="Run local validation tests without opening browser"
    )

    parser.add_argument(
        "--url",
        type=str,
        help="LinkedIn search or individual job URL"
    )

    args = parser.parse_args()

    if args.test:
        run_sample_test()

    elif args.url:
        run_linkedin_assisted([args.url])

    else:
        run_linkedin_assisted()
