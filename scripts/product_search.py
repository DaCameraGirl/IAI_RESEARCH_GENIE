#!/usr/bin/env python3
"""Product evidence search — Archive.org, YouTube, Reddit, Wayback Machine."""

from __future__ import annotations

import json
import os
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)


def _fetch_json(url: str, timeout: int = 20) -> dict[str, Any]:
    """Fetch JSON from URL with rate limiting."""
    time.sleep(1.0)  # Rate limit
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as e:
        print(f"Fetch error: {e}")
        return {}


def search_archive_org(
    query: str,
    mediatype: str = "texts",
    max_results: int = 20,
) -> list[dict[str, str]]:
    """
    Search Archive.org for product manuals, catalogs, technical documents.
    
    Args:
        query: Search query (e.g., "blender manual offset blade")
        mediatype: Type of media (texts, movies, audio, etc.)
        max_results: Maximum number of results to return
    
    Returns:
        List of dicts with keys: title, identifier, url, description, year
    """
    # Archive.org Advanced Search API
    # https://archive.org/advancedsearch.php
    q = urllib.parse.quote(query)
    fields = "identifier,title,description,year,downloads"
    url = (
        f"https://archive.org/advancedsearch.php?"
        f"q={q}&fl={fields}&rows={max_results}&page=1"
        f"&output=json&mediatype={mediatype}"
    )
    
    data = _fetch_json(url)
    if not data or "response" not in data:
        return []
    
    results = []
    for doc in data["response"].get("docs", []):
        identifier = doc.get("identifier", "")
        if not identifier:
            continue
        
        results.append({
            "title": doc.get("title", "Unknown"),
            "identifier": identifier,
            "url": f"https://archive.org/details/{identifier}",
            "description": doc.get("description", "")[:200],
            "year": str(doc.get("year", "unknown")),
            "downloads": doc.get("downloads", 0),
        })
    
    return results


def search_youtube(
    query: str,
    before_date: str | None = None,
    max_results: int = 10,
) -> list[dict[str, str]]:
    """
    Search YouTube for teardown/repair videos (requires API key).
    
    Args:
        query: Search query (e.g., "blender teardown repair")
        before_date: ISO date string (YYYY-MM-DD) for publishedBefore filter
        max_results: Maximum number of results
    
    Returns:
        List of dicts with keys: title, video_id, url, channel, published_date
    
    Note: Requires YOUTUBE_API_KEY environment variable.
    """
    import os
    
    api_key = os.environ.get("YOUTUBE_API_KEY")
    if not api_key:
        print("YouTube search requires YOUTUBE_API_KEY environment variable")
        return []
    
    q = urllib.parse.quote(query)
    url = (
        f"https://www.googleapis.com/youtube/v3/search?"
        f"part=snippet&q={q}&type=video&maxResults={max_results}&key={api_key}"
    )
    
    if before_date:
        # Convert YYYY-MM-DD to RFC 3339 format
        url += f"&publishedBefore={before_date}T23:59:59Z"
    
    data = _fetch_json(url)
    if not data or "items" not in data:
        return []
    
    results = []
    for item in data.get("items", []):
        video_id = item.get("id", {}).get("videoId", "")
        if not video_id:
            continue
        
        snippet = item.get("snippet", {})
        results.append({
            "title": snippet.get("title", "Unknown"),
            "video_id": video_id,
            "url": f"https://www.youtube.com/watch?v={video_id}",
            "channel": snippet.get("channelTitle", "Unknown"),
            "published_date": snippet.get("publishedAt", "")[:10],
            "description": snippet.get("description", "")[:200],
        })
    
    return results


