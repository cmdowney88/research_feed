"""Deep-dive literature search for a project, driven by `projects/<slug>/description.md`.

Stages (run in order; each reads and extends `projects/<slug>/candidates.jsonl`):

    search      plan queries (headless Claude) → S2 relevance + full-text snippet search →
                score relevance to the project → one citation-graph hop from `core` papers
                (keep papers that >= 2 core papers cite or are cited by) → score those →
                write `proposed_seeds.tsv`
    recommend   after the user copies/edits `proposed_seeds.tsv` to `seeds.tsv`: all-years
                recommendations for each seed (`forpaper`, `from=all-cs`) → score new papers
    notes       reading notes for the top `core` papers, framed by the project
    synthesize  `synthesis.md` (landscape, gaps, related-work outline) and `reading_list.md`

Relevance labels: core > related > background > irrelevant. All LLM calls are
`claude -p --bare` (billed to ANTHROPIC_API_KEY) and every S2 lookup is cached, so re-running a
stage is cheap.

Example:
    python scripts/deep_dive.py search my-project
"""

import argparse
import csv
import json
import sys
from collections import Counter
from concurrent.futures import ThreadPoolExecutor

from litfeed.candidates import merge_duplicates
from litfeed.llm import run_claude
from litfeed.notes import write_note
from litfeed.paths import DATA_ROOT, PROMPTS_DIR
from litfeed.s2 import S2Client

PROJECTS_DIR = DATA_ROOT / "projects"
PAPER_FIELDS = (
    "title,abstract,year,publicationDate,venue,authors,externalIds,citationCount,"
    "isOpenAccess,openAccessPdf"
)
LABEL_ORDER = {"core": 0, "related": 1, "background": 2, "irrelevant": 3}
MAX_ABSTRACT_CHARS = 1200

QUERY_SCHEMA = {
    "type": "object",
    "properties": {
        "queries": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "query": {"type": "string"},
                    "kind": {"type": "string", "enum": ["search", "snippet"]},
                    "aspect": {"type": "string"},
                },
                "required": ["query", "kind", "aspect"],
            },
        }
    },
    "required": ["queries"],
}

SCORE_SCHEMA = {
    "type": "object",
    "properties": {
        "items": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "paperId": {"type": "string"},
                    "relevance": {"type": "string", "enum": list(LABEL_ORDER)},
                    "aspect": {"type": "string"},
                    "why": {"type": "string"},
                },
                "required": ["paperId", "relevance", "aspect", "why"],
            },
        }
    },
    "required": ["items"],
}

SYNTHESIS_SCHEMA = {
    "type": "object",
    "properties": {"markdown": {"type": "string"}},
    "required": ["markdown"],
}


class Project:
    """Paths and candidate pool for one deep-dive project."""

    def __init__(self, slug: str) -> None:
        self.directory = PROJECTS_DIR / slug
        self.description = (self.directory / "description.md").read_text()
        self.candidates_path = self.directory / "candidates.jsonl"
        self.notes_dir = self.directory / "notes"

    def prompt(self, template_name: str) -> str:
        """Load a prompt template with the project description filled in."""
        template = (PROMPTS_DIR / template_name).read_text()
        return template.replace("{description}", self.description)

    def load_candidates(self) -> dict[str, dict]:
        if not self.candidates_path.exists():
            return {}
        with self.candidates_path.open() as handle:
            return {record["paperId"]: record for record in map(json.loads, handle)}

    def save_candidates(self, candidates: dict[str, dict]) -> None:
        with self.candidates_path.open("w") as handle:
            for record in candidates.values():
                handle.write(json.dumps(record, ensure_ascii=False) + "\n")


def new_record(paper: dict, source: str) -> dict:
    """Build a candidate record from an S2 paper dict."""
    return {
        "paperId": paper["paperId"],
        "title": paper.get("title"),
        "abstract": paper.get("abstract"),
        "year": paper.get("year"),
        "publicationDate": paper.get("publicationDate"),
        "venue": paper.get("venue"),
        "authors": [author.get("name") for author in paper.get("authors") or []],
        "externalIds": paper.get("externalIds") or {},
        "citationCount": paper.get("citationCount"),
        "openAccessPdf": paper.get("openAccessPdf"),
        "sources": [source],
        "feeds": {},
    }


