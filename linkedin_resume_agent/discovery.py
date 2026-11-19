"""Discover publicly indexed job postings without signing into or scraping LinkedIn.

Search-engine results are used only to discover employer/ATS URLs. Job descriptions
are fetched from public employer/ATS pages and accepted only when a JobPosting
schema or a sufficiently detailed page body is available.
"""
from __future__ import annotations

import html
import json
import re
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from urllib.parse import parse_qs, urlparse, urljoin

import httpx
from bs4 import BeautifulSoup

from .utils import stable_job_id

HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; PublicJobDiscovery/1.0; +https://example.org/bot)"
}
BLOCKED_HOSTS = ("linkedin.com",)
AGGREGATOR_HOSTS = ("indeed.com", "glassdoor.com", "naukri.com", "foundit.in", "ziprecruiter.com")


def _host(url: str) -> str:
    return (urlparse(url).hostname or "").lower().removeprefix("www.")


def _blocked(url: str) -> bool:
    host = _host(url)
    return any(host == d or host.endswith("." + d) for d in BLOCKED_HOSTS)


def _search_ddg(client: httpx.Client, query: str, limit: int):
    response = client.get("https://html.duckduckgo.com/html/", params={"q": query})
    response.raise_for_status()
    soup = BeautifulSoup(response.text, "html.parser")
    found = []
    for result in soup.select(".result"):
        a = result.select_one("a.result__a")
        if not a or not a.get("href"):
            continue
        url = html.unescape(a["href"])
        if url.startswith("//"):
            url = "https:" + url
        if url.startswith("/"):
            url = urljoin("https://html.duckduckgo.com", url)
        parsed = urlparse(url)
        if "duckduckgo.com" in (parsed.hostname or ""):
            target = parse_qs(parsed.query).get("uddg", [])
            if target:
                url = target[0]
        snippet = result.select_one(".result__snippet")
        found.append({"title": a.get_text(" ", strip=True), "url": url,
                      "snippet": snippet.get_text(" ", strip=True) if snippet else ""})
        if len(found) >= limit:
            break
    return found


def _search_bing_rss(client: httpx.Client, query: str, limit: int):
    response = client.get("https://www.bing.com/search", params={"format": "rss", "q": query})
    response.raise_for_status()
    soup = BeautifulSoup(response.text, "html.parser")
    found = []
    for item in soup.find_all("item")[:limit]:
        found.append({"title": item.title.get_text(" ", strip=True) if item.title else "",
                      "url": item.link.get_text(strip=True) if item.link else "",
                      "snippet": item.description.get_text(" ", strip=True) if item.description else ""})
    return found


def search_public_jobs(settings, timeout=20, per_query=12, pause=0.4):
    """Return publicly indexed job result URLs. Search providers are best-effort."""
    profile = settings["profile"]
    location = profile.get("location", "")
    queries = profile.get("search_queries", [])
    results, seen = [], set()
    with httpx.Client(timeout=timeout, follow_redirects=True, headers=HEADERS) as client:
        for role in queries:
            # Employer ATS and company-career URLs are preferred; LinkedIn is excluded.
            q = (f'"{role}" "{location}" '
                 '(site:jobs.lever.co OR site:boards.greenhouse.io OR '
                 'site:jobs.ashbyhq.com OR site:myworkdayjobs.com OR careers)')
            try:
                rows = _search_ddg(client, q, per_query)
            except Exception:
                try:
                    rows = _search_bing_rss(client, q, per_query)
                except Exception:
                    rows = []
            for row in rows:
                url = row.get("url", "").strip()
                if not url.startswith(("http://", "https://")) or _blocked(url):
                    continue
                if url in seen:
                    continue
                seen.add(url)
                row["search_role"] = role
                results.append(row)
            if pause:
                time.sleep(pause)
    return results


def _flatten(value):
    if isinstance(value, list):
        for x in value:
            yield from _flatten(x)
    elif isinstance(value, dict):
        if value.get("@type") == "JobPosting" or "JobPosting" in value.get("@type", [] if isinstance(value.get("@type"), list) else ""):
            yield value
        for v in value.values():
            if isinstance(v, (dict, list)):
                yield from _flatten(v)


