from datetime import date, datetime, timezone
import json
import os
from pathlib import Path
import re
from typing import Literal
from uuid import uuid4

from fastapi import Depends, FastAPI, HTTPException, Query, Request
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.trustedhost import TrustedHostMiddleware
from pydantic import BaseModel, Field, field_validator

from .catalog import RESOURCES, TOPICS, recommend
from .database import Database
from .model import EmotionModel
from .auth import install_auth
from .demo import examples

ROOT = Path(__file__).resolve().parents[1]


class EntryInput(BaseModel):
    title: str = Field(default="", max_length=120)
    content: str = Field(min_length=1, max_length=10000)
    entry_date: date
    mood: int | None = Field(default=None, ge=1, le=5, strict=True)
    topic: Literal["stress", "self-compassion", "worry", "sleep"] | None = None

    @field_validator("title", "content")
    @classmethod
    def trim_text(cls, value: str, info):
        value = value.strip()
        if info.field_name == "content" and not value:
            raise ValueError("Write something before saving your entry.")
        return value

    @field_validator("content")
    @classmethod
    def english_script(cls, value: str):
        # A script guard, not language identification: Latin-script non-English text
        # may still pass. English is the declared input language for this MVP.
        letters = [c for c in value if c.isalpha()]
        if letters and sum(c.isascii() for c in letters) / len(letters) < 0.6:
            raise ValueError("This version supports English entries. Please write in English.")
        return value