def search_reddit(
    query: str,
    subreddit: str | None = None,
    before_timestamp: int | None = None,
    max_results: int = 25,
) -> list[dict[str, str]]:
    """
    Search Reddit using Pushshift API for product discussions.
    
    Args:
        query: Search query (e.g., "blender blade offset")
        subreddit: Specific subreddit to search (e.g., "BuyItForLife")
        before_timestamp: Unix timestamp for posts before this date
        max_results: Maximum number of results
    
    Returns:
        List of dicts with keys: title, url, author, created_date, score, subreddit
    """
    # Pushshift Reddit Search API
    q = urllib.parse.quote(query)
    url = f"https://api.pushshift.io/reddit/search/submission/?q={q}&size={max_results}"
    
    if subreddit:
        url += f"&subreddit={subreddit}"
    
    if before_timestamp:
        url += f"&before={before_timestamp}"
    
    data = _fetch_json(url, timeout=30)
    if not data or "data" not in data:
        return []
    
    results = []
    for post in data.get("data", []):
        post_id = post.get("id", "")
        if not post_id:
            continue
        
        results.append({
            "title": post.get("title", "Unknown"),
            "url": f"https://reddit.com{post.get('permalink', '')}",
            "author": post.get("author", "unknown"),
            "created_date": time.strftime("%Y-%m-%d", time.gmtime(post.get("created_utc", 0))),
            "score": post.get("score", 0),
            "subreddit": post.get("subreddit", "unknown"),
            "selftext": post.get("selftext", "")[:200],
        })
    
    return results


def search_wayback_machine(
    url: str,
    from_date: str = "20100101",
    to_date: str = "20191231",
) -> list[dict[str, str]]:
    """
    Search Wayback Machine for archived versions of a URL.
    
    Args:
        url: URL to search for (e.g., "vitamix.com")
        from_date: Start date in YYYYMMDD format
        to_date: End date in YYYYMMDD format
    
    Returns:
        List of dicts with keys: timestamp, url, status_code
    """
    # Wayback Machine CDX API
    # https://github.com/internetarchive/wayback/tree/master/wayback-cdx-server
    encoded_url = urllib.parse.quote(url)
    api_url = (
        f"https://web.archive.org/cdx/search/cdx?"
        f"url={encoded_url}&from={from_date}&to={to_date}"
        f"&output=json&limit=50&filter=statuscode:200"
    )
    
    try:
        req = urllib.request.Request(api_url, headers={"User-Agent": USER_AGENT})
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as e:
        print(f"Wayback fetch error: {e}")
        return []
    
    if not data or len(data) < 2:
        return []
    
    # First row is headers
    headers = data[0]
    results = []
    
    for row in data[1:]:
        if len(row) < 3:
            continue
        
        timestamp = row[1]  # YYYYMMDDHHMMSS format
        original_url = row[2]
        status_code = row[4] if len(row) > 4 else "200"
        
        # Format timestamp as YYYY-MM-DD
        date_str = f"{timestamp[:4]}-{timestamp[4:6]}-{timestamp[6:8]}"
        
        results.append({
            "timestamp": timestamp,
            "date": date_str,
            "url": f"https://web.archive.org/web/{timestamp}/{original_url}",
            "original_url": original_url,
            "status_code": status_code,
        })
    
    return results


