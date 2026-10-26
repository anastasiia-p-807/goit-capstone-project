"""Local accounts and revocable sessions. No diary text is stored in cookies."""
from collections import defaultdict, deque
from datetime import datetime, timezone
import hashlib
import hmac
import os
import secrets
import sqlite3
import threading
import time
from uuid import uuid4

from fastapi import APIRouter, HTTPException, Request, Response
from pydantic import BaseModel, Field, field_validator

COOKIE = "still_session"
SESSION_SECONDS = 7 * 24 * 60 * 60


class Credentials(BaseModel):
    username: str = Field(min_length=3, max_length=32, pattern=r"^[a-zA-Z0-9_-]+$")
    password: str = Field(min_length=10, max_length=128)

    @field_validator("username")
    @classmethod
    def normalize(cls, value):
        return value.lower()


def password_hash(password: str, salt: str | None = None) -> str:
    salt = salt or secrets.token_hex(16)
    digest = hashlib.scrypt(password.encode(), salt=bytes.fromhex(salt), n=16384, r=8, p=1).hex()
    return f"{salt}:{digest}"


def token_hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def install_auth(app, database):
    router = APIRouter(prefix="/api/auth")
    secure = os.getenv("STILL_SECURE_COOKIES", "0") == "1"
    attempts = defaultdict(deque)
    lock = threading.Lock()
    dummy_hash = password_hash(secrets.token_urlsafe(32))

    def throttle(request):
        key = request.client.host if request.client else "unknown"
        now = time.monotonic()
        with lock:
            for host in list(attempts):
                while attempts[host] and attempts[host][0] < now - 60:
                    attempts[host].popleft()
                if not attempts[host]:
                    del attempts[host]
            if len(attempts[key]) >= 10:
                raise HTTPException(429, "Too many attempts. Try again in a minute.", headers={"Retry-After": "60"})
            attempts[key].append(now)

    def current_user(request: Request):
        token = request.cookies.get(COOKIE)
        if not token:
            raise HTTPException(401, "Please sign in to continue.")
        with database.connect() as conn:
            row = conn.execute("""SELECT users.id, users.username FROM sessions
                JOIN users ON users.id = sessions.user_id
                WHERE token_hash = ? AND expires_at > ?""", (token_hash(token), int(time.time()))).fetchone()
        if not row:
            raise HTTPException(401, "Your session has expired. Please sign in again.")
        return dict(row)

    def start_session(user, request, response):
        token = secrets.token_urlsafe(32)
        with database.connect() as conn:
            conn.execute("DELETE FROM sessions WHERE expires_at <= ?", (int(time.time()),))
            old = request.cookies.get(COOKIE)
            if old:
                conn.execute("DELETE FROM sessions WHERE token_hash = ?", (token_hash(old),))
            conn.execute("INSERT INTO sessions VALUES (?, ?, ?)",
                         (token_hash(token), user["id"], int(time.time()) + SESSION_SECONDS))
        response.set_cookie(COOKIE, token, max_age=SESSION_SECONDS, httponly=True,
                            secure=secure, samesite="strict", path="/")
        return {"user": {"id": user["id"], "username": user["username"]}}

    @router.post("/register", status_code=201)
    def register(payload: Credentials, request: Request, response: Response):
        if os.getenv("STILL_ALLOW_REGISTRATION", "1") != "1":
            raise HTTPException(403, "Registration is currently closed.")
        throttle(request)
        user = {"id": str(uuid4()), "username": payload.username}
        encoded = password_hash(payload.password)
        try:
            with database.connect() as conn:
                conn.execute("INSERT INTO users VALUES (?, ?, ?, ?)",
                             (user["id"], user["username"], encoded, datetime.now(timezone.utc).isoformat()))
        except sqlite3.IntegrityError:
            raise HTTPException(409, "This username is already taken.")
        return start_session(user, request, response)

    @router.post("/login")
    def login(payload: Credentials, request: Request, response: Response):
        throttle(request)
        with database.connect() as conn:
            user = conn.execute("SELECT * FROM users WHERE username = ?", (payload.username,)).fetchone()
        encoded = user["password_hash"] if user else dummy_hash
        valid = hmac.compare_digest(password_hash(payload.password, encoded.split(":")[0]), encoded)
        if not user or not valid:
            raise HTTPException(401, "Incorrect username or password.")
        return start_session(user, request, response)

    @router.get("/me")
    def me(request: Request):
        return {"user": current_user(request)}

    @router.post("/logout", status_code=204)
    def logout(request: Request, response: Response):
        token = request.cookies.get(COOKIE)
        if token:
            with database.connect() as conn:
                conn.execute("DELETE FROM sessions WHERE token_hash = ?", (token_hash(token),))
        response.delete_cookie(COOKIE, path="/", secure=secure, httponly=True, samesite="strict")

    app.include_router(router)
    return current_user