def _text(value):
    if isinstance(value, dict):
        return value.get("name") or value.get("@value") or ""
    if isinstance(value, list):
        return ", ".join(filter(None, (_text(v) for v in value)))
    return str(value or "")


def extract_job_posting(url: str, timeout=15, max_chars=30000):
    if _blocked(url):
        return None
    with httpx.Client(timeout=timeout, follow_redirects=True, headers=HEADERS) as client:
        response = client.get(url)
        response.raise_for_status()
    soup = BeautifulSoup(response.text, "html.parser")
    for script in soup.find_all("script", attrs={"type": "application/ld+json"}):
        try:
            data = json.loads(script.string or script.get_text())
        except Exception:
            continue
        for posting in _flatten(data):
            org = posting.get("hiringOrganization") or {}
            location = posting.get("jobLocation") or posting.get("jobLocationType") or ""
            if isinstance(location, list):
                location = location[0] if location else ""
            address = location.get("address", {}) if isinstance(location, dict) else {}
            loc_text = ", ".join(filter(None, [
                _text(address.get("addressLocality")), _text(address.get("addressRegion")),
                _text(address.get("addressCountry"))])) if isinstance(address, dict) else _text(location)
            description_html = posting.get("description", "")
            description = BeautifulSoup(description_html, "html.parser").get_text("\n", strip=True)
            title = _text(posting.get("title"))
            company = _text(org.get("name")) if isinstance(org, dict) else _text(org)
            if title and company and len(description) >= 200:
                return {"title": title, "company": company, "location": loc_text,
                        "url": response.url.__str__(), "description": description[:max_chars],
                        "posted_date": _text(posting.get("datePosted")), "source": "public_jobposting_jsonld"}

    # Conservative fallback for employer career pages with a clear title and long main body.
    for node in soup(["script", "style", "nav", "footer", "header", "noscript"]):
        node.decompose()
    main = soup.find("main") or soup.find("article") or soup.body or soup
    description = "\n".join(x.strip() for x in main.get_text("\n").splitlines() if x.strip())
    title = soup.find("h1") or soup.title
    title_text = title.get_text(" ", strip=True) if title else ""
    if len(description) >= 500 and title_text:
        # Do not guess a company from a generic search engine or domain name.
        company = ""
        org_meta = soup.find(attrs={"property": "og:site_name"}) or soup.find(attrs={"name": "author"})
        if org_meta:
            company = org_meta.get("content", "").strip()
        if company:
            return {"title": title_text, "company": company, "location": "",
                    "url": response.url.__str__(), "description": description[:max_chars],
                    "posted_date": "", "source": "public_employer_page"}
    return None


def discover_jobs(settings, timeout=20, per_query=12, max_candidates=80, pause=0.4):
    candidates = search_public_jobs(settings, timeout=timeout, per_query=per_query, pause=pause)
    eligible = []
    for item in candidates:
        host = _host(item["url"])
        if any(host == d or host.endswith("." + d) for d in AGGREGATOR_HOSTS):
            continue
        eligible.append(item)
    jobs, seen_ids = [], set()
    excluded = [x.lower() for x in settings["profile"].get("exclude_terms", [])]

    def fetch(item):
        return extract_job_posting(item["url"], timeout=timeout,
                                   max_chars=settings["jobs"].get("max_description_chars", 30000))

    # Bound concurrency so a large result set does not create an excessive burst.
    with ThreadPoolExecutor(max_workers=6) as pool:
        futures = [pool.submit(fetch, item) for item in eligible[:max_candidates]]
        for future in as_completed(futures):
            try:
                job = future.result()
            except Exception:
                continue
            if not job:
                continue
            desired_location = settings["profile"].get("location", "").lower()
            actual_location = (job.get("location") or "").lower()
            city = desired_location.split(",")[0].strip()
            if actual_location and city and not any(
                term in actual_location for term in (city, "remote", "india", "anywhere")
            ):
                continue
            full = " ".join([job["title"], job["company"], job["description"]]).lower()
            if any(term in full for term in excluded):
                continue
            job["job_id"] = stable_job_id(job)
            if job["job_id"] not in seen_ids:
                seen_ids.add(job["job_id"])
                jobs.append(job)
    return jobs