def search_product_evidence(
    product_keywords: list[str],
    technical_terms: list[str],
    before_date: str,
    max_per_source: int = 10,
    log_fn: callable = None,
) -> dict[str, list[dict[str, str]]]:
    """
    Search multiple sources for product evidence.
    
    Args:
        product_keywords: Product names/types (e.g., ["blender", "food processor"])
        technical_terms: Technical features (e.g., ["offset blade", "eccentric rotor"])
        before_date: Critical date in YYYY-MM-DD format
        max_per_source: Max results per source
        log_fn: Optional logging function (msg, level) for real-time updates
    
    Returns:
        Dict with keys: archive_org, youtube, reddit, wayback, wikipedia, google, bing, duckduckgo, semantic_scholar, openalex, musicbrainz, discogs
    """
    import os
    
    def _log(msg: str, level: str = "info"):
        if log_fn:
            log_fn(msg, level)
        else:
            print(msg)
    
    results = {
        "archive_org": [],
        "youtube": [],
        "reddit": [],
        "wayback": [],
        "wikipedia": [],
        "google": [],
        "bing": [],
        "duckduckgo": [],
        "semantic_scholar": [],
        "openalex": [],
        "musicbrainz": [],
        "discogs": [],
    }
    
    # Build search queries
    queries = []
    for product in product_keywords[:3]:  # Limit to avoid too many queries
        for term in technical_terms[:3]:
            queries.append(f"{product} {term}")
    
    # Archive.org search
    _log("  -> Searching Archive.org for product manuals...")
    for query in queries[:5]:  # Limit queries
        hits = search_archive_org(
            f"{query} manual catalog datasheet",
            mediatype="texts",
            max_results=max_per_source,
        )
        results["archive_org"].extend(hits)
        if len(results["archive_org"]) >= max_per_source * 2:
            break
    
    # YouTube search (if API key available)
    _log("  -> Searching YouTube for teardown videos...")
    for query in queries[:3]:
        hits = search_youtube(
            f"{query} teardown repair disassembly",
            before_date=before_date,
            max_results=max_per_source,
        )
        results["youtube"].extend(hits)
        if len(results["youtube"]) >= max_per_source * 2:
            break
    _log(f"  [+] Found {len(results['youtube'])} YouTube results")
    
    # Reddit search
    _log("  -> Searching Reddit for product discussions...")
    before_ts = int(time.mktime(time.strptime(before_date, "%Y-%m-%d")))
    for query in queries[:3]:
        hits = search_reddit(
            query,
            subreddit=None,  # Search all subreddits
            before_timestamp=before_ts,
            max_results=max_per_source,
        )
        results["reddit"].extend(hits)
        if len(results["reddit"]) >= max_per_source * 2:
            break
    
    # Wayback Machine search for manufacturer sites
    _log("  -> Searching Wayback Machine for archived product pages...")
    manufacturer_domains = [
        "vitamix.com",
        "blendtec.com",
        "ninja.com",
        "cuisinart.com",
        "kitchenaid.com",
        "oster.com",
        "hamilton-beach.com",
    ]
    
    to_date = before_date.replace("-", "")
    for domain in manufacturer_domains[:5]:
        hits = search_wayback_machine(
            domain,
            from_date="20100101",
            to_date=to_date,
        )
        results["wayback"].extend(hits)
        if len(results["wayback"]) >= max_per_source * 3:
            break
    
    # Wikipedia search
    _log("  -> Searching Wikipedia for technical articles...")
    for query in queries[:3]:
        hits = search_wikipedia(query, max_results=max_per_source)
        results["wikipedia"].extend(hits)
        if len(results["wikipedia"]) >= max_per_source * 2:
            break
    _log(f"  [+] Found {len(results['wikipedia'])} Wikipedia results")
    
    # Google Custom Search (if API key available)
    google_api_key = os.environ.get("GOOGLE_API_KEY")
    google_search_id = os.environ.get("GOOGLE_SEARCH_ENGINE_ID")
    if google_api_key and google_search_id:
        _log("  -> Searching Google Custom Search...")
        # Half queries for web-wide search
        for query in queries[:2]:
            hits = search_google_custom(
                query,
                api_key=google_api_key,
                search_engine_id=google_search_id,
                site_restrict=None,
                max_results=5,
            )
            results["google"].extend(hits)
        
        # Half queries for domain-specific search
        for domain in manufacturer_domains[:2]:
            for query in queries[:1]:
                hits = search_google_custom(
                    query,
                    api_key=google_api_key,
                    search_engine_id=google_search_id,
                    site_restrict=domain,
                    max_results=5,
                )
                results["google"].extend(hits)
    
    # Bing Search (if API key available)
    bing_api_key = os.environ.get("BING_API_KEY")
    if bing_api_key:
        _log("  -> Searching Bing...")
        for query in queries[:3]:
            hits = search_bing(query, api_key=bing_api_key, max_results=max_per_source)
            results["bing"].extend(hits)
            if len(results["bing"]) >= max_per_source * 2:
                break
        _log(f"  [+] Found {len(results['bing'])} Bing results")
    
    # DuckDuckGo search (no API key needed)
    _log("  -> Searching DuckDuckGo...")
    for query in queries[:3]:
        hits = search_duckduckgo(query, max_results=max_per_source)
        results["duckduckgo"].extend(hits)
        if len(results["duckduckgo"]) >= max_per_source * 2:
            break
    _log(f"  [+] Found {len(results['duckduckgo'])} DuckDuckGo results")
    
    # Semantic Scholar (academic papers)
    _log("  -> Searching Semantic Scholar for academic papers...")
    before_year = int(before_date[:4])
    for query in queries[:3]:
        hits = search_semantic_scholar(query, before_year=before_year, max_results=max_per_source)
        results["semantic_scholar"].extend(hits)
        if len(results["semantic_scholar"]) >= max_per_source * 2:
            break
    _log(f"  [+] Found {len(results['semantic_scholar'])} Semantic Scholar results")
    
    # OpenAlex (academic papers - better coverage)
    _log("  -> Searching OpenAlex for academic papers...")
    for query in queries[:3]:
        hits = search_openalex(query, before_date=before_date, max_results=max_per_source)
        results["openalex"].extend(hits)
        if len(results["openalex"]) >= max_per_source * 2:
            break
    _log(f"  [+] Found {len(results['openalex'])} OpenAlex results")
    
    # MusicBrainz (recordings - perfect for hymns, no API key needed)
    _log("  -> Searching MusicBrainz for recordings...")
    for query in queries[:3]:
        hits = search_musicbrainz(query, before_date=before_date, max_results=max_per_source)
        results["musicbrainz"].extend(hits)
        if len(results["musicbrainz"]) >= max_per_source * 2:
            break
    _log(f"  [+] Found {len(results['musicbrainz'])} MusicBrainz results")
    
    # Discogs (album releases - if API key available)
    discogs_api_key = os.environ.get("DISCOGS_API_KEY")
    if discogs_api_key:
        _log("  -> Searching Discogs for album releases...")
        before_year = int(before_date[:4])
        for query in queries[:3]:
            hits = search_discogs(query, before_year=before_year, max_results=max_per_source)
            results["discogs"].extend(hits)
            if len(results["discogs"]) >= max_per_source * 2:
                break
        _log(f"  [+] Found {len(results['discogs'])} Discogs results")

    
    return results


