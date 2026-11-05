from __future__ import annotations

import json
import os
import sqlite3
import threading
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from app.bursar.models import AgentFinding, AuditEvent, BursarCase, EvidenceReference, HumanDecision, SimulatedLedgerEntry
from app.bursar.passport import EvidencePassport
from app.bursar.timeline import TimelineEvent
from app.switch_adapter.models import SwitchMessage


class BursarRepositoryError(RuntimeError):
    """Safe repository error; never contains credentials or invoice content."""


def _json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"))


class BursarRepository:
    """Small persistence boundary. It stores state, but never applies policy."""

    def __init__(self, database_path: str | Path) -> None:
        self.database_path = str(database_path)
        self._lock = threading.RLock()
        self._connections: dict[int, sqlite3.Connection] = {}
        self._connections_lock = threading.RLock()
        self._closed = False
        try:
            if self.database_path != ":memory:":
                Path(self.database_path).parent.mkdir(parents=True, exist_ok=True)
            self.initialize()
        except (OSError, sqlite3.Error) as exc:
            raise BursarRepositoryError("unable to initialize Bursar database") from exc

    @classmethod
    def from_environment_optional(cls) -> "BursarRepository | None":
        url = os.getenv("BURSAR_DATABASE_URL")
        path = os.getenv("BURSAR_DATABASE_PATH")
        if url:
            parsed = urlparse(url)
            if parsed.scheme != "sqlite":
                raise BursarRepositoryError("BURSAR_DATABASE_URL must use sqlite")
            path = parsed.path or parsed.netloc
        if not path:
            return None
        return cls(path)

    def initialize(self) -> None:
        statements = [
            "CREATE TABLE IF NOT EXISTS schema_migrations (version INTEGER PRIMARY KEY, applied_at TEXT NOT NULL)",
            "CREATE TABLE IF NOT EXISTS cases (case_id TEXT PRIMARY KEY, status TEXT NOT NULL, requester_id TEXT NOT NULL, room_id TEXT, intake_message_id TEXT, finance_reviewer_id TEXT, vendor_name TEXT, invoice_number TEXT, total TEXT, currency TEXT, created_at TEXT NOT NULL, updated_at TEXT NOT NULL)",
            "CREATE TABLE IF NOT EXISTS switch_messages (message_id TEXT PRIMARY KEY, case_id TEXT NOT NULL, room_id TEXT NOT NULL, message_type TEXT NOT NULL, sender_type TEXT NOT NULL, sender_id TEXT NOT NULL, agent_role TEXT, payload_json TEXT NOT NULL, timestamp TEXT NOT NULL)",
            "CREATE TABLE IF NOT EXISTS evidence_references (evidence_id TEXT PRIMARY KEY, case_id TEXT NOT NULL, kind TEXT NOT NULL, file_name TEXT NOT NULL, sha256 TEXT NOT NULL, source_location TEXT, created_at TEXT NOT NULL)",
            "CREATE TABLE IF NOT EXISTS agent_findings (finding_id TEXT PRIMARY KEY, case_id TEXT NOT NULL, agent_name TEXT NOT NULL, finding_type TEXT NOT NULL, status TEXT NOT NULL, explanation TEXT NOT NULL, confidence REAL NOT NULL, evidence_json TEXT NOT NULL)",
            "CREATE TABLE IF NOT EXISTS human_decisions (decision_id INTEGER PRIMARY KEY AUTOINCREMENT, case_id TEXT NOT NULL, action TEXT NOT NULL, actor_id TEXT NOT NULL, actor_role TEXT NOT NULL, reason TEXT, occurred_at TEXT NOT NULL)",
            "CREATE TABLE IF NOT EXISTS audit_events (event_id TEXT PRIMARY KEY, case_id TEXT NOT NULL, event_type TEXT NOT NULL, actor_id TEXT NOT NULL, actor_type TEXT NOT NULL, payload_json TEXT NOT NULL, occurred_at TEXT NOT NULL)",
            "CREATE TABLE IF NOT EXISTS simulated_ledger_entries (entry_id TEXT PRIMARY KEY, case_id TEXT NOT NULL, amount TEXT NOT NULL, currency TEXT NOT NULL, approved_by TEXT NOT NULL, decision_event_id TEXT NOT NULL, created_at TEXT NOT NULL)",
            "CREATE TABLE IF NOT EXISTS timeline_events (event_id TEXT PRIMARY KEY, case_id TEXT NOT NULL, sequence INTEGER NOT NULL, event_type TEXT NOT NULL, actor_id TEXT NOT NULL, payload_json TEXT NOT NULL, occurred_at TEXT NOT NULL, UNIQUE(case_id, sequence))",
            "CREATE TABLE IF NOT EXISTS passports (case_id TEXT PRIMARY KEY, extracted_invoice_fields_json TEXT NOT NULL, check_results_json TEXT NOT NULL, updated_at TEXT NOT NULL)",
        ]
        with self._lock:
            try:
                for statement in statements:
                    self._connection.execute(statement)
                self._connection.execute("INSERT OR IGNORE INTO schema_migrations(version, applied_at) VALUES (?, datetime('now'))", (1,))
                self._connection.commit()
            except sqlite3.Error as exc:
                self._connection.rollback()
                raise BursarRepositoryError("unable to initialize Bursar schema") from exc

    def _get_connection(self) -> sqlite3.Connection:
        thread_id = threading.get_ident()
        with self._connections_lock:
            if self._closed:
                raise sqlite3.ProgrammingError("Bursar repository is closed")
            connection = self._connections.get(thread_id)
            if connection is None:
                connection = sqlite3.connect(self.database_path, timeout=5.0, check_same_thread=True)
                connection.row_factory = sqlite3.Row
                connection.execute("PRAGMA foreign_keys = ON")
                connection.execute("PRAGMA busy_timeout = 5000")
                if self.database_path != ":memory:":
                    connection.execute("PRAGMA journal_mode = WAL")
                self._connections[thread_id] = connection
            return connection

    @property
    def _connection(self) -> sqlite3.Connection:
        return self._get_connection()

    def close(self) -> None:
        with self._connections_lock:
            self._closed = True
            for connection in self._connections.values():
                connection.close()
            self._connections.clear()

    def _execute(self, sql: str, params: tuple = ()) -> sqlite3.Cursor:
        try:
            cursor = self._connection.execute(sql, params)
            self._connection.commit()
            return cursor
        except sqlite3.Error as exc:
            self._connection.rollback()
            raise BursarRepositoryError("Bursar database operation failed") from exc

    def save_case(self, case: BursarCase) -> None:
        d = case.model_dump(mode="json")
        self._execute("""INSERT INTO cases VALUES (?,?,?,?,?,?,?,?,?,?,?,?) ON CONFLICT(case_id) DO UPDATE SET status=excluded.status, finance_reviewer_id=excluded.finance_reviewer_id, updated_at=excluded.updated_at""", (d["case_id"], d["status"], d["requester_id"], d["room_id"], d["intake_message_id"], d["finance_reviewer_id"], d["vendor_name"], d["invoice_number"], str(case.total) if case.total is not None else None, d["currency"], d["created_at"], d["updated_at"]))

    def list_cases(self) -> list[BursarCase]:
        try:
            rows = self._connection.execute("SELECT * FROM cases ORDER BY created_at, case_id").fetchall()
            return [BursarCase.model_validate(dict(row)) for row in rows]
        except (sqlite3.Error, ValueError) as exc:
            raise BursarRepositoryError("unable to read Bursar cases") from exc

    def get_case(self, case_id: str) -> BursarCase | None:
        rows = [c for c in self.list_cases() if c.case_id == case_id]
        return rows[0] if rows else None

    def save_message(self, message: SwitchMessage) -> None:
        d = message.model_dump(mode="json")
        self._execute("INSERT OR IGNORE INTO switch_messages VALUES (?,?,?,?,?,?,?,?,?)", (d["message_id"], d["case"]["case_id"], d["room_id"], d["message_type"], d["sender_type"], d["sender_id"], d["agent_role"], _json(d["payload"]), d["timestamp"]))

    def list_messages(self, case_id: str, room_id: str | None = None) -> list[SwitchMessage]:
        try:
            sql = "SELECT * FROM switch_messages WHERE case_id = ?"
            params: tuple = (case_id,)
            if room_id is not None:
                sql += " AND room_id = ?"
                params += (room_id,)
            sql += " ORDER BY timestamp, message_id"
            rows = self._connection.execute(sql, params).fetchall()
            return [SwitchMessage.model_validate({"message_id": r["message_id"], "room_id": r["room_id"], "case": {"case_id": r["case_id"]}, "message_type": r["message_type"], "sender_type": r["sender_type"], "sender_id": r["sender_id"], "agent_role": r["agent_role"], "payload": json.loads(r["payload_json"]), "timestamp": r["timestamp"]}) for r in rows]
        except (sqlite3.Error, ValueError) as exc:
            raise BursarRepositoryError("unable to read Bursar messages") from exc

    def save_evidence(self, reference: EvidenceReference) -> None:
        d = reference.model_dump(mode="json")
        self._execute("INSERT OR IGNORE INTO evidence_references VALUES (?,?,?,?,?,?,?)", (d["evidence_id"], d["case_id"], d["kind"], d["file_name"], d["sha256"], d["source_location"], d["created_at"]))

    def list_evidence(self, case_id: str) -> list[EvidenceReference]:
        rows = self._connection.execute("SELECT * FROM evidence_references WHERE case_id = ? ORDER BY created_at, evidence_id", (case_id,)).fetchall()
        return [EvidenceReference.model_validate(dict(row)) for row in rows]

    def save_finding(self, finding: AgentFinding, case_id: str) -> None:
        d = finding.model_dump(mode="json")
        self._execute("INSERT OR REPLACE INTO agent_findings VALUES (?,?,?,?,?,?,?,?)", (d["finding_id"], case_id, d["agent_name"], d["finding_type"], d["status"], d["explanation"], d["confidence"], _json(d["evidence"])))

    def list_findings(self, case_id: str) -> list[AgentFinding]:
        rows = self._connection.execute("SELECT * FROM agent_findings WHERE case_id = ? ORDER BY finding_id", (case_id,)).fetchall()
        return [AgentFinding.model_validate({"finding_id": r["finding_id"], "agent_name": r["agent_name"], "finding_type": r["finding_type"], "status": r["status"], "explanation": r["explanation"], "confidence": r["confidence"], "evidence": json.loads(r["evidence_json"])}) for r in rows]

    def save_decision(self, decision: HumanDecision, case_id: str) -> None:
        d = decision.model_dump(mode="json")
        self._execute("INSERT INTO human_decisions(case_id,action,actor_id,actor_role,reason,occurred_at) VALUES (?,?,?,?,?,?)", (case_id, d["action"], d["actor_id"], d["actor_role"], d["reason"], d["occurred_at"]))

    def get_decision(self, case_id: str) -> HumanDecision | None:
        row = self._connection.execute("SELECT * FROM human_decisions WHERE case_id = ? ORDER BY decision_id DESC LIMIT 1", (case_id,)).fetchone()
        return HumanDecision.model_validate({"action": row["action"], "actor_id": row["actor_id"], "actor_role": row["actor_role"], "reason": row["reason"], "occurred_at": row["occurred_at"]}) if row else None

    def save_audit_event(self, event: AuditEvent) -> bool:
        cursor = self._execute("INSERT OR IGNORE INTO audit_events VALUES (?,?,?,?,?,?,?)", (event.event_id, event.case_id, event.event_type, event.actor_id, event.actor_type, _json(event.payload), event.occurred_at.isoformat()))
        return cursor.rowcount == 1

    def list_audit_events(self, case_id: str) -> list[AuditEvent]:
        rows = self._connection.execute("SELECT * FROM audit_events WHERE case_id = ? ORDER BY occurred_at, event_id", (case_id,)).fetchall()
        return [AuditEvent.model_validate({"event_id": r["event_id"], "case_id": r["case_id"], "event_type": r["event_type"], "actor_id": r["actor_id"], "actor_type": r["actor_type"], "payload": json.loads(r["payload_json"]), "occurred_at": r["occurred_at"]}) for r in rows]

    def save_ledger_entry(self, entry: SimulatedLedgerEntry) -> None:
        d = entry.model_dump(mode="json")
        self._execute("INSERT OR IGNORE INTO simulated_ledger_entries VALUES (?,?,?,?,?,?,?)", (d["entry_id"], d["case_id"], str(entry.amount), d["currency"], d["approved_by"], d["decision_event_id"], d["created_at"]))

    def get_ledger_entry(self, case_id: str) -> SimulatedLedgerEntry | None:
        row = self._connection.execute("SELECT * FROM simulated_ledger_entries WHERE case_id = ? ORDER BY created_at DESC LIMIT 1", (case_id,)).fetchone()
        return SimulatedLedgerEntry.model_validate(dict(row)) if row else None

    def save_timeline_event(self, event: TimelineEvent) -> bool:
        cursor = self._execute("INSERT OR IGNORE INTO timeline_events VALUES (?,?,?,?,?,?,?)", (event.event_id, event.case_id, event.sequence, event.event_type, event.actor_id, _json(event.payload), event.occurred_at.isoformat()))
        return cursor.rowcount == 1

    def list_timeline(self, case_id: str) -> list[TimelineEvent]:
        rows = self._connection.execute("SELECT * FROM timeline_events WHERE case_id = ? ORDER BY sequence", (case_id,)).fetchall()
        return [TimelineEvent.model_validate({"sequence": r["sequence"], "event_id": r["event_id"], "case_id": r["case_id"], "event_type": r["event_type"], "actor_id": r["actor_id"], "payload": json.loads(r["payload_json"]), "occurred_at": r["occurred_at"]}) for r in rows]

    def list_all_timeline(self) -> list[TimelineEvent]:
        rows = self._connection.execute("SELECT * FROM timeline_events ORDER BY case_id, sequence").fetchall()
        return [TimelineEvent.model_validate({"sequence": r["sequence"], "event_id": r["event_id"], "case_id": r["case_id"], "event_type": r["event_type"], "actor_id": r["actor_id"], "payload": json.loads(r["payload_json"]), "occurred_at": r["occurred_at"]}) for r in rows]

    def save_passport(self, passport: EvidencePassport) -> None:
        d = passport.model_dump(mode="json")
        self._execute("INSERT INTO passports VALUES (?,?,?,datetime('now')) ON CONFLICT(case_id) DO UPDATE SET extracted_invoice_fields_json=excluded.extracted_invoice_fields_json, check_results_json=excluded.check_results_json, updated_at=datetime('now')", (passport.case_id, _json(d["extracted_invoice_fields"]), _json(d["check_results"])))
        for reference in passport.evidence_references:
            self.save_evidence(reference)
        for finding in passport.agent_findings:
            self.save_finding(finding, passport.case_id)
        for event in passport.audit_events:
            self.save_audit_event(event)
        if passport.human_decision is not None and self.get_decision(passport.case_id) is None:
            self.save_decision(passport.human_decision, passport.case_id)
        if passport.simulated_ledger_result is not None:
            self.save_ledger_entry(passport.simulated_ledger_result)

    def get_passport(self, case_id: str) -> EvidencePassport | None:
        row = self._connection.execute("SELECT * FROM passports WHERE case_id = ?", (case_id,)).fetchone()
        if not row:
            return None
        return EvidencePassport(case_id=case_id, extracted_invoice_fields=json.loads(row["extracted_invoice_fields_json"]), check_results=json.loads(row["check_results_json"]), evidence_references=self.list_evidence(case_id), agent_findings=self.list_findings(case_id), human_decision=self.get_decision(case_id), audit_events=self.list_audit_events(case_id), simulated_ledger_result=self.get_ledger_entry(case_id))
