import html
import os
import re
from typing import Any, Dict, List
from urllib.parse import unquote

import httpx
from langchain_core.tools import tool


def _clean_html_text(raw_html: str) -> str:
    """Strip HTML tags and unescape text."""
    # Remove script and style elements
    cleaned = re.sub(r"<(script|style)[^>]*>.*?</\1>", " ", raw_html, flags=re.DOTALL | re.IGNORECASE)
    # Remove all other tags
    cleaned = re.sub(r"<[^>]+>", " ", cleaned)
    # Replace multiple whitespaces
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    return html.unescape(cleaned)


def _search_duckduckgo_pkg(query: str, max_results: int = 5) -> List[Dict[str, str]]:
    """Attempt search using duckduckgo_search package."""
    from duckduckgo_search import DDGS

    with DDGS() as ddgs:
        # First try dedicated news tab
        results: List[Dict[str, Any]] = []
        try:
            results = list(ddgs.news(query, max_results=max_results))
        except Exception:
            results = []

        # Fallback to general text search if news returned nothing
        if not results:
            results = list(ddgs.text(query, max_results=max_results))

        parsed: List[Dict[str, str]] = []
        for r in results:
            title = r.get("title", "Untitled")
            url = r.get("url") or r.get("href", "")
            snippet = r.get("body") or r.get("snippet", "")
            date = r.get("date", "Recent")
            source = r.get("source", "Web")
            if url:
                parsed.append({
                    "title": title,
                    "url": url,
                    "snippet": snippet,
                    "date": date,
                    "source": source,
                })
        return parsed


def _search_httpx_fallback(query: str, max_results: int = 5) -> List[Dict[str, str]]:
    """Fallback search using httpx to scrape DuckDuckGo HTML directly without extra dependencies."""
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/124.0.0.0 Safari/537.36"
        ),
        "Accept-Language": "en-US,en;q=0.9",
    }
    url = "https://html.duckduckgo.com/html/"
    parsed: List[Dict[str, str]] = []

    with httpx.Client(timeout=10.0, follow_redirects=True, headers=headers) as client:
        resp = client.post(url, data={"q": query})
        if resp.status_code != 200:
            return parsed

        content = resp.text
        # Extract results matching result__body
        # Regex to capture link, title, and snippet in DDG HTML
        pattern = re.compile(
            r'<a[^>]*class="[^"]*result__url[^"]*"[^>]*href="(?P<url>[^"]+)"[^>]*>.*?'
            r'<a[^>]*class="[^"]*result__title[^"]*"[^>]*>(?P<title>.*?)</a>.*?'
            r'<a[^>]*class="[^"]*result__snippet[^"]*"[^>]*>(?P<snippet>.*?)</a>',
            re.DOTALL | re.IGNORECASE,
        )

        matches = list(pattern.finditer(content))
        if not matches:
            # Broader pattern if specific class nesting changes
            link_pattern = re.compile(
                r'<a\s+class="result__snippet"[^>]*href="(?P<url>[^"]+)".*?>(?P<snippet>.*?)</a>',
                re.DOTALL | re.IGNORECASE,
            )
            title_pattern = re.compile(
                r'<h2\s+class="result__title"[^>]*>\s*<a[^>]*href="(?P<url>[^"]+)"[^>]*>(?P<title>.*?)</a>',
                re.DOTALL | re.IGNORECASE,
            )
            titles = title_pattern.findall(content)
            snippets = link_pattern.findall(content)
            for idx, (t_url, t_text) in enumerate(titles[:max_results]):
                actual_url = t_url
                if "uddg=" in actual_url:
                    actual_url = unquote(actual_url.split("uddg=")[-1].split("&")[0])
                snip_text = snippets[idx][1] if idx < len(snippets) else ""
                parsed.append({
                    "title": _clean_html_text(t_text),
                    "url": actual_url,
                    "snippet": _clean_html_text(snip_text),
                    "date": "Recent",
                    "source": "Web Search",
                })
            return parsed

        for m in matches[:max_results]:
            raw_url = m.group("url")
            # DuckDuckGo HTML often redirects through /l/?uddg=<encoded_url>
            if "uddg=" in raw_url:
                actual_url = unquote(raw_url.split("uddg=")[-1].split("&")[0])
            else:
                actual_url = raw_url

            parsed.append({
                "title": _clean_html_text(m.group("title")),
                "url": actual_url,
                "snippet": _clean_html_text(m.group("snippet")),
                "date": "Recent",
                "source": "Web Search",
            })

    return parsed