def search_wikipedia(
    query: str,
    max_results: int = 5,
) -> list[dict[str, str]]:
    """
    Search Wikipedia and extract references + revision history.
    
    Args:
        query: Search query (e.g., "blender blade design")
        max_results: Maximum number of articles to return
    
    Returns:
        List of dicts with keys: title, url, summary, references, last_edited
    """
    # Wikipedia API search
    search_url = (
        f"https://en.wikipedia.org/w/api.php?"
        f"action=query&list=search&srsearch={urllib.parse.quote(query)}"
        f"&format=json&srlimit={max_results}"
    )
    
    data = _fetch_json(search_url)
    if not data or "query" not in data:
        return []
    
    results = []
    for item in data["query"].get("search", []):
        page_id = item.get("pageid")
        title = item.get("title", "Unknown")
        
        # Get page content and references
        content_url = (
            f"https://en.wikipedia.org/w/api.php?"
            f"action=query&pageids={page_id}&prop=extracts|info|revisions"
            f"&exintro=1&explaintext=1&inprop=url&rvprop=timestamp&format=json"
        )
        
        page_data = _fetch_json(content_url)
        if not page_data or "query" not in page_data:
            continue
        
        pages = page_data["query"].get("pages", {})
        page_info = pages.get(str(page_id), {})
        
        results.append({
            "title": title,
            "url": page_info.get("fullurl", f"https://en.wikipedia.org/wiki/{title.replace(' ', '_')}"),
            "summary": page_info.get("extract", "")[:300],
            "last_edited": page_info.get("revisions", [{}])[0].get("timestamp", "unknown")[:10] if page_info.get("revisions") else "unknown",
            "page_id": page_id,
        })
    
    return results


