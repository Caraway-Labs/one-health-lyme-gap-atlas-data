import io
import tarfile

import pytest

from lyme_gap_atlas_data.pmc_graph import PmcOpenAccessClient, admit_pmc_open_access


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


def test_pmc_client_uses_only_the_oa_package_jats(monkeypatch: pytest.MonkeyPatch) -> None:
    package_buffer = io.BytesIO()
    with tarfile.open(fileobj=package_buffer, mode="w:gz") as package:
        member = tarfile.TarInfo("article.nxml")
        payload = jats()
        member.size = len(payload)
        package.addfile(member, io.BytesIO(payload))

    class Response:
        def __init__(self, content: bytes) -> None:
            self.content = content

        def raise_for_status(self) -> None:
            return None

    calls: list[str] = []

    def get(url: str, **kwargs: object) -> Response:
        calls.append(url)
        if url.endswith("oa.fcgi"):
            return Response(
                b'<OA><records><record><link format="tgz" '
                b'href="ftp://example.test/a.tgz" /></record></records></OA>'
            )
        return Response(package_buffer.getvalue())

    monkeypatch.setattr("lyme_gap_atlas_data.pmc_graph.httpx.get", get)
    assert PmcOpenAccessClient().fetch_jats("PMC123") == jats()
    assert calls == [
        "https://www.ncbi.nlm.nih.gov/pmc/utils/oa/oa.fcgi",
        "https://example.test/a.tgz",
    ]
