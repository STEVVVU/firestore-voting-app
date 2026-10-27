import hashlib
import os
import sqlite3
from contextlib import asynccontextmanager, closing
from datetime import datetime, timezone
from typing import Literal

import firebase_admin
from fastapi import FastAPI, Header, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from firebase_admin import auth
from google.api_core.exceptions import Aborted, AlreadyExists, DeadlineExceeded, RetryError, ServiceUnavailable
from google.cloud import firestore
from google.cloud.firestore_v1.base_query import FieldFilter
from pydantic import BaseModel


class Vote(BaseModel):
    team: Literal["TABS", "SPACES"]


def settings():
    mode = os.getenv("APP_ENV", "production")
    backend = os.getenv("VOTING_BACKEND", "firestore")
    identity = os.getenv("IDENTITY_MODE", "firebase")
    if mode not in ("local", "production") or backend not in ("sqlite", "firestore") or identity not in ("local", "firebase"):
        raise RuntimeError("Invalid application configuration")
    if mode != "local" and (backend != "firestore" or identity != "firebase"):
        raise RuntimeError("Local adapters are forbidden outside APP_ENV=local")
    if mode == "production" and (os.getenv("FIREBASE_AUTH_EMULATOR_HOST") or os.getenv("FIRESTORE_EMULATOR_HOST")):
        raise RuntimeError("Emulators are forbidden in production")
    project = os.getenv("GOOGLE_CLOUD_PROJECT")
    if (backend == "firestore" or identity == "firebase") and not project:
        raise RuntimeError("GOOGLE_CLOUD_PROJECT is required")
    if mode == "production" and not all(os.getenv(name) for name in ("FIREBASE_API_KEY", "FIREBASE_AUTH_DOMAIN")):
        raise RuntimeError("Firebase web configuration is required")
    return backend, identity, project


@asynccontextmanager
async def lifespan(app):
    backend, identity, project = settings()
    app.state.identity = identity
    if identity == "firebase" and not firebase_admin._apps:
        firebase_admin.initialize_app(options={"projectId": project})
    if backend == "firestore":
        app.state.store = FirestoreStore(firestore.Client(project=project))
    else:
        app.state.store = SQLiteStore(os.getenv("SQLITE_PATH", "votes.sqlite3"))
    yield


app = FastAPI(lifespan=lifespan)
app.mount("/static", StaticFiles(directory="static"), name="static")


def user_id(authorization: str | None):
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(401, detail="Bearer token required")
    token = authorization[7:]
    if app.state.identity == "local":
        if not token.startswith("local:") or not token[6:] or len(token) > 200:
            raise HTTPException(401, detail="Invalid token")
        return token[6:]
    try:
        return auth.verify_id_token(token, check_revoked=True)["uid"]
    except (ValueError, auth.InvalidIdTokenError, auth.UserDisabledError):
        raise HTTPException(401, detail="Invalid token") from None
    except Exception:
        raise HTTPException(503, detail="Identity verification unavailable") from None


def key(uid):
    return hashlib.sha256(uid.encode()).hexdigest()


class SQLiteStore:
    def __init__(self, path):
        self.path = path
        with closing(sqlite3.connect(path)) as db, db:
            db.execute("CREATE TABLE IF NOT EXISTS votes (uid TEXT PRIMARY KEY, team TEXT NOT NULL, cast_at TEXT NOT NULL)")

    def cast(self, uid, team):
        with closing(sqlite3.connect(self.path, timeout=10)) as db, db:
            db.execute("BEGIN IMMEDIATE")
            previous = db.execute("SELECT team FROM votes WHERE uid = ?", (key(uid),)).fetchone()
            if previous:
                return previous[0] == team
            db.execute("INSERT INTO votes VALUES (?, ?, ?)", (key(uid), team, datetime.now(timezone.utc).isoformat()))
            return True

    def results(self):
        with closing(sqlite3.connect(self.path)) as db, db:
            counts = dict(db.execute("SELECT team, COUNT(*) FROM votes GROUP BY team"))
            recent = [{"team": team, "cast_at": time} for team, time in db.execute("SELECT team, cast_at FROM votes ORDER BY cast_at DESC LIMIT 10")]
        return {"counts": {team: counts.get(team, 0) for team in ("TABS", "SPACES")}, "recent": recent}


class FirestoreStore:
    def __init__(self, db):
        self.db = db

    def cast(self, uid, team):
        vote = self.db.collection("votes").document(key(uid))
        try:
            vote.create({"team": team, "cast_at": firestore.SERVER_TIMESTAMP})
            return True
        except AlreadyExists:
            return vote.get().to_dict()["team"] == team

    def results(self):
        votes = self.db.collection("votes")
        counts = {team: votes.where(filter=FieldFilter("team", "==", team)).count().get()[0][0].value for team in ("TABS", "SPACES")}
        query = votes.order_by("cast_at", direction=firestore.Query.DESCENDING).limit(10)
        recent = []
        for document in query.stream():
            data = document.to_dict()
            recent.append({"team": data["team"], "cast_at": data["cast_at"].isoformat()})
        return {"counts": counts, "recent": recent}


@app.get("/health")
def health():
    return {"status": "ok"}


@app.get("/config")
def config():
    return {"apiKey": os.getenv("FIREBASE_API_KEY", ""), "authDomain": os.getenv("FIREBASE_AUTH_DOMAIN", ""), "projectId": os.getenv("GOOGLE_CLOUD_PROJECT", "")}


@app.get("/results")
def results():
    try:
        return app.state.store.results()
    except (Aborted, DeadlineExceeded, RetryError, ServiceUnavailable):
        raise HTTPException(503, detail="Results unavailable; retry later") from None


@app.post("/votes")
def vote(body: Vote, authorization: str | None = Header(default=None)):
    uid = user_id(authorization)
    try:
        recorded = app.state.store.cast(uid, body.team)
    except (Aborted, DeadlineExceeded, RetryError, ServiceUnavailable):
        raise HTTPException(503, detail="Vote storage unavailable; retry the same choice") from None
    if not recorded:
        raise HTTPException(409, detail="A different vote is already recorded")
    return {"status": "recorded"}


@app.get("/")
def index():
    return FileResponse("static/index.html")