def search_google_custom(
    query: str,
    api_key: str,
    search_engine_id: str,
    site_restrict: str | None = None,
    max_results: int = 10,
) -> list[dict[str, str]]:
    """
    Search using Google Custom Search API.
    
    Args:
        query: Search query
        api_key: Google API key
        search_engine_id: Custom Search Engine ID
        site_restrict: Optional domain to restrict (e.g., "vitamix.com")
        max_results: Maximum results (max 10 per query)
    
    Returns:
        List of dicts with keys: title, url, snippet, display_url
    """
    if not api_key or not search_engine_id:
        print("Google Custom Search requires API_KEY and SEARCH_ENGINE_ID")
        return []
    
    q = urllib.parse.quote(query)
    url = (
        f"https://www.googleapis.com/customsearch/v1?"
        f"key={api_key}&cx={search_engine_id}&q={q}&num={min(max_results, 10)}"
    )
    
    if site_restrict:
        url += f"&siteSearch={site_restrict}&siteSearchFilter=i"
    
    data = _fetch_json(url)
    if not data or "items" not in data:
        return []
    
    results = []
    for item in data.get("items", []):
        results.append({
            "title": item.get("title", "Unknown"),
            "url": item.get("link", ""),
            "snippet": item.get("snippet", "")[:200],
            "display_url": item.get("displayLink", ""),
        })
    
    return results


def search_bing(
    query: str,
    api_key: str,
    max_results: int = 10,
) -> list[dict[str, str]]:
    """
    Search using Bing Search API.
    
    Args:
        query: Search query
        api_key: Bing API key
        max_results: Maximum results
    
    Returns:
        List of dicts with keys: title, url, snippet
    """
    if not api_key:
        print("Bing Search requires BING_API_KEY")
        return []
    
    url = f"https://api.bing.microsoft.com/v7.0/search?q={urllib.parse.quote(query)}&count={max_results}"
    
    try:
        req = urllib.request.Request(url, headers={
            "Ocp-Apim-Subscription-Key": api_key,
            "User-Agent": USER_AGENT
        })
        with urllib.request.urlopen(req, timeout=20) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as e:
        print(f"Bing fetch error: {e}")
        return []
    
    results = []
    for item in data.get("webPages", {}).get("value", []):
        results.append({
            "title": item.get("name", "Unknown"),
            "url": item.get("url", ""),
            "snippet": item.get("snippet", "")[:200],
        })
    
    return results


def search_duckduckgo(
    query: str,
    max_results: int = 10,
) -> list[dict[str, str]]:
    """
    Search using DuckDuckGo Instant Answer API (limited results).
    
    Args:
        query: Search query
        max_results: Maximum results (DuckDuckGo returns limited results)
    
    Returns:
        List of dicts with keys: title, url, snippet
    """
    url = f"https://api.duckduckgo.com/?q={urllib.parse.quote(query)}&format=json"
    
    data = _fetch_json(url)
    if not data:
        return []
    
    results = []
    
    # Abstract (main result)
    if data.get("Abstract"):
        results.append({
            "title": data.get("Heading", "DuckDuckGo Result"),
            "url": data.get("AbstractURL", ""),
            "snippet": data.get("Abstract", "")[:200],
        })
    
    # Related topics
    for topic in data.get("RelatedTopics", [])[:max_results]:
        if isinstance(topic, dict) and "Text" in topic:
            results.append({
                "title": topic.get("Text", "")[:100],
                "url": topic.get("FirstURL", ""),
                "snippet": topic.get("Text", "")[:200],
            })
    
    return results[:max_results]