def create_app(database_path: Path | None = None, model_path: Path | None = None) -> FastAPI:
    app = FastAPI(title="Still Journal API", version="0.1.0")
    database = Database(database_path or Path(os.getenv("STILL_DATABASE", str(ROOT / "data/journal.sqlite3"))))
    model = EmotionModel(model_path or Path(os.getenv("STILL_MODEL", str(ROOT / "artifacts/baseline.joblib"))))
    current_user = install_auth(app, database)
    allowed_hosts = os.getenv("STILL_ALLOWED_HOSTS", "127.0.0.1,localhost,testserver").split(",")
    allowed_origins = os.getenv("STILL_ALLOWED_ORIGINS", "http://127.0.0.1:8000,http://localhost:8000,http://127.0.0.1:5173,http://localhost:5173").split(",")
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=allowed_hosts)

    @app.middleware("http")
    async def local_protection(request: Request, call_next):
        # No CORS wildcard; reject browser writes initiated by unrelated sites.
        if request.method in {"POST", "PUT", "DELETE", "PATCH"}:
            if request.headers.get("x-still-client") != "web":
                return JSONResponse({"detail": "Missing request protection header."}, status_code=403)
            origin = request.headers.get("origin")
            if origin and origin not in allowed_origins:
                return JSONResponse({"detail": "This local app only accepts same-site writes."}, status_code=403)
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["X-Frame-Options"] = "DENY"
        if request.url.path.startswith("/api"):
            response.headers["Cache-Control"] = "no-store"
        return response

    def serialize(row):
        item = dict(row)
        item["analysis"] = json.loads(item["analysis"])
        item["recommendations"] = recommend(item["topic"], item["analysis"]["emotions"])
        return item

    def get_entry(entry_id: str, user_id: str):
        with database.connect() as conn:
            row = conn.execute("SELECT * FROM entries WHERE id = ? AND user_id = ?", (entry_id, user_id)).fetchone()
        if row is None:
            raise HTTPException(404, "Entry not found.")
        return serialize(row)

    @app.get("/api/status")
    def status():
        return {
            "status": "ok", "language": "en", "storage": "local-sqlite",
            "model_ready": model.ready,
            "model_version": model.bundle["version"] if model.ready else None,
            "model_kind": "TF-IDF + logistic regression" if model.ready else None,
            "scope": "Journal prototype with local accounts. No clinical validation.",
            "registration_open": os.getenv("STILL_ALLOW_REGISTRATION", "1") == "1",
        }

    @app.get("/api/demo")
    def demo():
        return examples()

    @app.get("/api/resources")
    def resources():
        return {"items": RESOURCES, "topics": TOPICS}

    @app.get("/api/entries")
    def list_entries(q: str = Query(default="", max_length=200),
                     limit: int = Query(default=100, ge=1, le=500),
                     offset: int = Query(default=0, ge=0), user: dict = Depends(current_user)):
        escaped = q.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        search = f"%{escaped}%"
        where = "WHERE user_id = ? AND (title LIKE ? ESCAPE '\\' OR content LIKE ? ESCAPE '\\')"
        with database.connect() as conn:
            total = conn.execute(f"SELECT COUNT(*) FROM entries {where}", (user["id"], search, search)).fetchone()[0]
            rows = conn.execute(
                f"SELECT * FROM entries {where} ORDER BY entry_date DESC, created_at DESC LIMIT ? OFFSET ?",
                (user["id"], search, search, limit, offset),
            ).fetchall()
        return {"items": [serialize(row) for row in rows], "total": total}

    @app.get("/api/entries/{entry_id}")
    def read_entry(entry_id: str, user: dict = Depends(current_user)):
        return get_entry(entry_id, user["id"])

    def entry_values(payload: EntryInput):
        title = payload.title or " ".join(re.findall(r"\S+", payload.content)[:7])[:120]
        analysis = model.predict(payload.content)
        return title, payload.content, payload.entry_date.isoformat(), payload.mood, payload.topic, json.dumps(analysis)

    @app.post("/api/entries", status_code=201)
    def create_entry(payload: EntryInput, user: dict = Depends(current_user)):
        entry_id = str(uuid4())
        now = datetime.now(timezone.utc).isoformat()
        values = entry_values(payload)
        with database.connect() as conn:
            conn.execute("""INSERT INTO entries
                         (id, title, content, entry_date, mood, topic, analysis, created_at, updated_at, user_id)
                         VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                         (entry_id, *values, now, now, user["id"]))
        return get_entry(entry_id, user["id"])

    @app.put("/api/entries/{entry_id}")
    def update_entry(entry_id: str, payload: EntryInput, user: dict = Depends(current_user)):
        get_entry(entry_id, user["id"])
        values = entry_values(payload)
        with database.connect() as conn:
            conn.execute("""UPDATE entries SET title=?, content=?, entry_date=?, mood=?, topic=?,
                         analysis=?, updated_at=? WHERE id=? AND user_id=?""",
                         (*values, datetime.now(timezone.utc).isoformat(), entry_id, user["id"]))
        return get_entry(entry_id, user["id"])

    @app.delete("/api/entries/{entry_id}", status_code=204)
    def delete_entry(entry_id: str, user: dict = Depends(current_user)):
        with database.connect() as conn:
            cursor = conn.execute("DELETE FROM entries WHERE id=? AND user_id=?", (entry_id, user["id"]))
            if cursor.rowcount == 0:
                raise HTTPException(404, "Entry not found.")
        return Response(status_code=204)

    @app.get("/api/summary")
    def summary(user: dict = Depends(current_user)):
        with database.connect() as conn:
            rows = conn.execute("SELECT entry_date, mood, analysis FROM entries WHERE user_id = ? ORDER BY entry_date", (user["id"],)).fetchall()
        emotion_counts: dict[str, int] = {}
        days: dict[str, list[int]] = {}
        for row in rows:
            days.setdefault(row["entry_date"], [])
            if row["mood"] is not None:
                days[row["entry_date"]].append(row["mood"])
            for emotion in json.loads(row["analysis"])["emotions"]:
                emotion_counts[emotion["label"]] = emotion_counts.get(emotion["label"], 0) + 1
        return {
            "entries": len(rows), "writing_days": len(days),
            "emotions": sorted([{"label": k, "count": v} for k, v in emotion_counts.items()],
                               key=lambda item: item["count"], reverse=True),
            "days": [{"date": day, "mood": round(sum(moods) / len(moods), 2) if moods else None,
                      "check_ins": len(moods)} for day, moods in days.items()],
        }

    dist = ROOT / "frontend/dist"
    if dist.is_dir():
        app.mount("/assets", StaticFiles(directory=dist / "assets"), name="assets")

        @app.get("/")
        def index():
            return FileResponse(dist / "index.html")

    return app
