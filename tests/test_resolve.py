import pytest

from litfeed.resolve import lookup_key

HEX = "0b33e11706a73d95ed46e7593412f35bd413c514"


@pytest.mark.parametrize(
    "text, expected",
    [
        (f"https://www.semanticscholar.org/paper/Some-Title/{HEX}", HEX),
        (HEX, HEX),
        ("https://arxiv.org/abs/2401.12345v2", "ARXIV:2401.12345"),
        ("https://arxiv.org/pdf/2401.12345v3.pdf", "ARXIV:2401.12345"),
        ("arXiv:2401.12345", "ARXIV:2401.12345"),
        ("2401.12345", "ARXIV:2401.12345"),
        ("cs.CL/0701001", "ARXIV:cs.CL/0701001"),
        ("https://doi.org/10.18653/v1/2023.acl-long.1", "DOI:10.18653/v1/2023.acl-long.1"),
        ("10.1145/3292500.3330701", "DOI:10.1145/3292500.3330701"),
        ("https://aclanthology.org/2023.acl-long.1/", "ACL:2023.acl-long.1"),
        ("https://aclanthology.org/2023.acl-long.1.pdf", "ACL:2023.acl-long.1"),
        ("CorpusId:12345", "CorpusId:12345"),
        ("Attention is all you need", None),
        ("Whisper 2.0: a study", None),
    ],
)
def test_lookup_key(text: str, expected: str | None) -> None:
    assert lookup_key(text) == expected