def _search_tavily(query: str, max_results: int = 5) -> List[Dict[str, str]]:
    """Attempt search using Tavily API if key is present."""
    from tavily import TavilyClient

    api_key = os.getenv("TAVILY_API_KEY")
    if not api_key:
        raise ValueError("TAVILY_API_KEY not set")

    client = TavilyClient(api_key=api_key)
    res = client.search(query=query, topic="news", max_results=max_results)
    parsed: List[Dict[str, str]] = []
    for r in res.get("results", []):
        parsed.append({
            "title": r.get("title", "Untitled"),
            "url": r.get("url", ""),
            "snippet": r.get("content", ""),
            "date": r.get("published_date", "Recent"),
            "source": "Tavily News",
        })
    return parsed


@tool
def search_latest_news(query: str) -> str:
    """Search for the latest news, breaking industry updates, recent company announcements,
    salary trends, and real-time information outside the knowledge base and LLM training cutoff.
    Returns findings with direct clickable Markdown resource links.
    """
    if not query or not query.strip():
        return "Search query cannot be empty."

    articles: List[Dict[str, str]] = []
    error_notes: List[str] = []

    # 1. Try Tavily if configured
    if os.getenv("TAVILY_API_KEY"):
        try:
            articles = _search_tavily(query.strip(), max_results=5)
        except Exception as e:
            error_notes.append(f"Tavily search notice: {e}")

    # 2. Try duckduckgo_search package
    if not articles:
        try:
            articles = _search_duckduckgo_pkg(query.strip(), max_results=5)
        except Exception as e:
            error_notes.append(f"DDGS search notice: {e}")

    # 3. Fallback to direct HTTP client scraping
    if not articles:
        try:
            articles = _search_httpx_fallback(query.strip(), max_results=5)
        except Exception as e:
            error_notes.append(f"HTTP search fallback notice: {e}")

    if not articles:
        details = f" (Details: {'; '.join(error_notes)})" if error_notes else ""
        return f"No recent news or web results found for '{query}'{details}."

    formatted_entries = []
    resource_links = []

    for idx, item in enumerate(articles, start=1):
        title = item["title"] or f"Resource {idx}"
        url = item["url"]
        snippet = item["snippet"] or "No detailed description available."
        date = item["date"]
        source = item["source"]

        formatted_entries.append(
            f"{idx}. **{title}**\n"
            f"   - **Source/Date**: {source} ({date})\n"
            f"   - **Summary**: {snippet}\n"
            f"   - **Resource Link**: [{title}]({url})"
        )
        resource_links.append(f"- [{title}]({url}) — {source} ({date})")

    results_text = "\n\n".join(formatted_entries)
    links_section = "\n".join(resource_links)

    return (
        f"### Latest Web Search Results for '{query}':\n\n"
        f"{results_text}\n\n"
        f"### Verified Resource Links:\n"
        f"{links_section}"
    )


@tool
def browse_webpage(url: str) -> str:
    """Visit and read the full text content of a specific webpage URL (e.g., job postings,
    company press releases, news articles). Returns the parsed text with the original resource link.
    """
    if not url or not url.strip().startswith(("http://", "https://")):
        return f"Invalid URL: '{url}'. Please provide a valid HTTP/HTTPS web link."

    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/124.0.0.0 Safari/537.36"
        ),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    }

    try:
        with httpx.Client(timeout=12.0, follow_redirects=True, headers=headers) as client:
            resp = client.get(url.strip())
            resp.raise_for_status()

        cleaned_text = _clean_html_text(resp.text)
        # Limit token budget
        max_chars = 3500
        truncated = cleaned_text[:max_chars]
        more_notice = "\n\n*(Content truncated for length)*" if len(cleaned_text) > max_chars else ""

        return (
            f"### Web Page Content\n"
            f"**Resource Link**: [{url}]({url})\n\n"
            f"{truncated}{more_notice}\n\n"
            f"---\n"
            f"**Original Source Link**: [{url}]({url})"
        )
    except httpx.HTTPStatusError as e:
        return f"HTTP error occurred while visiting {url}: {e.response.status_code} ({e})"
    except Exception as e:
        return f"Failed to retrieve webpage at {url}: {str(e)}"
