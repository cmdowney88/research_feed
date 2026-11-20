"""Fetch abstracts from the arXiv API for papers whose S2 record lacks one."""

import re
import sys
import time
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ElementTree

ARXIV_API_URL = "https://export.arxiv.org/api/query"
ATOM_NAMESPACE = {"atom": "http://www.w3.org/2005/Atom"}


def fetch_abstracts(
    arxiv_ids: list[str],
    batch_size: int = 50,
    pause_seconds: float = 3.0,
) -> dict[str, str]:
    """Return {arxiv_id: abstract} for the given IDs, querying arXiv in batches.

    arXiv asks clients to wait about 3 seconds between requests; IDs that fail to resolve are
    simply missing from the result.
    """
    abstracts = {}
    for start in range(0, len(arxiv_ids), batch_size):
        batch = arxiv_ids[start : start + batch_size]
        query = urllib.parse.urlencode({"id_list": ",".join(batch), "max_results": len(batch)})
        try:
            with urllib.request.urlopen(f"{ARXIV_API_URL}?{query}", timeout=60) as response:
                root = ElementTree.fromstring(response.read())
        except OSError as error:
            print(f"arXiv request failed: {error}", file=sys.stderr)
            continue
        for entry in root.findall("atom:entry", ATOM_NAMESPACE):
            entry_id = entry.findtext("atom:id", default="", namespaces=ATOM_NAMESPACE)
            summary = entry.findtext("atom:summary", default="", namespaces=ATOM_NAMESPACE)
            # strip URL prefix and version from IDs like http://arxiv.org/abs/2510.22492v2
            arxiv_id = re.sub(r"v\d+$", "", entry_id.split("/abs/")[-1])
            if summary.strip():
                abstracts[arxiv_id] = " ".join(summary.split())
        time.sleep(pause_seconds)
    return abstracts
