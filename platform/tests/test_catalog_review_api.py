"""API transaction controls; synthetic catalog admission is not byte-validation proof."""

import pytest
from botocore.exceptions import EndpointConnectionError
from crashcap_api.app import create_app
from crashcap_api.config import Settings
from crashcap_api.models import CatalogChange, CatalogPair, CatalogPairReview
from fastapi.testclient import TestClient
from sqlalchemy import func, select

from .catalog_fixtures import admit_pair, origin, pair_evidence


@pytest.fixture
def review_api(tmp_path):
    app = create_app(
        Settings.for_test(tmp_path).model_copy(update={"catalog_reviews_enabled": True})
    )
    with app.state.database.sessions.begin() as session:
        pe, pdb, locations = pair_evidence()
        pair_id = admit_pair(session, pe, pdb, locations, origin()).id
    with TestClient(app) as client:
        yield app, client, pair_id


def review_body(**changes):
    return {
        "expected_version": 1,
        "state": "withdrawn",
        "reason": "provider check",
        "reviewer": "test provider",
        "evidence": "checked original binary and full PDB",
        "idempotency_key": "review-one",
        **changes,
    }


def test_review_replay_conflict_history_and_integrity(review_api):
    app, client, pair_id = review_api
    url = f"/api/v3/symbol-catalog/pairs/{pair_id}/reviews"
    first = client.post(url, json=review_body())
    assert first.status_code == 200, first.text
    assert client.post(url, json=review_body()).json() == first.json()
    assert client.post(url, json=review_body(reason="changed")).status_code == 409
    assert client.post(url, json=review_body(idempotency_key="stale")).status_code == 409
    second = client.post(
        url, json=review_body(expected_version=2, state="active", idempotency_key="restore")
    )
    assert second.status_code == 200, second.text
    page = client.get(url, params={"limit": 1}).json()
    assert page["items"][0]["id"] == second.json()["id"]
    tail = client.get(url, params={"limit": 1, "before_version": page["next_version"]}).json()
    assert tail["items"][0]["id"] == first.json()["id"] and tail["next_version"] is None
    evidence_url = f"{url}/{first.json()['id']}/evidence"
    evidence = client.get(evidence_url)
    assert evidence.status_code == 200
    assert evidence.json()["evidence"] == review_body()["evidence"]
    assert client.get(evidence_url.replace(pair_id, "wrong")).status_code == 404
    with app.state.database.sessions() as session:
        assert session.scalar(select(func.count()).select_from(CatalogPairReview)) == 2
        assert session.scalar(select(func.count()).select_from(CatalogChange)) == 5
        assert session.get(CatalogPair, pair_id).qualification_version == 3
        key = session.get(CatalogPairReview, first.json()["id"]).evidence_object_key
    app.state.store.put_bytes(key, b"corrupted", "application/json")
    assert client.get(evidence_url).status_code == 503


def test_bad_evidence_readback_does_not_change_catalog(review_api, monkeypatch):
    app, client, pair_id = review_api
    monkeypatch.setattr(app.state.store, "stream", lambda key: iter([b"wrong bytes"]))
    result = client.post(f"/api/v3/symbol-catalog/pairs/{pair_id}/reviews", json=review_body())
    assert result.status_code == 503
    with app.state.database.sessions() as session:
        assert session.get(CatalogPair, pair_id).qualification_version == 1
        assert session.get(CatalogPair, pair_id).state == "active"
        assert session.scalar(select(func.count()).select_from(CatalogPairReview)) == 0
        assert session.scalar(select(func.count()).select_from(CatalogChange)) == 3


def test_review_default_enabled_and_blank_evidence_rejected(tmp_path, review_api):
    app = create_app(Settings.for_test(tmp_path / "disabled"))
    with TestClient(app) as client:
        assert (
            client.post(
                "/api/v3/symbol-catalog/pairs/missing/reviews", json=review_body()
            ).status_code
            == 404
        )
    _, client, pair_id = review_api
    assert (
        client.post(
            f"/api/v3/symbol-catalog/pairs/{pair_id}/reviews", json=review_body(evidence="  ")
        ).status_code
        == 422
    )


@pytest.mark.parametrize("operation", ["put_bytes", "stream"])
def test_review_storage_outage_is_retryable_without_catalog_mutation(
    review_api, monkeypatch, operation
):
    app, client, pair_id = review_api
    url = f"/api/v3/symbol-catalog/pairs/{pair_id}/reviews"

    def unavailable(*args, **kwargs):
        raise EndpointConnectionError(endpoint_url="https://private-store/SECRET_SENTINEL")

    with monkeypatch.context() as patch:
        patch.setattr(app.state.store, operation, unavailable)
        response = client.post(url, json=review_body())
    assert response.status_code == 503
    assert "SECRET_SENTINEL" not in response.text
    with app.state.database.sessions() as session:
        assert session.get(CatalogPair, pair_id).qualification_version == 1
        assert session.scalar(select(func.count()).select_from(CatalogPairReview)) == 0
        assert session.scalar(select(func.count()).select_from(CatalogChange)) == 3
    assert client.post(url, json=review_body()).status_code == 200
    assert client.post(url, json=review_body()).status_code == 200
    with app.state.database.sessions() as session:
        assert session.scalar(select(func.count()).select_from(CatalogPairReview)) == 1
        assert session.scalar(select(func.count()).select_from(CatalogChange)) == 4


def test_review_read_interruption_never_returns_partial_evidence(review_api, monkeypatch):
    app, client, pair_id = review_api
    url = f"/api/v3/symbol-catalog/pairs/{pair_id}/reviews"
    created = client.post(url, json=review_body()).json()
    evidence_url = f"{url}/{created['id']}/evidence"
    expected = client.get(evidence_url).json()

    def interrupted(key):
        yield b'{"reviewer":"unverified data"'
        raise OSError("SECRET_SENTINEL")

    with monkeypatch.context() as patch:
        patch.setattr(app.state.store, "stream", interrupted)
        response = client.get(evidence_url)
    assert response.status_code == 503
    assert "unverified data" not in response.text and "SECRET_SENTINEL" not in response.text
    assert client.get(evidence_url).json() == expected
    with app.state.database.sessions() as session:
        key = session.get(CatalogPairReview, created["id"]).evidence_object_key
    original = b"".join(app.state.store.stream(key))
    app.state.store.delete(key)
    assert client.get(evidence_url).status_code == 503
    app.state.store.put_bytes(key, original, "application/json")
    assert client.get(evidence_url).json() == expected
