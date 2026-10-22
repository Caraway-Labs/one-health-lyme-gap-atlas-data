"""Synthetic descriptions; no claim about live publisher value semantics."""

from dataclasses import replace

import pytest
from test_intelligence_feed import approved
from test_intelligence_native_metadata import RAW, policy, records

from lyme_gap_atlas_data.intelligence_metadata import verify_native_item


def receipt(raw: bytes):
    base = policy(raw)
    return replace(
        base,
        inventory=base.inventory | {"item/description"},
        permitted_paths=base.permitted_paths | {"item/description"},
    )


@pytest.mark.parametrize(
    ("replacement", "text", "state"),
    [
        (b"", None, "not_provided"),
        (b"<description/>", "", "empty"),
        (b"<description>   </description>", "", "empty"),
        (
            b"<description><![CDATA[<p>Publisher <b>summary</b>.</p>"
            b"<script>bad()</script><img src='https://example.org/a'>]]></description>",
            "Publisher summary .",
            "present",
        ),
    ],
)
def test_description_missing_empty_and_safe_html(replacement, text, state):
    raw = RAW.replace(b"<description>Rights-restricted article text</description>", replacement)
    doc = records(raw, receipt=receipt(raw))[0]
    verify_native_item(doc, receipt(raw), approved())
    assert doc["publisher_metadata"]["description"] == {
        "text": text,
        "state": state,
        "format": "plain_text",
        "origin": "publisher",
    }
    assert "Tick borne disease" in doc["publisher_metadata"]["categories"]


def test_description_is_revision_content_and_not_silently_truncated():
    first = records(RAW, receipt=receipt(RAW))[0]
    assert first == records(RAW, receipt=receipt(RAW))[0]
    revised = RAW.replace(b"Rights-restricted article text", b"Corrected publisher summary")
    second = records(revised, receipt=receipt(revised))[0]
    assert first["item_id"] == second["item_id"]
    assert first["revision_id"] != second["revision_id"]
    huge = RAW.replace(b"Rights-restricted article text", b"x" * 4097)
    with pytest.raises(ValueError, match="INTELLIGENCE_NATIVE_FIELD_LIMIT"):
        records(huge, receipt=receipt(huge))