def add_paper(
    candidates: dict[str, dict],
    paper: dict,
    source: str,
) -> None:
    """Add a paper to the pool, or record one more source that found it."""
    paper_id = paper.get("paperId")
    if not paper_id:
        return
    if paper_id in candidates:
        if source not in candidates[paper_id]["sources"]:
            candidates[paper_id]["sources"].append(source)
    else:
        candidates[paper_id] = new_record(paper, source)


def score_unscored(
    project: Project,
    candidates: dict[str, dict],
    model: str,
    batch_size: int = 25,
    workers: int = 4,
) -> None:
    """Label every candidate that has no `relevance` yet (in place)."""
    unscored = [record for record in candidates.values() if "relevance" not in record]
    if not unscored:
        return
    system_prompt = project.prompt("deepdive_score.md")

    def score_batch(batch: list[dict]) -> list[dict]:
        papers = []
        for record in batch:
            abstract = (record.get("abstract") or "")[:MAX_ABSTRACT_CHARS]
            papers.append(
                {
                    "paperId": record["paperId"],
                    "title": record.get("title"),
                    "year": record.get("year"),
                    "venue": record.get("venue"),
                    "abstract": abstract or None,
                    "snippet": record.get("snippet"),
                }
            )
        message = "Judge these papers:\n\n" + json.dumps(papers, ensure_ascii=False, indent=1)
        result = run_claude(system_prompt, message, SCORE_SCHEMA, model=model)
        if result.output is None:
            print(f"scoring batch failed: {result.error}", file=sys.stderr)
            return []
        print(f"  scored {len(batch)} (${result.cost_usd:.3f})", file=sys.stderr)
        return result.output["items"]

    batches = [
        unscored[start : start + batch_size] for start in range(0, len(unscored), batch_size)
    ]
    with ThreadPoolExecutor(max_workers=workers) as executor:
        for items in executor.map(score_batch, batches):
            for item in items:
                if item["paperId"] in candidates:
                    candidates[item["paperId"]].update(
                        relevance=item["relevance"], aspect=item["aspect"], why=item["why"]
                    )
    missing = sum(1 for record in candidates.values() if "relevance" not in record)
    if missing:
        print(f"WARNING: {missing} papers still unscored; rerun the stage", file=sys.stderr)


def rank_key(record: dict) -> tuple:
    """Order by label, then number of independent signals, then citation count."""
    return (
        LABEL_ORDER.get(record.get("relevance"), 9),
        -len(record.get("sources") or []),
        -(record.get("citationCount") or 0),
    )


def stage_search(project: Project, client: S2Client, model: str) -> None:
    queries_path = project.directory / "queries.json"
    if queries_path.exists():
        queries = json.loads(queries_path.read_text())
    else:
        result = run_claude(
            PROMPTS_DIR.joinpath("deepdive_queries.md").read_text(),
            project.description,
            QUERY_SCHEMA,
            model=model,
        )
        if result.output is None:
            sys.exit(f"query planning failed: {result.error}")
        queries = result.output["queries"]
        queries_path.write_text(json.dumps(queries, indent=1, ensure_ascii=False))
    print(f"{len(queries)} queries", file=sys.stderr)

    candidates = project.load_candidates()
    snippet_hits: dict[str, tuple[str, str]] = {}
    for query in queries:
        source = f"{query['kind']}: {query['query']}"
        if query["kind"] == "search":
            for paper in client.search(query["query"], PAPER_FIELDS, limit=50):
                add_paper(candidates, paper, source)
        else:
            for hit in client.snippet_search(query["query"], limit=30):
                corpus_id = (hit.get("paper") or {}).get("corpusId")
                text = (hit.get("snippet") or {}).get("text", "")
                if corpus_id and corpus_id not in snippet_hits:
                    snippet_hits[corpus_id] = (source, text[:600])
    if snippet_hits:
        resolved = client.paper_batch(
            [f"CorpusId:{corpus_id}" for corpus_id in snippet_hits],
            PAPER_FIELDS + ",corpusId",
        )
        for paper in resolved:
            source, text = snippet_hits[str(paper.get("corpusId"))]
            add_paper(candidates, paper, source)
            candidates[paper["paperId"]].setdefault("snippet", text)
    merged = merge_duplicates(list(candidates.values()))
    candidates = {record["paperId"]: record for record in merged}
    print(f"{len(candidates)} papers from search", file=sys.stderr)
    score_unscored(project, candidates, model)
    project.save_candidates(candidates)

    # one citation-graph hop from the strongest core papers
    core = sorted(
        (record for record in candidates.values() if record.get("relevance") == "core"),
        key=rank_key,
    )[:30]
    neighbor_counts: Counter = Counter()
    for record in core:
        references = client.get(
            f"/paper/{record['paperId']}/references",
            {"fields": "paperId", "limit": 1000},
        ).get("data") or []
        citations = client.get(
            f"/paper/{record['paperId']}/citations",
            {"fields": "paperId", "limit": 1000},
        ).get("data") or []
        neighbors = {
            (item.get("citedPaper") or item.get("citingPaper") or {}).get("paperId")
            for item in references + citations
        }
        neighbor_counts.update(neighbor for neighbor in neighbors if neighbor)
    expansion_ids = [
        paper_id
        for paper_id, count in neighbor_counts.most_common()
        if count >= 2 and paper_id not in candidates
    ][:150]
    print(
        f"citation hop: {len(expansion_ids)} new papers linked to >= 2 core papers",
        file=sys.stderr,
    )
    for paper in client.paper_batch(expansion_ids, PAPER_FIELDS):
        links = neighbor_counts[paper["paperId"]]
        add_paper(candidates, paper, f"citation graph ({links} core links)")
    score_unscored(project, candidates, model)
    project.save_candidates(candidates)
    write_proposed_seeds(project, candidates)


