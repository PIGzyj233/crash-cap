import hashlib
from types import SimpleNamespace

import pytest
from crashcap_api.errors import ApiError
from crashcap_api.services.current_decisions import MAX_EVIDENCE_JSON_BYTES
from crashcap_api.services.result_reviews import read_review_object


class EvidenceStore:
    def __init__(self, size, chunks):
        self.size, self.chunks = size, chunks
        self.streamed = False

    def head(self, _key):
        return SimpleNamespace(size=self.size)

    def stream(self, _key):
        self.streamed = True
        yield from self.chunks


def test_review_object_checks_actual_streamed_content():
    payload = b'{"evidence":true}'
    store = EvidenceStore(len(payload), [payload[:3], payload[3:]])
    assert (
        read_review_object(store, "evidence.json", hashlib.sha256(payload).hexdigest()) == payload
    )


@pytest.mark.parametrize(
    "size,chunks",
    [
        (3, [b"ab"]),
        (2, [b"abc"]),
        (2, [b"a", b"bc"]),
        (2, [b"xy"]),
    ],
)
def test_review_object_rejects_truncation_growth_and_corruption(size, chunks):
    with pytest.raises(ApiError):
        read_review_object(
            EvidenceStore(size, chunks), "evidence.json", hashlib.sha256(b"ab").hexdigest()
        )


@pytest.mark.parametrize("size", [-1, MAX_EVIDENCE_JSON_BYTES + 1])
def test_oversize_review_evidence_is_rejected_before_stream(size):
    store = EvidenceStore(size, [b"unused"])
    with pytest.raises(ApiError):
        read_review_object(store, "evidence.json", "a" * 64)
    assert not store.streamed
