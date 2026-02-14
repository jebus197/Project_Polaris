"""Append-only event log — the canonical record of all governance actions.

Every state change in Genesis produces an event record that is appended
to the log. Events are immutable once written. The log serves as:
1. The input to Merkle tree computation for epoch commitments.
2. The audit trail for third-party verification.
3. The source of truth for state reconstruction.

Constitutional invariant: "Can trust decisions occur without audit trail?
If yes, reject design." — This module ensures the answer is always no.
"""

from __future__ import annotations

import enum
import hashlib
import json
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional


class EventKind(str, enum.Enum):
    """Classification of governance events."""
    MISSION_CREATED = "mission_created"
    MISSION_TRANSITION = "mission_transition"
    REVIEWER_ASSIGNED = "reviewer_assigned"
    REVIEW_SUBMITTED = "review_submitted"
    EVIDENCE_ADDED = "evidence_added"
    TRUST_UPDATED = "trust_updated"
    ACTOR_REGISTERED = "actor_registered"
    ACTOR_STATUS_CHANGED = "actor_status_changed"
    EPOCH_OPENED = "epoch_opened"
    EPOCH_CLOSED = "epoch_closed"
    COMMITMENT_ANCHORED = "commitment_anchored"
    GOVERNANCE_BALLOT = "governance_ballot"
    PHASE_TRANSITION = "phase_transition"
    QUALITY_ASSESSED = "quality_assessed"
    # Market events
    LISTING_CREATED = "listing_created"
    LISTING_TRANSITION = "listing_transition"
    BID_SUBMITTED = "bid_submitted"
    WORKER_ALLOCATED = "worker_allocated"
    # Skill lifecycle events
    SKILL_UPDATED = "skill_updated"
    SKILL_ENDORSED = "skill_endorsed"
    SKILL_DECAYED = "skill_decayed"
    # Protected leave events
    LEAVE_REQUESTED = "leave_requested"
    LEAVE_ADJUDICATED = "leave_adjudicated"
    LEAVE_APPROVED = "leave_approved"
    LEAVE_DENIED = "leave_denied"
    LEAVE_RETURNED = "leave_returned"
    LEAVE_PERMANENT = "leave_permanent"  # Legacy — kept for log compat
    LEAVE_MEMORIALISED = "leave_memorialised"


@dataclass(frozen=True)
class EventRecord:
    """A single immutable event in the governance log.

    Once created, an event cannot be modified. The event_hash is
    computed at creation time and serves as the leaf hash for
    Merkle tree inclusion.
    """
    event_id: str
    event_kind: EventKind
    timestamp_utc: str
    actor_id: str
    payload: dict[str, Any]
    event_hash: str  # SHA-256 of canonical JSON

    @staticmethod
    def create(
        event_id: str,
        event_kind: EventKind,
        actor_id: str,
        payload: dict[str, Any],
        timestamp_utc: Optional[datetime] = None,
    ) -> EventRecord:
        """Create a new event record with computed hash."""
        ts = timestamp_utc or datetime.now(timezone.utc)
        ts_str = ts.strftime("%Y-%m-%dT%H:%M:%SZ")

        # Compute canonical hash
        canonical = json.dumps(
            {
                "event_id": event_id,
                "event_kind": event_kind.value,
                "timestamp_utc": ts_str,
                "actor_id": actor_id,
                "payload": payload,
            },
            sort_keys=True,
            ensure_ascii=False,
        ).encode("utf-8")
        digest = hashlib.sha256(canonical).hexdigest()

        return EventRecord(
            event_id=event_id,
            event_kind=event_kind,
            timestamp_utc=ts_str,
            actor_id=actor_id,
            payload=payload,
            event_hash=f"sha256:{digest}",
        )


class EventLog:
    """Append-only event log with optional file persistence.

    Events can only be appended, never modified or deleted.
    The log can be persisted to a JSONL file (one JSON object per line)
    and loaded back for recovery.
    """

    def __init__(self, storage_path: Optional[Path] = None) -> None:
        self._events: list[EventRecord] = []
        self._storage_path = storage_path
        self._event_ids: set[str] = set()

        if storage_path and storage_path.exists():
            self._load_from_file(storage_path)

    def append(self, event: EventRecord) -> None:
        """Append an event to the log.

        Raises ValueError if event_id is a duplicate (replay protection).
        """
        if event.event_id in self._event_ids:
            raise ValueError(f"Duplicate event ID: {event.event_id}")

        self._events.append(event)
        self._event_ids.add(event.event_id)

        if self._storage_path:
            self._append_to_file(event)

    def events(self, kind: Optional[EventKind] = None) -> list[EventRecord]:
        """Return events, optionally filtered by kind."""
        if kind is None:
            return list(self._events)
        return [e for e in self._events if e.event_kind == kind]

    def events_since(
        self,
        since_utc: str,
        kind: Optional[EventKind] = None,
    ) -> list[EventRecord]:
        """Return events after a timestamp, optionally filtered by kind."""
        result = [e for e in self._events if e.timestamp_utc >= since_utc]
        if kind is not None:
            result = [e for e in result if e.event_kind == kind]
        return result

    def event_hashes(self, kind: Optional[EventKind] = None) -> list[str]:
        """Return all event hashes for Merkle tree construction."""
        return [e.event_hash for e in self.events(kind)]

    @property
    def count(self) -> int:
        return len(self._events)

    @property
    def last_event(self) -> Optional[EventRecord]:
        return self._events[-1] if self._events else None

    def _append_to_file(self, event: EventRecord) -> None:
        """Append a single event to the JSONL file."""
        record = {
            "event_id": event.event_id,
            "event_kind": event.event_kind.value,
            "timestamp_utc": event.timestamp_utc,
            "actor_id": event.actor_id,
            "payload": event.payload,
            "event_hash": event.event_hash,
        }
        with self._storage_path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(record, sort_keys=True, ensure_ascii=False) + "\n")

    def _load_from_file(self, path: Path) -> None:
        """Load events from a JSONL file with integrity verification.

        Fail-closed: rejects tampered records (hash mismatch) and
        duplicate event IDs (replay protection on recovery).
        """
        with path.open("r", encoding="utf-8") as f:
            for line_num, line in enumerate(f, 1):
                line = line.strip()
                if not line:
                    continue
                data = json.loads(line)

                event_id = data["event_id"]

                # Replay protection: reject duplicate IDs on load
                if event_id in self._event_ids:
                    raise ValueError(
                        f"Duplicate event ID on recovery (line {line_num}): {event_id}"
                    )

                # Recompute canonical hash to verify integrity
                canonical = json.dumps(
                    {
                        "event_id": data["event_id"],
                        "event_kind": data["event_kind"],
                        "timestamp_utc": data["timestamp_utc"],
                        "actor_id": data["actor_id"],
                        "payload": data["payload"],
                    },
                    sort_keys=True,
                    ensure_ascii=False,
                ).encode("utf-8")
                expected_hash = f"sha256:{hashlib.sha256(canonical).hexdigest()}"

                if data["event_hash"] != expected_hash:
                    raise ValueError(
                        f"Integrity check failed (line {line_num}): event {event_id} "
                        f"stored hash {data['event_hash']} != computed {expected_hash}"
                    )

                event = EventRecord(
                    event_id=data["event_id"],
                    event_kind=EventKind(data["event_kind"]),
                    timestamp_utc=data["timestamp_utc"],
                    actor_id=data["actor_id"],
                    payload=data["payload"],
                    event_hash=data["event_hash"],
                )
                self._events.append(event)
                self._event_ids.add(event.event_id)