def write_proposed_seeds(project: Project, candidates: dict[str, dict]) -> None:
    """Write the ranked `core` papers as a seed list for the user to prune."""
    core = sorted(
        (record for record in candidates.values() if record.get("relevance") == "core"),
        key=rank_key,
    )
    seeds_path = project.directory / "proposed_seeds.tsv"
    with seeds_path.open("w", newline="") as handle:
        writer = csv.writer(handle, delimiter="\t")
        writer.writerow(["paperId", "year", "signals", "aspect", "title"])
        for record in core:
            writer.writerow(
                [
                    record["paperId"],
                    record.get("year") or "",
                    len(record.get("sources") or []),
                    record.get("aspect") or "",
                    record.get("title") or "",
                ]
            )
    labels = Counter(record.get("relevance") for record in candidates.values())
    print(f"labels: {dict(labels)}")
    print(f"{len(core)} proposed seeds -> {seeds_path}")


def stage_recommend(project: Project, client: S2Client, model: str) -> None:
    seeds_path = project.directory / "seeds.tsv"
    if not seeds_path.exists():
        sys.exit(f"copy and prune proposed_seeds.tsv to {seeds_path} first")
    with seeds_path.open(newline="") as handle:
        seed_ids = [row["paperId"] for row in csv.DictReader(handle, delimiter="\t")]
    candidates = project.load_candidates()
    for seed_id in seed_ids:
        for paper in client.recommend_for_paper(seed_id, PAPER_FIELDS, pool="all-cs", limit=30):
            add_paper(candidates, paper, f"recommended from seed {seed_id[:8]}")
    print(f"{len(candidates)} papers after recommendations", file=sys.stderr)
    score_unscored(project, candidates, model)
    project.save_candidates(candidates)
    labels = Counter(record.get("relevance") for record in candidates.values())
    print(f"labels: {dict(labels)}")


def stage_notes(
    project: Project,
    model: str,
    top: int,
    workers: int,
    paper_ids: list[str],
) -> None:
    candidates = project.load_candidates()
    core = sorted(
        (record for record in candidates.values() if record.get("relevance") == "core"),
        key=rank_key,
    )[:top]
    # always include papers the user asked for by ID, whatever their rank or label
    requested = [candidates[paper_id] for paper_id in paper_ids if paper_id in candidates]
    core = requested + [record for record in core if record["paperId"] not in paper_ids]
    todo = [
        record
        for record in core
        if not (project.notes_dir / f"{record['paperId']}.md").exists()
    ]
    print(f"{len(todo)} notes to write", file=sys.stderr)
    system_prompt = project.prompt("deepdive_note.md")
    with ThreadPoolExecutor(max_workers=workers) as executor:
        for status in executor.map(
            lambda record: write_note(
                record,
                system_prompt,
                project.notes_dir,
                model,
                relevance_heading="How it bears on the project",
            ),
            todo,
        ):
            print(status, file=sys.stderr)


