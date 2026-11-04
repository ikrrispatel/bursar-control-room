from __future__ import annotations

from pathlib import Path
from uuid import uuid4

from fastapi import APIRouter, File, HTTPException, UploadFile
from langgraph.types import Command

from app.graph.workflow import build_graph
from app.bursar.inspection import (
    BursarInspectionService,
    CaseDetail,
    CaseListResponse,
    DecisionResponse,
    EvidencePassportResponse,
    FindingsResponse,
    LedgerResponse,
    TimelineResponse,
)
from app.bursar.workflow import LocalBursarWorkflowCoordinator
from app.switch_adapter import SwitchMessage
from app.switch_adapter.boundary import LiveMattermostBursarBoundary, SwitchCommandRequest

router = APIRouter()

RUNS: dict[str, dict] = {}
RUN_GRAPHS: dict[str, object] = {}
LIVE_BURSAR_BOUNDARY: LiveMattermostBursarBoundary | None = None
BURSAR_COORDINATOR = LocalBursarWorkflowCoordinator()


@router.get("/health")
def health() -> dict:
    return {"status": "ok"}


@router.get("/bursar/cases", response_model=CaseListResponse)
def list_bursar_cases() -> CaseListResponse:
    return _inspection().list_cases()


@router.get("/bursar/cases/{case_id}", response_model=CaseDetail)
def get_bursar_case(case_id: str) -> CaseDetail:
    try:
        return _inspection().case_detail(case_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Bursar case not found") from exc


@router.get("/bursar/cases/{case_id}/passport", response_model=EvidencePassportResponse)
def get_bursar_passport(case_id: str) -> EvidencePassportResponse:
    try:
        return EvidencePassportResponse(passport=_inspection().evidence_passport(case_id))
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Bursar case not found") from exc


@router.get("/bursar/cases/{case_id}/timeline", response_model=TimelineResponse)
def get_bursar_timeline(case_id: str) -> TimelineResponse:
    try:
        return TimelineResponse(events=_inspection().timeline(case_id))
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Bursar case not found") from exc


@router.get("/bursar/cases/{case_id}/findings", response_model=FindingsResponse)
def get_bursar_findings(case_id: str) -> FindingsResponse:
    try:
        return _inspection().findings(case_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Bursar case not found") from exc


@router.get("/bursar/cases/{case_id}/decision", response_model=DecisionResponse)
def get_bursar_decision(case_id: str) -> DecisionResponse:
    try:
        return _inspection().decision(case_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Bursar case not found") from exc


@router.get("/bursar/cases/{case_id}/ledger", response_model=LedgerResponse)
def get_bursar_ledger(case_id: str) -> LedgerResponse:
    try:
        return _inspection().ledger(case_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Bursar case not found") from exc


@router.post("/switch/messages")
def receive_switch_message(message: SwitchMessage) -> dict:
    try:
        result = _live_boundary().receive_message(message)
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return result.model_dump(mode="json")


@router.post("/switch/commands")
def receive_switch_command(request: SwitchCommandRequest) -> dict:
    try:
        result = _live_boundary().receive_command(request)
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return result.model_dump(mode="json")


@router.post("/runs")
async def create_run(files: list[UploadFile] = File(...)) -> dict:
    run_id = str(uuid4())
    upload_dir = Path("data/uploads") / run_id
    upload_dir.mkdir(parents=True, exist_ok=True)

    uploaded_documents = []

    for file in files:
        path = upload_dir / file.filename
        path.write_bytes(await file.read())
        uploaded_documents.append(
            {
                "path": str(path),
                "filename": file.filename,
                "document_type": "unknown",
            }
        )

    graph = build_graph()
    result = graph.invoke(
        {"run_id": run_id, "uploaded_documents": uploaded_documents},
        config={"configurable": {"thread_id": run_id}},
    )

    RUNS[run_id] = result
    RUN_GRAPHS[run_id] = graph

    if result.get("requires_human_approval"):
        status = "requires_approval"
    elif (result.get("erp_result") or {}).get("status") == "posted":
        status = "posted"
    else:
        status = "completed"

    return {"run_id": run_id, "status": status, "result": result}


@router.get("/runs/{run_id}")
def get_run(run_id: str) -> dict:
    return RUNS.get(run_id, {"status": "not_found"})


@router.post("/runs/{run_id}/approve")
def approve_run(run_id: str) -> dict:
    return _resume_run(
        run_id,
        {"status": "approved", "approved_by": "api"},
    )


@router.post("/runs/{run_id}/reject")
def reject_run(run_id: str) -> dict:
    return _resume_run(
        run_id,
        {"status": "rejected", "approved_by": "api"},
    )


@router.get("/runs/{run_id}/audit")
def get_audit(run_id: str) -> dict:
    audit_path = Path("data/processed/audit.jsonl")
    if not audit_path.exists():
        return {"run_id": run_id, "events": []}

    events = [
        line
        for line in audit_path.read_text(encoding="utf-8").splitlines()
        if f'"run_id": "{run_id}"' in line
    ]
    return {"run_id": run_id, "events": events}


def _resume_run(run_id: str, approval: dict) -> dict:
    graph = RUN_GRAPHS.get(run_id)
    if graph is None:
        return {"run_id": run_id, "status": "not_found"}

    current = RUNS.get(run_id, {})
    if "__interrupt__" not in current:
        return {
            "run_id": run_id,
            "status": "not_waiting_for_approval",
            "result": current,
        }

    result = graph.invoke(
        Command(resume=approval),
        config={"configurable": {"thread_id": run_id}},
    )
    RUNS[run_id] = result

    erp_status = (result.get("erp_result") or {}).get("status")
    if approval["status"] == "rejected":
        status = "rejected"
    elif erp_status == "posted":
        status = "posted"
    else:
        status = "completed"

    return {"run_id": run_id, "status": status, "result": result}


def _live_boundary() -> LiveMattermostBursarBoundary:
    global LIVE_BURSAR_BOUNDARY, BURSAR_COORDINATOR
    if LIVE_BURSAR_BOUNDARY is None:
        try:
            LIVE_BURSAR_BOUNDARY = LiveMattermostBursarBoundary.from_environment()
            BURSAR_COORDINATOR = LIVE_BURSAR_BOUNDARY.coordinator
        except ValueError as exc:
            raise HTTPException(
                status_code=503,
                detail="live Switch configuration is unavailable; set SWITCH_BASE_URL, SWITCH_TOKEN, SWITCH_TEAM_ID, and SWITCH_CHANNEL_ID",
            ) from exc
    return LIVE_BURSAR_BOUNDARY


def configure_live_boundary(boundary: LiveMattermostBursarBoundary | None) -> None:
    """Inject a boundary for tests or replace the process-local live boundary."""
    global LIVE_BURSAR_BOUNDARY, BURSAR_COORDINATOR
    LIVE_BURSAR_BOUNDARY = boundary
    if boundary is not None:
        BURSAR_COORDINATOR = boundary.coordinator
    else:
        BURSAR_COORDINATOR = LocalBursarWorkflowCoordinator()


def configure_bursar_coordinator(coordinator: LocalBursarWorkflowCoordinator) -> None:
    """Inject the in-memory coordinator for read-only query tests or hosting."""
    global BURSAR_COORDINATOR
    BURSAR_COORDINATOR = coordinator


def _inspection() -> BursarInspectionService:
    return BursarInspectionService(BURSAR_COORDINATOR)
