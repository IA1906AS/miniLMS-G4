from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

import pytest

from app import create_app


@pytest.fixture
def app(tmp_path):
    return create_app(
        {
            "TESTING": True,
            "JWT_SECRET": "reset-revocation-test-secret-at-least-32-characters",
            "BCRYPT_ROUNDS": 4,
            "AUDIT_LOG_PATH": str(tmp_path / "audit.log"),
            "SMTP_ENABLED": False,
            "LOCAL_EMAIL_ENABLED": False,
            "RESET_TOKEN_ECHO": True,
        }
    )


def links(app):
    with app.test_client() as client:
        return [
            client.post(
                "/auth/forgot-password", json={"email": "chi.sv@lms.test"}
            ).json["resetToken"]
            for _ in range(2)
        ]


def test_reset_revokes_all_preexisting_links_and_sessions(app, tmp_path):
    first, second = links(app)
    client = app.test_client()
    token = client.post(
        "/auth/login", json={"email": "chi.sv@lms.test", "password": "Lms@2026"}
    ).json["accessToken"]
    app.config["AUDIT_LOG_PATH"] = str(tmp_path)
    assert (
        client.post(
            "/auth/reset-password",
            json={"token": first, "password": "NewPassword@2026"},
        ).status_code
        == 200
    )
    for old in (first, second):
        assert (
            client.post(
                "/auth/reset-password",
                json={"token": old, "password": "AnotherPassword@2026"},
            ).status_code
            == 400
        )
    assert (
        client.get("/me", headers={"Authorization": "Bearer " + token}).status_code
        == 401
    )
    assert (
        client.post(
            "/auth/login",
            json={"email": "chi.sv@lms.test", "password": "NewPassword@2026"},
        ).status_code
        == 200
    )
    assert app.extensions["lms_store"].list_audit("RESET_PASSWORD", "u4", 1)[1] == 1

    fresh = client.post(
        "/auth/forgot-password", json={"email": "chi.sv@lms.test"}
    ).json["resetToken"]
    assert (
        client.post(
            "/auth/reset-password",
            json={"token": fresh, "password": "FreshPassword@2026"},
        ).status_code
        == 200
    )


def test_concurrent_distinct_reset_links_only_one_succeeds(app):
    tokens = links(app)
    barrier = Barrier(2)

    def reset(index):
        with app.test_client() as client:
            barrier.wait(timeout=10)
            return client.post(
                "/auth/reset-password",
                json={"token": tokens[index], "password": f"NewPassword{index}@2026"},
            ).status_code

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(reset, range(2)))
    assert sorted(results) == [200, 400]
    assert app.extensions["lms_store"].list_audit("RESET_PASSWORD", "u4", 1)[1] == 1


def test_reset_audit_failure_rolls_back_password_and_link_revocation(app, monkeypatch):
    first, second = links(app)
    store = app.extensions["lms_store"]
    before = store.get_user("u4")
    original = store.record_audit

    def fail_reset_audit(record, **kwargs):
        if record["action"] == "RESET_PASSWORD":
            raise RuntimeError("Simulated audit database failure")
        return original(record, **kwargs)

    monkeypatch.setattr(store, "record_audit", fail_reset_audit)
    client = app.test_client()
    assert (
        client.post(
            "/auth/reset-password",
            json={"token": first, "password": "NewPassword@2026"},
        ).status_code
        == 500
    )
    after = store.get_user("u4")
    assert after.password_hash == before.password_hash
    assert after.token_version == before.token_version
    monkeypatch.setattr(store, "record_audit", original)
    assert (
        client.post(
            "/auth/reset-password",
            json={"token": second, "password": "NewPassword@2026"},
        ).status_code
        == 200
    )
    assert (
        client.post(
            "/auth/reset-password",
            json={"token": first, "password": "AnotherPassword@2026"},
        ).status_code
        == 400
    )