def note_tldr(project: Project, paper_id: str) -> str | None:
    """Return the TL;DR section of a project note, if the note exists."""
    note_path = project.notes_dir / f"{paper_id}.md"
    if not note_path.exists():
        return None
    text = note_path.read_text()
    if "## TL;DR" not in text:
        return None
    return text.split("## TL;DR", 1)[1].split("\n## ", 1)[0].strip()


def stage_synthesize(project: Project, model: str, max_papers: int) -> None:
    candidates = project.load_candidates()
    relevant = sorted(
        (
            record
            for record in candidates.values()
            if record.get("relevance") in ("core", "related", "background")
        ),
        key=rank_key,
    )[:max_papers]

    lines = []
    for number, record in enumerate(relevant, start=1):
        entry = (
            f"[{number}] {record.get('title')} ({record.get('year')}) | {record['relevance']} | "
            f"{record.get('aspect')} | {record.get('why')}"
        )
        tldr = note_tldr(project, record["paperId"])
        if tldr:
            entry += f" | TL;DR: {tldr}"
        lines.append(entry)
    result = run_claude(
        project.prompt("deepdive_synthesis.md"),
        "Papers:\n\n" + "\n".join(lines),
        SYNTHESIS_SCHEMA,
        model=model,
    )
    if result.output is None:
        sys.exit(f"synthesis failed: {result.error}")

    references = [
        f"{number}. {record.get('title')} ({record.get('year')}). "
        f"https://www.semanticscholar.org/paper/{record['paperId']}"
        for number, record in enumerate(relevant, start=1)
    ]
    title = project.description.splitlines()[0].lstrip("# ")
    synthesis = (
        f"# Synthesis: {title}\n\n{result.output['markdown'].strip()}\n\n"
        "## References\n\n" + "\n".join(references) + "\n"
    )
    (project.directory / "synthesis.md").write_text(synthesis)
    print(f"synthesis (${result.cost_usd:.3f}) -> {project.directory / 'synthesis.md'}")
    write_reading_list(project, candidates)


def write_reading_list(project: Project, candidates: dict[str, dict]) -> None:
    """Write all non-irrelevant candidates, grouped by label, with reasons and note links."""
    sections = []
    for label in ("core", "related", "background"):
        records = sorted(
            (record for record in candidates.values() if record.get("relevance") == label),
            key=rank_key,
        )
        sections.append(f"## {label.capitalize()} ({len(records)})\n")
        for record in records:
            link = f"https://www.semanticscholar.org/paper/{record['paperId']}"
            line = (
                f"- **{record.get('title')}** ({record.get('year')}) [S2]({link}) "
                f"· _{record.get('aspect')}_: {record.get('why')}"
            )
            if (project.notes_dir / f"{record['paperId']}.md").exists():
                line += f" · [note](notes/{record['paperId']}.md)"
            sections.append(line)
        sections.append("")
    path = project.directory / "reading_list.md"
    path.write_text("# Reading list\n\n" + "\n".join(sections))
    print(f"reading list -> {path}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("stage", choices=["search", "recommend", "notes", "synthesize"])
    parser.add_argument("slug")
    parser.add_argument("--model", default="sonnet")
    parser.add_argument("--top", type=int, default=15, help="notes: how many core papers")
    parser.add_argument(
        "--paper-ids",
        nargs="*",
        default=[],
        help="notes: also write notes for these candidate paper IDs",
    )
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--max-papers", type=int, default=80, help="synthesize: papers listed")
    args = parser.parse_args()

    project = Project(args.slug)
    client = S2Client(min_interval=1.5)
    if args.stage == "search":
        stage_search(project, client, args.model)
    elif args.stage == "recommend":
        stage_recommend(project, client, args.model)
    elif args.stage == "notes":
        stage_notes(project, args.model, args.top, args.workers, args.paper_ids)
    else:
        stage_synthesize(project, args.model, args.max_papers)


if __name__ == "__main__":
    main()
