"""Minimal Semantic Scholar API client (Graph + Recommendations) with an on-disk cache.

Uses only the standard library. The API key is read from the `S2_API_KEY` environment
variable, falling back to a `S2_API_KEY=...` line in the data directory's `.env` file. Without a
key, requests share the public rate-limited pool, so requests are throttled and retried on HTTP 429.

Static lookups (an old paper's references, an author's paper list) are cached forever. Queries
whose answer changes over time (recommendations, new citations) should pass `use_cache=False`.
"""

import hashlib
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

from litfeed.paths import DATA_ROOT

GRAPH_URL = "https://api.semanticscholar.org/graph/v1"
RECOMMENDATIONS_URL = "https://api.semanticscholar.org/recommendations/v1"
DEFAULT_CACHE_DIR = DATA_ROOT / "cache" / "s2"
MAX_BACKOFF_SECONDS = 60


def load_api_key(env_path: Path = DATA_ROOT / ".env") -> str | None:
    """Return `S2_API_KEY` from the environment, else from a `.env` file, else None."""
    api_key = os.environ.get("S2_API_KEY")
    if api_key:
        return api_key
    if not env_path.exists():
        return None
    for line in env_path.read_text().splitlines():
        key, separator, value = line.partition("=")
        if separator and key.strip() == "S2_API_KEY":
            return value.strip().strip("\"'")
    return None


class S2Client:
    """Thin wrapper around the S2 Graph and Recommendations APIs.

    Args:
        cache_dir: Directory for cached JSON responses, keyed by request URL and body.
        min_interval: Minimum seconds between network requests.
        max_retries: Number of retries on HTTP 429 / 5xx before giving up.
    """

    def __init__(
        self,
        cache_dir: Path = DEFAULT_CACHE_DIR,
        min_interval: float = 1.1,
        max_retries: int = 10,
    ) -> None:
        self.cache_dir = cache_dir
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.min_interval = min_interval
        self.max_retries = max_retries
        self.api_key = load_api_key()
        self._last_request_time = 0.0

    def _request(
        self,
        url: str,
        body: dict | None,
        use_cache: bool,
    ) -> dict:
        """Send a GET (no body) or POST (JSON body) request, with caching and retries."""
        encoded_body = json.dumps(body, sort_keys=True).encode() if body is not None else None
        cache_key = url.encode() + (encoded_body or b"")
        cache_path = self.cache_dir / (hashlib.sha256(cache_key).hexdigest() + ".json")
        if use_cache and cache_path.exists():
            return json.loads(cache_path.read_text())

        for attempt in range(self.max_retries + 1):
            # throttle network requests
            wait_time = self.min_interval - (time.time() - self._last_request_time)
            if wait_time > 0:
                time.sleep(wait_time)
            self._last_request_time = time.time()

            request = urllib.request.Request(url, data=encoded_body)
            if encoded_body is not None:
                request.add_header("Content-Type", "application/json")
            if self.api_key:
                request.add_header("x-api-key", self.api_key)
            try:
                with urllib.request.urlopen(request, timeout=60) as response:
                    payload = json.loads(response.read())
                cache_path.write_text(json.dumps(payload))
                return payload
            except urllib.error.HTTPError as error:
                retryable = error.code == 429 or error.code >= 500
                if not retryable or attempt == self.max_retries:
                    detail = error.read().decode(errors="replace")[:500]
                    print(f"HTTP {error.code} on {url}: {detail}", file=sys.stderr)
                    raise
                # honor Retry-After when S2 sends one; otherwise back off exponentially
                retry_after = error.headers.get("Retry-After", "")
                backoff = min(2 ** (attempt + 1), MAX_BACKOFF_SECONDS)
                if retry_after.isdigit():
                    backoff = min(int(retry_after), MAX_BACKOFF_SECONDS)
                print(f"HTTP {error.code}; retrying in {backoff}s", file=sys.stderr)
                time.sleep(backoff)
        raise RuntimeError("unreachable")

    def get(
        self,
        path: str,
        params: dict[str, str | int] | None = None,
        use_cache: bool = True,
    ) -> dict:
        """GET `GRAPH_URL + path` with query `params`."""
        query = urllib.parse.urlencode(params or {})
        return self._request(f"{GRAPH_URL}{path}?{query}", body=None, use_cache=use_cache)

    def get_all(
        self,
        path: str,
        fields: str,
        page_size: int = 500,
        use_cache: bool = True,
    ) -> list[dict]:
        """Follow offset/next pagination and return the concatenated `data` lists."""
        results = []
        offset = 0
        while True:
            params = {"fields": fields, "limit": page_size, "offset": offset}
            page = self.get(path, params, use_cache=use_cache)
            # S2 sends "data": null for some papers (e.g. no listed references)
            results.extend(page.get("data") or [])
            if "next" not in page:
                return results
            offset = page["next"]

    def recommend(
        self,
        positive_ids: list[str],
        negative_ids: list[str],
        fields: str,
        limit: int = 100,
    ) -> list[dict]:
        """Return recommended papers for positive/negative seed lists (never cached).

        Uses POST /recommendations/v1/papers/, which (unlike the single-paper endpoint)
        takes no `from` pool parameter.
        """
        query = urllib.parse.urlencode({"fields": fields, "limit": limit})
        body = {"positivePaperIds": positive_ids, "negativePaperIds": negative_ids}
        payload = self._request(
            f"{RECOMMENDATIONS_URL}/papers/?{query}",
            body=body,
            use_cache=False,
        )
        return payload.get("recommendedPapers", [])

    def search(
        self,
        query: str,
        fields: str,
        limit: int = 50,
    ) -> list[dict]:
        """Relevance search over papers (cached; `limit` <= 100)."""
        payload = self.get("/paper/search", {"query": query, "fields": fields, "limit": limit})
        return payload.get("data") or []

    def snippet_search(
        self,
        query: str,
        limit: int = 30,
    ) -> list[dict]:
        """Full-text snippet search (cached). Results carry `paper.corpusId`, not `paperId`."""
        payload = self.get("/snippet/search", {"query": query, "limit": limit})
        return payload.get("data") or []

    def paper_batch(
        self,
        paper_ids: list[str],
        fields: str,
        keep_missing: bool = False,
    ) -> list[dict | None]:
        """Fetch details for up to 500 IDs per request (any S2-supported ID form, e.g.
        `CorpusId:123`). Unknown IDs are skipped, or kept as None (aligned with `paper_ids`)
        when `keep_missing` is set."""
        results = []
        for start in range(0, len(paper_ids), 500):
            chunk = paper_ids[start : start + 500]
            query = urllib.parse.urlencode({"fields": fields})
            payload = self._request(
                f"{GRAPH_URL}/paper/batch?{query}",
                body={"ids": chunk},
                use_cache=True,
            )
            results.extend(paper for paper in payload if paper or keep_missing)
        return results

    def recommend_for_paper(
        self,
        paper_id: str,
        fields: str,
        pool: str = "all-cs",
        limit: int = 30,
    ) -> list[dict]:
        """Recommendations for a single seed paper from the `recent` or `all-cs` pool."""
        query = urllib.parse.urlencode({"fields": fields, "limit": limit, "from": pool})
        payload = self._request(
            f"{RECOMMENDATIONS_URL}/papers/forpaper/{paper_id}?{query}",
            body=None,
            use_cache=True,
        )
        return payload.get("recommendedPapers", [])
