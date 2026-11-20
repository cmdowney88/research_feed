from pathlib import Path

import pytest

from litfeed import library

ENTRY_A = "@inproceedings{smith-2024-thing,\n  title = {A {Nested} Thing},\n  year = {2024}\n}"
ENTRY_B = "@misc{jones2026other,\n  title={Other},\n}"


@pytest.fixture
def temp_library(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setattr(library, "INDEX_PATH", tmp_path / "index.tsv")
    monkeypatch.setattr(library, "download_pdf", lambda record, key: "")
    return tmp_path


def make_record(paper_id: str) -> dict:
    return {"paperId": paper_id, "feeds": {"asr": 3, "adaptation": 1, "citing_me": 0}}


def test_entry_key_and_with_key() -> None:
    assert library.entry_key(ENTRY_A) == "smith-2024-thing"
    renamed = library.with_key(ENTRY_A, "smith-2024-thingb")
    assert library.entry_key(renamed) == "smith-2024-thingb"
    assert "{Nested}" in renamed


def test_remove_entry_is_brace_matched() -> None:
    text = ENTRY_A + "\n\n" + ENTRY_B + "\n"
    remaining = library.remove_entry(text, "smith-2024-thing")
    assert "Nested" not in remaining
    assert library.entry_key(remaining) == "jones2026other"


def test_default_collection_prefers_best_ranked_seed_feed() -> None:
    record = make_record("p")
    assert library.default_collection(record, ["asr", "adaptation"]) == "adaptation"
    only_citing = {"paperId": "q", "feeds": {"citing_me": 0}}
    assert library.default_collection(only_citing, ["asr"]) == library.GENERAL_COLLECTION


def test_save_dedupes_keys_moves_and_unsaves(
    temp_library: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(library, "fetch_bibtex", lambda record: (ENTRY_A, "acl"))
    first = library.save_paper(make_record("p1"), "asr")
    second = library.save_paper(make_record("p2"), "asr")
    assert (first["key"], second["key"]) == ("smith-2024-thing", "smith-2024-thingb")

    library.save_paper(make_record("p1"), "adaptation")
    asr_bib = (temp_library / "asr.bib").read_text()
    assert "smith-2024-thingb" in asr_bib and "{smith-2024-thing," not in asr_bib
    assert "smith-2024-thing," in (temp_library / "adaptation.bib").read_text()

    library.unsave_paper("p2")
    assert "smith" not in (temp_library / "asr.bib").read_text()
    assert set(library.load_index()) == {"p1"}


def test_save_raises_when_no_bibtex(
    temp_library: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(library, "fetch_bibtex", lambda record: None)
    with pytest.raises(LookupError):
        library.save_paper(make_record("p"), "asr")