def search_semantic_scholar(
    query: str,
    before_year: int | None = None,
    max_results: int = 10,
) -> list[dict[str, str]]:
    """
    Search Semantic Scholar for academic papers.
    
    Args:
        query: Search query
        before_year: Only papers published before this year
        max_results: Maximum results
    
    Returns:
        List of dicts with keys: title, url, authors, year, doi, abstract
    """
    url = (
        f"https://api.semanticscholar.org/graph/v1/paper/search?"
        f"query={urllib.parse.quote(query)}&limit={max_results}"
        f"&fields=title,authors,year,abstract,externalIds,url"
    )
    
    if before_year:
        url += f"&year=-{before_year}"
    
    data = _fetch_json(url)
    if not data or "data" not in data:
        return []
    
    results = []
    for paper in data.get("data", []):
        authors = ", ".join(a.get("name", "") for a in paper.get("authors", [])[:3])
        if len(paper.get("authors", [])) > 3:
            authors += " et al."
        
        results.append({
            "title": paper.get("title", "Unknown"),
            "url": paper.get("url", ""),
            "authors": authors,
            "year": str(paper.get("year", "unknown")),
            "doi": paper.get("externalIds", {}).get("DOI", ""),
            "abstract": paper.get("abstract", "")[:300],
        })
    
    return results


def search_openalex(
    query: str,
    before_date: str | None = None,
    max_results: int = 10,
) -> list[dict[str, str]]:
    """
    Search OpenAlex for academic papers (better coverage than Crossref).
    
    Args:
        query: Search query
        before_date: ISO date string (YYYY-MM-DD)
        max_results: Maximum results
    
    Returns:
        List of dicts with keys: title, url, authors, date, doi, abstract
    """
    url = (
        f"https://api.openalex.org/works?"
        f"search={urllib.parse.quote(query)}&per-page={max_results}"
    )
    
    if before_date:
        url += f"&filter=publication_date:<{before_date}"
    
    # OpenAlex requires email in User-Agent
    headers = {
        "User-Agent": f"{USER_AGENT}; mailto:research@example.com"
    }
    
    try:
        req = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(req, timeout=20) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as e:
        print(f"OpenAlex fetch error: {e}")
        return []
    
    results = []
    for work in data.get("results", []):
        authors = ", ".join(
            a.get("author", {}).get("display_name", "")
            for a in work.get("authorships", [])[:3]
        )
        if len(work.get("authorships", [])) > 3:
            authors += " et al."
        
        results.append({
            "title": work.get("title") or "Unknown",

            "url": work.get("doi", "") or work.get("id", ""),
            "authors": authors,
            "date": work.get("publication_date", "unknown"),
            "doi": work.get("doi", "").replace("https://doi.org/", ""),
            "abstract": (work.get("abstract_inverted_index") or {}).get("abstract", "")[:300] if work.get("abstract_inverted_index") else "",
        })
    
    return results


def search_musicbrainz(
    query: str,
    before_date: str | None = None,
    max_results: int = 10,
) -> list[dict[str, str]]:
    """
    Search MusicBrainz for recordings (perfect for hymns, no API key needed).
    
    Args:
        query: Search query (e.g., "Amazing Grace Cebuano")
        before_date: ISO date string (YYYY-MM-DD) for release date filter
        max_results: Maximum results
    
    Returns:
        List of dicts with keys: title, artist, url, release_date, recording_id
    """
    # MusicBrainz API: https://musicbrainz.org/doc/MusicBrainz_API
    q = urllib.parse.quote(query)
    url = f"https://musicbrainz.org/ws/2/recording/?query={q}&limit={max_results}&fmt=json"
    
    headers = {
        "User-Agent": f"{USER_AGENT}; mailto:research@example.com"
    }
    
    try:
        req = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(req, timeout=20) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as e:
        print(f"MusicBrainz fetch error: {e}")
        return []
    
    results = []
    for recording in data.get("recordings", []):
        # Get first release date
        releases = recording.get("releases", [])
        if not releases:
            continue
        
        release_date = releases[0].get("date", "unknown")
        
        # Filter by date if specified
        if before_date and release_date != "unknown":
            try:
                if release_date > before_date:
                    continue
            except:
                pass
        
        # Get artist name
        artist_credit = recording.get("artist-credit", [])
        artist = artist_credit[0].get("name", "Unknown") if artist_credit else "Unknown"
        
        recording_id = recording.get("id", "")
        
        results.append({
            "title": recording.get("title", "Unknown"),
            "artist": artist,
            "url": f"https://musicbrainz.org/recording/{recording_id}",
            "release_date": release_date,
            "recording_id": recording_id,
        })
    
    return results


