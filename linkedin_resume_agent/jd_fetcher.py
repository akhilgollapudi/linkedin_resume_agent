from urllib.parse import urlparse
import httpx
from bs4 import BeautifulSoup


def fetch_public_description(url, timeout=15, max_chars=30000):
    """Fetch only public non-LinkedIn career pages; LinkedIn automation is intentionally blocked."""
    host = (urlparse(url).hostname or "").lower()
    if host == "linkedin.com" or host.endswith(".linkedin.com"):
        raise ValueError("LinkedIn pages are not fetched automatically. Paste the JD into the CSV.")
    if not url.startswith(("http://", "https://")):
        raise ValueError("JD URL must be an http(s) URL")
    headers = {"User-Agent": "Mozilla/5.0 (compatible; ResumeTailoringAssistant/1.0; +https://example.invalid)"}
    with httpx.Client(timeout=timeout, follow_redirects=True, headers=headers) as client:
        response = client.get(url)
        response.raise_for_status()
    soup = BeautifulSoup(response.text, "html.parser")
    for node in soup(["script", "style", "nav", "footer", "header", "noscript"]):
        node.decompose()
    main = soup.find("main") or soup.find("article") or soup.body or soup
    text = "\n".join(line.strip() for line in main.get_text("\n").splitlines() if line.strip())
    return text[:max_chars]
