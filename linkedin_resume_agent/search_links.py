from urllib.parse import urlencode
from pathlib import Path


def build_search_urls(settings):
    profile = settings["profile"]
    urls = []
    for query in profile.get("search_queries", []):
        params = {"keywords": query, "location": profile.get("location", "")}
        urls.append((query, "https://www.linkedin.com/jobs/search/?" + urlencode(params)))
    return urls


def write_search_html(settings, output_path):
    rows = build_search_urls(settings)
    html = ["<!doctype html><html><head><meta charset='utf-8'><title>LinkedIn job searches</title>",
            "<style>body{font:16px Arial;max-width:900px;margin:40px auto;padding:0 20px}li{margin:16px 0}a{color:#0a66c2}</style></head><body>",
            "<h1>LinkedIn job searches</h1><p>These links are provided for optional manual review. The agent separately discovers publicly indexed employer and ATS postings when you run python main.py. It does not scrape LinkedIn or access logged-in pages.</p><ul>"]
    for query, url in rows:
        html.append(f"<li><a target='_blank' rel='noopener' href='{url}'>{query}</a></li>")
    html.append("</ul></body></html>")
    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    Path(output_path).write_text("\n".join(html), encoding="utf-8")
    return rows
