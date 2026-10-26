from datetime import date

from fastapi.testclient import TestClient
import pytest

from backend.main import create_app


@pytest.fixture
def client(tmp_path):
    with TestClient(create_app(tmp_path / "journal.sqlite3", tmp_path / "missing.joblib")) as value:
        value.headers["X-Still-Client"] = "web"
        assert value.post("/api/auth/register", json={"username": "writer", "password": "test-password-123"}).status_code == 201
        yield value


def entry(**overrides):
    return {"title": "A quiet moment", "content": "I felt pleased after a walk today.",
            "entry_date": date.today().isoformat(), "mood": 4, "topic": "stress", **overrides}


def test_entry_lifecycle_and_summary(client):
    response = client.post("/api/entries", json=entry())
    assert response.status_code == 201
    saved = response.json()
    assert saved["analysis"]["status"] == "unavailable"
    assert saved["recommendations"][0]["id"] == "who-stress"
    assert "chosen reading topic" in saved["recommendations"][0]["reason"]
    assert client.get("/api/entries").json()["total"] == 1
    summary = client.get("/api/summary").json()
    assert summary["days"][0]["mood"] == 4
    assert summary["emotions"] == []  # A self-report must not become a model prediction.
    updated = client.put(f"/api/entries/{saved['id']}", json=entry(content="A different thought.", mood=2, topic=None))
    assert updated.status_code == 200
    assert updated.json()["recommendations"] == []
    assert client.get("/api/summary").json()["days"][0]["mood"] == 2
    assert client.delete(f"/api/entries/{saved['id']}").status_code == 204
    assert client.get(f"/api/entries/{saved['id']}").status_code == 404
    assert client.get("/api/summary").json()["entries"] == 0


@pytest.mark.parametrize("changes", [{"content": "  "}, {"content": "x" * 10001}, {"mood": 6},
                                     {"topic": "diagnosis"}, {"entry_date": "not-a-date"},
                                     {"content": "Сьогодні я дуже радію новинам."}])
def test_invalid_input_is_not_saved(client, changes):
    assert client.post("/api/entries", json=entry(**changes)).status_code == 422
    assert client.get("/api/entries").json()["total"] == 0


def test_local_origin_and_literal_search(client):
    blocked = client.post("/api/entries", json=entry(), headers={"origin": "https://unrelated.example"})
    assert blocked.status_code == 403
    client.post("/api/entries", json=entry(title="100% effort"))
    client.post("/api/entries", json=entry(title="Another entry"))
    assert client.get("/api/entries", params={"q": "%"}).json()["total"] == 1
    assert client.get("/api/entries").headers["cache-control"] == "no-store"


def test_storage_survives_app_recreation(tmp_path):
    path = tmp_path / "journal.sqlite3"
    with TestClient(create_app(path, tmp_path / "missing.joblib")) as first:
        first.headers["X-Still-Client"] = "web"
        first.post("/api/auth/register", json={"username": "writer", "password": "test-password-123"})
        saved = first.post("/api/entries", json=entry()).json()
    with TestClient(create_app(path, tmp_path / "missing.joblib")) as second:
        second.headers["X-Still-Client"] = "web"
        second.post("/api/auth/login", json={"username": "writer", "password": "test-password-123"})
        assert second.get(f"/api/entries/{saved['id']}").json()["content"] == entry()["content"]


def test_account_isolation_and_logout(client):
    saved = client.post("/api/entries", json=entry()).json()
    old_cookie = client.cookies.get("still_session")
    assert client.post("/api/auth/logout").status_code == 204
    assert client.get("/api/entries").status_code == 401
    assert client.get("/api/summary").status_code == 401
    client.cookies.set("still_session", old_cookie)
    assert client.get("/api/auth/me").status_code == 401
    client.cookies.clear()
    assert client.post("/api/auth/register", json={"username": "second", "password": "another-password"}).status_code == 201
    assert client.get("/api/entries").json()["total"] == 0
    assert client.get("/api/summary").json()["entries"] == 0
    for method in ("get", "put", "delete"):
        kwargs = {"json": entry()} if method == "put" else {}
        assert getattr(client, method)(f"/api/entries/{saved['id']}", **kwargs).status_code == 404
    client.post("/api/auth/logout")
    assert client.post("/api/auth/login", json={"username": "WRITER", "password": "test-password-123"}).status_code == 200
    assert client.get("/api/entries").json()["total"] == 1


