"""Short-lived fictional presentation rooms; never clinical records or audio analysis."""
import secrets
import threading
import time
from datetime import UTC, datetime
from typing import Literal
from uuid import UUID, uuid4

from fastapi import HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field

from patient_memory.auth import decode_token
from patient_memory.storage import require_member, transaction


class Submission(BaseModel):
    model_config = ConfigDict(extra="forbid")
    request_id: UUID
    duration_s: float = Field(gt=0, le=30, allow_inf_nan=False)


class Explanation(BaseModel):
    model_config = ConfigDict(extra="forbid")
    tag: Literal["exertion"]


class Rooms:
    """Bounded single-process demo state, discarded on expiry/restart; no patient IDs."""

    def __init__(self, clock=time.monotonic):
        self.clock, self.rooms, self.lock = clock, {}, threading.RLock()

    def create(self):
        with self.lock:
            self.rooms = {k: v for k, v in self.rooms.items() if v["expires"] > self.clock()}
            if len(self.rooms) >= 128:
                raise HTTPException(429, "Demo room capacity reached")
            rid = str(uuid4())
            keys = {role: secrets.token_urlsafe(32) for role in ("nurse", "runner", "resident")}
            self.rooms[rid] = {"expires": self.clock() + 7200, "keys": keys,
                               "checks": [], "explained": False, "revision": 0}
            return {"room": rid, "keys": keys, "expires_in_s": 7200}

    def get(self, rid, token, role):
        room = self.rooms.get(str(rid))
        if not room or room["expires"] <= self.clock():
            self.rooms.pop(str(rid), None)
            raise HTTPException(404, "Demo room unavailable; ask the nurse for a new link")
        if not secrets.compare_digest(room["keys"][role], token):
            raise HTTPException(404, "Demo room unavailable")
        return room

    def submit(self, rid, token, body):
        with self.lock:
            room = self.rooms.get(str(rid))
            role = next((r for r in ("runner", "resident") if room and
                         secrets.compare_digest(room["keys"][r], token)), None)
            room = self.get(rid, token, role or "runner")
            if role is None:
                raise HTTPException(404, "Capture link required")
            prior = next((c for c in room["checks"] if c["id"] == str(body.request_id)), None)
            if prior:
                if prior["resident"] != role or prior["duration_s"] != body.duration_s:
                    raise HTTPException(409, "Check-in ID already used")
                return {"id": prior["id"], "accepted": True,
                        "remaining_checks": (1 if role == "runner" else 2) - prior["take"]}
            count = sum(c["resident"] == role for c in room["checks"])
            if count >= (1 if role == "runner" else 2):
                raise HTTPException(409, "Scenario complete; ask the nurse to start a new room")
            room["checks"].append({"id": str(body.request_id), "resident": role,
                                   "take": count + 1, "duration_s": body.duration_s,
                                   "received_at": datetime.now(UTC).isoformat()})
            room["revision"] += 1
            return {"id": str(body.request_id), "accepted": True,
                    "remaining_checks": (1 if role == "runner" else 2) - count - 1}

    def snapshot(self, rid, token):
        with self.lock:
            room = self.get(rid, token, "nurse")
            checks = []
            for check in room["checks"]:
                verdict = ("explained" if room["explained"] else "watch") if (
                    check["resident"] == "runner") else (
                    "escalate" if check["take"] == 2 else "watch")
                checks.append({**check, "verdict": verdict})
            return {"revision": room["revision"], "checks": checks,
                    "exertion": room["explained"], "scenario": "authored-demo",
                    "capture_keys": {r: room["keys"][r] for r in ("runner", "resident")}}

    def explain(self, rid, token):
        with self.lock:
            room = self.get(rid, token, "nurse")
            if not any(c["resident"] == "runner" for c in room["checks"]):
                raise HTTPException(409, "Receive the runner's check-in first")
            if not room["explained"]:
                room["explained"] = True
                room["revision"] += 1
            return self.snapshot(rid, token)


def register(app, cfg, reader):
    rooms = Rooms()

    def bearer(request):
        return request.headers.get("authorization", "").removeprefix("Bearer ")

    @app.post("/demo/handoff", include_in_schema=False, status_code=201)
    def create(request: Request):
        identity = decode_token(bearer(request), cfg)
        if identity != reader:
            raise HTTPException(404, "Nurse demo session required")
        with transaction(cfg, identity) as conn:
            require_member(conn)
        return rooms.create()

    @app.get("/demo/handoff/{rid}", include_in_schema=False)
    def read(rid: UUID, request: Request):
        return rooms.snapshot(rid, bearer(request))

    @app.post("/demo/handoff/{rid}/checks", include_in_schema=False)
    def submit(rid: UUID, body: Submission, request: Request):
        return rooms.submit(rid, bearer(request), body)

    @app.post("/demo/handoff/{rid}/context", include_in_schema=False)
    def explain(rid: UUID, body: Explanation, request: Request):
        return rooms.explain(rid, bearer(request))

    @app.delete("/demo/handoff/{rid}", include_in_schema=False)
    def remove(rid: UUID, request: Request):
        with rooms.lock:
            rooms.get(rid, bearer(request), "nurse")
            del rooms.rooms[str(rid)]
        return {"deleted": True}