def search_discogs(
    query: str,
    before_year: int | None = None,
    max_results: int = 10,
) -> list[dict[str, str]]:
    """
    Search Discogs for album releases (requires DISCOGS_API_KEY).
    
    Args:
        query: Search query (e.g., "Amazing Grace hymnal")
        before_year: Filter releases before this year
        max_results: Maximum results
    
    Returns:
        List of dicts with keys: title, artist, url, year, format, label
    """
    api_key = os.environ.get("DISCOGS_API_KEY")
    if not api_key:
        print("Discogs search requires DISCOGS_API_KEY environment variable")
        return []
    
    # Discogs API: https://www.discogs.com/developers
    q = urllib.parse.quote(query)
    url = f"https://api.discogs.com/database/search?q={q}&type=release&per_page={max_results}"
    
    headers = {
        "User-Agent": USER_AGENT,
        "Authorization": f"Discogs token={api_key}"
    }
    
    try:
        req = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(req, timeout=20) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as e:
        print(f"Discogs fetch error: {e}")
        return []
    
    results = []
    for release in data.get("results", []):
        year = release.get("year", "")
        
        # Filter by year if specified
        if before_year and year:
            try:
                if int(year) >= before_year:
                    continue
            except:
                pass
        
        results.append({
            "title": release.get("title", "Unknown"),
            "artist": ", ".join(release.get("artist", [])) if isinstance(release.get("artist"), list) else release.get("artist", "Unknown"),
            "url": release.get("uri", ""),
            "year": str(year) if year else "unknown",
            "format": ", ".join(release.get("format", [])) if release.get("format") else "Unknown",
            "label": ", ".join(release.get("label", [])) if release.get("label") else "Unknown",
        })
    
    return results


    # Test searches
    print("Testing Archive.org search...")
    archive_results = search_archive_org("blender manual offset blade", max_results=5)
    print(f"Found {len(archive_results)} Archive.org results")
    for r in archive_results[:2]:
        print(f"  - {r['title']} ({r['year']}): {r['url']}")
    
    print("\nTesting Wikipedia search...")
    wiki_results = search_wikipedia("blender", max_results=3)
    print(f"Found {len(wiki_results)} Wikipedia results")
    for r in wiki_results[:2]:
        print(f"  - {r['title']}: {r['url']}")
    
    print("\nTesting DuckDuckGo search...")
    ddg_results = search_duckduckgo("blender blade offset", max_results=5)
    print(f"Found {len(ddg_results)} DuckDuckGo results")
    for r in ddg_results[:2]:
        print(f"  - {r['title']}: {r['url']}")
    
    print("\nTesting Semantic Scholar search...")
    ss_results = search_semantic_scholar("blender mixing efficiency", before_year=2020, max_results=5)
    print(f"Found {len(ss_results)} Semantic Scholar results")
    for r in ss_results[:2]:
        print(f"  - {r['title']} ({r['year']})")
    
    print("\nTesting OpenAlex search...")
    oa_results = search_openalex("blender vortex mixing", before_date="2020-01-01", max_results=5)
    print(f"Found {len(oa_results)} OpenAlex results")
    for r in oa_results[:2]:
        print(f"  - {r['title']} ({r['date']})")
