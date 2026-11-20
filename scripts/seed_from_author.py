"""Rank the papers an author has cited, to bootstrap recommendation seed lists.

Each reference gets a score summed over the author's papers that cite it:

    score = sum over citing papers p of recency(p) * role(p) * strength(p, ref)

where `recency` halves every `--half-life` years before the newest paper, `role` is 1.0 when
the author is first or last author and `--middle-author-weight` otherwise, and `strength` is
1 + 1 if S2 marks the citation influential + 0.25 per citation context (capped at 4 contexts).

Writes `seeds/candidates.tsv` (ranked references) and `seeds/citing_me.tsv` (papers citing the
author's work, newest first).

Example:
    python scripts/seed_from_author.py --author-id <S2 author ID> --exclude <paper ID prefix>
"""

import argparse
import csv
import sys
from collections import defaultdict
from pathlib import Path

from litfeed.paths import DATA_ROOT
from litfeed.s2 import S2Client
from litfeed.scoring import author_role_weight, citation_strength, recency_weight


REFERENCE_FIELDS = "title,year,venue,externalIds,contexts,isInfluential"
CITATION_FIELDS = "title,year,venue,externalIds,authors"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--author-id", required=True)
    parser.add_argument(
        "--exclude",
        nargs="*",
        default=[],
        help="paperId prefixes of misattributed papers to skip",
    )
    parser.add_argument("--half-life", type=float, default=3.0)
    parser.add_argument("--middle-author-weight", type=float, default=0.5)
    parser.add_argument("--output-dir", type=Path, default=DATA_ROOT / "seeds")
    args = parser.parse_args()

    client = S2Client()
    papers = client.get_all(
        f"/author/{args.author_id}/papers",
        fields="title,year,authors",
    )
    papers = [
        paper
        for paper in papers
        if not any(paper["paperId"].startswith(prefix) for prefix in args.exclude)
    ]
    own_paper_ids = {paper["paperId"] for paper in papers}
    newest_year = max(paper["year"] or 0 for paper in papers)

    scores: dict[str, float] = defaultdict(float)
    cited_by: dict[str, list[str]] = defaultdict(list)
    influential_count: dict[str, int] = defaultdict(int)
    metadata: dict[str, dict] = {}
    citing_me: dict[str, dict] = {}

    for paper in papers:
        print(f"{paper['year']}  {paper['title'][:80]}", file=sys.stderr)
        recency = recency_weight(paper["year"], newest_year, args.half_life)
        role = author_role_weight(paper, args.author_id, args.middle_author_weight)

        references = client.get_all(
            f"/paper/{paper['paperId']}/references",
            fields=REFERENCE_FIELDS,
            page_size=1000,
        )
        for reference in references:
            cited = reference.get("citedPaper") or {}
            cited_id = cited.get("paperId")
            if not cited_id:
                continue
            scores[cited_id] += recency * role * citation_strength(reference)
            cited_by[cited_id].append(str(paper["year"]))
            if reference.get("isInfluential"):
                influential_count[cited_id] += 1
            metadata[cited_id] = cited

        citations = client.get_all(
            f"/paper/{paper['paperId']}/citations",
            fields=CITATION_FIELDS,
            page_size=1000,
        )
        for citation in citations:
            citing = citation.get("citingPaper") or {}
            citing_id = citing.get("paperId")
            if citing_id and citing_id not in own_paper_ids:
                entry = citing_me.setdefault(citing_id, {**citing, "cites": []})
                entry["cites"].append(paper["title"][:40])

    args.output_dir.mkdir(parents=True, exist_ok=True)

    candidates_path = args.output_dir / "candidates.tsv"
    ranked_ids = sorted(scores, key=lambda paper_id: -scores[paper_id])
    with candidates_path.open("w", newline="") as handle:
        writer = csv.writer(handle, delimiter="\t")
        writer.writerow(
            ["score", "n_cited_in", "n_influential", "year", "paperId", "arxiv", "self", "title"]
        )
        for paper_id in ranked_ids:
            cited = metadata[paper_id]
            writer.writerow(
                [
                    f"{scores[paper_id]:.3f}",
                    len(cited_by[paper_id]),
                    influential_count[paper_id],
                    cited.get("year") or "",
                    paper_id,
                    (cited.get("externalIds") or {}).get("ArXiv", ""),
                    "self" if paper_id in own_paper_ids else "",
                    cited.get("title") or "",
                ]
            )

    citing_path = args.output_dir / "citing_me.tsv"
    citing_sorted = sorted(citing_me.values(), key=lambda paper: -(paper.get("year") or 0))
    with citing_path.open("w", newline="") as handle:
        writer = csv.writer(handle, delimiter="\t")
        writer.writerow(["year", "paperId", "arxiv", "cites", "title"])
        for paper in citing_sorted:
            writer.writerow(
                [
                    paper.get("year") or "",
                    paper["paperId"],
                    (paper.get("externalIds") or {}).get("ArXiv", ""),
                    "; ".join(paper["cites"]),
                    paper.get("title") or "",
                ]
            )

    print(f"{len(ranked_ids)} cited papers -> {candidates_path}")
    print(f"{len(citing_me)} citing papers -> {citing_path}")


if __name__ == "__main__":
    main()
