"""Web tools (ported from Rome)."""

from __future__ import annotations

import re

try:
    from strands import tool
except Exception:  # pragma: no cover
    def tool(fn):
        return fn


@tool
def web_search(query: str) -> str:
    """Search the web via DuckDuckGo. Returns top results with titles and URLs."""
    import httpx

    resp = httpx.get(
        "https://html.duckduckgo.com/html/",
        params={"q": query},
        headers={"User-Agent": "Formica/0.1"},
        follow_redirects=True,
        timeout=15,
    )
    text = resp.text
    links = re.findall(r'<a rel="nofollow" class="result__a" href="([^"]+)"[^>]*>(.+?)</a>', text)
    snippets = re.findall(r'<a class="result__snippet"[^>]*>(.+?)</a>', text)
    out = []
    for i, (url, title) in enumerate(links[:5]):
        snippet = snippets[i] if i < len(snippets) else ""
        title = re.sub(r"<[^>]+>", "", title)
        snippet = re.sub(r"<[^>]+>", "", snippet)
        out.append(f"- {title}\n  {url}\n  {snippet}")
    return f"Search results for '{query}':\n\n" + "\n\n".join(out) if out else f"No results for {query}"


@tool
def web_fetch(url: str) -> str:
    """Fetch a URL and return cleaned text (truncated)."""
    import httpx

    try:
        resp = httpx.get(
            url,
            headers={"User-Agent": "Formica/0.1"},
            follow_redirects=True,
            timeout=15,
        )
        resp.raise_for_status()
    except Exception as e:
        return f"Failed to fetch {url}: {e}"
    text = resp.text
    text = re.sub(r"<script[^>]*>.*?</script>", "", text, flags=re.DOTALL)
    text = re.sub(r"<style[^>]*>.*?</style>", "", text, flags=re.DOTALL)
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    if len(text) > 3000:
        text = text[:3000] + "... [truncated]"
    return text
