import pytest

from lyme_gap_atlas_data.pmc_graph import admit_pmc_open_access


def jats(
    language: str = "en", license_url: str = "https://creativecommons.org/licenses/by/4.0/"
) -> bytes:
    return f'''<article xml:lang="{language}" xmlns:xlink="http://www.w3.org/1999/xlink">
      <front><article-meta><article-id pub-id-type="pmc">PMC123</article-id>
      <permissions><license xlink:href="{license_url}" /></permissions></article-meta></front>
      <body><sec><title>Results</title><p>Reviewed evidence text.</p></sec></body>
    </article>'''.encode()


def test_admits_only_english_explicit_open_access_jats() -> None:
    admitted = admit_pmc_open_access(jats())
    assert admitted.pmcid == "PMC123"
    assert admitted.normalized_text == "Results Reviewed evidence text."
    assert len(admitted.jats_sha256) == 64


@pytest.mark.parametrize(
    "payload",
    [jats(language="fr"), jats(license_url="https://example.com/all-rights-reserved")],
)
def test_rejects_ineligible_full_text_before_extraction(payload: bytes) -> None:
    with pytest.raises(ValueError):
        admit_pmc_open_access(payload)