def test_credentials_csrf_and_demo_separation(client):
    assert client.post("/api/auth/register", json={"username": "WRITER", "password": "different-pass"}).status_code == 409
    assert client.post("/api/auth/login", json={"username": "writer", "password": "incorrect-password"}).status_code == 401
    assert client.post("/api/entries", json=entry(), headers={"X-Still-Client": ""}).status_code == 403
    assert client.get("/api/status", headers={"host": "attacker.example"}).status_code == 400
    before = client.get("/api/summary").json()
    demo = client.get("/api/demo").json()
    assert len(demo["items"]) == 3
    assert all(item["analysis"]["status"] == "demo" for item in demo["items"])
    assert client.get("/api/summary").json() == before
    # Clients cannot inject fabricated analysis into stored records.
    saved = client.post("/api/entries", json=entry(analysis=demo["items"][0]["analysis"])).json()
    assert saved["analysis"]["status"] == "unavailable"


def test_pagination_and_daily_mood_average(client):
    for mood in (1, 5, None):
        assert client.post("/api/entries", json=entry(mood=mood)).status_code == 201
    first = client.get("/api/entries?limit=2").json()
    second = client.get("/api/entries?limit=2&offset=2").json()
    assert first["total"] == second["total"] == 3
    assert len(first["items"]) == 2 and len(second["items"]) == 1
    assert not ({x["id"] for x in first["items"]} & {x["id"] for x in second["items"]})
    summary = client.get("/api/summary").json()
    assert summary["days"][0]["mood"] == 3
    assert summary["days"][0]["check_ins"] == 2


def test_session_expiry_and_password_storage(client, tmp_path):
    import sqlite3
    with sqlite3.connect(tmp_path / "journal.sqlite3") as conn:
        encoded = conn.execute("SELECT password_hash FROM users").fetchone()[0]
        assert "test-password" not in encoded
        stored_token = conn.execute("SELECT token_hash FROM sessions").fetchone()[0]
        assert stored_token != client.cookies.get("still_session")
        conn.execute("UPDATE sessions SET expires_at=0")
    assert client.get("/api/entries").status_code == 401


def test_registration_toggle_and_rate_limit(client, monkeypatch):
    monkeypatch.setenv("STILL_ALLOW_REGISTRATION", "0")
    assert client.get("/api/status").json()["registration_open"] is False
    assert client.post("/api/auth/register", json={"username": "closed", "password": "test-password-123"}).status_code == 403
    for _ in range(9):
        assert client.post("/api/auth/login", json={"username": "writer", "password": "wrong-password"}).status_code == 401
    assert client.post("/api/auth/login", json={"username": "writer", "password": "wrong-password"}).status_code == 429


def test_legacy_migration_preserves_unassigned_entries(tmp_path):
    import sqlite3
    from backend.database import Database
    path = tmp_path / "legacy.sqlite3"
    with sqlite3.connect(path) as conn:
        conn.execute("""CREATE TABLE entries (id TEXT PRIMARY KEY, title TEXT, content TEXT,
            entry_date TEXT, mood INTEGER, topic TEXT, analysis TEXT, created_at TEXT, updated_at TEXT)""")
        conn.execute("INSERT INTO entries VALUES ('legacy', 'old', 'original text', '2026-10-01', NULL, NULL, '{}', '', '')")
    Database(path)
    Database(path)
    with sqlite3.connect(path) as conn:
        assert conn.execute("SELECT content, user_id FROM entries").fetchone() == ("original text", None)


def test_legacy_claim_is_explicit_and_does_not_reassign_owned_entries(client, tmp_path, monkeypatch):
    import sqlite3
    from backend.claim_legacy import main
    saved = client.post("/api/entries", json=entry()).json()
    path = tmp_path / "journal.sqlite3"
    with sqlite3.connect(path) as conn:
        conn.execute("UPDATE entries SET user_id=NULL WHERE id=?", (saved["id"],))
    other = client.post("/api/entries", json=entry(title="Already owned")).json()
    client.post("/api/auth/register", json={"username": "new_owner", "password": "test-password-123"})
    args = ["claim_legacy", "--database", str(path), "--username", "new_owner"]
    monkeypatch.setattr("sys.argv", args)
    main()
    assert client.get("/api/entries").json()["total"] == 0
    monkeypatch.setattr("sys.argv", args + ["--apply"])
    main()
    assert client.get(f"/api/entries/{saved['id']}").status_code == 200
    assert client.get(f"/api/entries/{other['id']}").status_code == 404


def test_session_cookie_flags(tmp_path, monkeypatch):
    monkeypatch.setenv("STILL_SECURE_COOKIES", "1")
    app = create_app(tmp_path / "secure.sqlite3", tmp_path / "missing.joblib")
    with TestClient(app, base_url="https://localhost") as client:
        response = client.post("/api/auth/register", json={"username": "secure_user", "password": "test-password-123"}, headers={"X-Still-Client": "web"})
        cookie = response.headers["set-cookie"].lower()
        assert "httponly" in cookie and "secure" in cookie and "samesite=strict" in cookie
        assert client.get("/api/auth/me").status_code == 200
