import json
import logging
import os
from contextlib import asynccontextmanager
from typing import Any

from apscheduler.schedulers.background import BackgroundScheduler
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from openai import OpenAI
from pydantic import BaseModel
from dotenv import load_dotenv

from jobs import job_generate_mock_data, job_run_anomaly_detection
from services import (
    get_alarm_detail_service,
    get_alarm_summary_service,
    get_anomalies_atomic_service,
    get_anomalies_service,
    get_complaints_atomic_service,
    get_complaints_service,
    get_faults_atomic_service,
    get_faults_service,
    get_homepage_summary_service,
    get_metrics_atomic_service,
    get_metrics_service,
    get_recent_event_stream_service,
    get_region_detail_service,
    get_region_risk_ranking_service,
    get_station_service,
    get_stations_atomic_service,
)

log = logging.getLogger(__name__)
scheduler = BackgroundScheduler(timezone="Europe/Istanbul")

load_dotenv()

LLM_MODEL = os.getenv("GROQ_MODEL", "llama-3.3-70b-versatile")


@asynccontextmanager
async def lifespan(app: FastAPI):
    if not scheduler.running:
        scheduler.add_job(
            job_generate_mock_data,
            trigger="interval",
            seconds=30,
            id="mock_data_job",
            replace_existing=True,
            max_instances=1,
        )
        scheduler.add_job(
            job_run_anomaly_detection,
            trigger="interval",
            seconds=120,
            id="anomaly_job",
            replace_existing=True,
            max_instances=1,
        )
        scheduler.start()
        log.info("Scheduler started with mock=30s and anomaly=120s intervals.")
    try:
        yield
    finally:
        if scheduler.running:
            scheduler.shutdown(wait=False)
            log.info("Scheduler stopped.")


app = FastAPI(title="Telecom NOC API", version="2.0.0", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


class ChatRequest(BaseModel):
    message: str
    limit: int = 20


class ChatResponse(BaseModel):
    summary: str
    evidence: list[dict[str, Any]]
    root_cause: str
    recommended_actions: list[str]
    confidence: float


TOOL_SCHEMAS: list[dict[str, Any]] = [
    {
        "type": "function",
        "function": {
            "name": "get_faults",
            "description": "Fault verisini filtrelerle getirir.",
            "parameters": {
                "type": "object",
                "properties": {
                    "cell_id": {"type": "string", "description": "CELL_XXX veya all"},
                    "region": {"type": "string", "description": "Bolge veya all"},
                    "severity": {"type": "string", "description": "CRITICAL/MAJOR/MINOR/WARNING/all"},
                    "fault_type": {"type": "string", "description": "Fault tipi veya all"},
                    "resolved": {"type": "string", "description": "true/false/all"},
                    "window_min": {"anyOf": [{"type": "integer"}, {"type": "string"}]},
                    "limit": {"anyOf": [{"type": "integer"}, {"type": "string"}]},
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_complaints",
            "description": "Sikayet verisini filtrelerle getirir.",
            "parameters": {
                "type": "object",
                "properties": {
                    "cell_id": {"type": "string"},
                    "region": {"type": "string"},
                    "issue": {"type": "string"},
                    "window_min": {"anyOf": [{"type": "integer"}, {"type": "string"}]},
                    "limit": {"anyOf": [{"type": "integer"}, {"type": "string"}]},
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_anomalies",
            "description": "Anomaly verisini filtrelerle getirir.",
            "parameters": {
                "type": "object",
                "properties": {
                    "cell_id": {"type": "string"},
                    "region": {"type": "string"},
                    "severity": {"type": "string"},
                    "only_anomalies": {"anyOf": [{"type": "boolean"}, {"type": "string"}]},
                    "window_min": {"anyOf": [{"type": "integer"}, {"type": "string"}]},
                    "limit": {"anyOf": [{"type": "integer"}, {"type": "string"}]},
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_metrics",
            "description": "Network metrics verisini filtrelerle getirir.",
            "parameters": {
                "type": "object",
                "properties": {
                    "cell_id": {"type": "string"},
                    "region": {"type": "string"},
                    "slice_type": {"type": "string"},
                    "window_min": {"anyOf": [{"type": "integer"}, {"type": "string"}]},
                    "limit": {"anyOf": [{"type": "integer"}, {"type": "string"}]},
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_stations",
            "description": "Istasyon envanter verisini filtrelerle getirir.",
            "parameters": {
                "type": "object",
                "properties": {
                    "cell_id": {"type": "string"},
                    "region": {"type": "string"},
                    "status": {"type": "string"},
                    "limit": {"anyOf": [{"type": "integer"}, {"type": "string"}]},
                },
            },
        },
    },
]


def _tool_dispatch(name: str, args: dict[str, Any], default_limit: int) -> dict[str, Any]:
    def _to_int(v: Any, fallback: int) -> int:
        if v is None:
            return fallback
        try:
            return int(v)
        except Exception:
            return fallback

    def _to_bool(v: Any, fallback: bool) -> bool:
        if isinstance(v, bool):
            return v
        if isinstance(v, str):
            low = v.strip().lower()
            if low in ("true", "1", "yes"):
                return True
            if low in ("false", "0", "no"):
                return False
        return fallback

    if "window_min" in args:
        args["window_min"] = _to_int(args.get("window_min"), 60)
    if "limit" in args:
        args["limit"] = _to_int(args.get("limit"), default_limit)
    if "only_anomalies" in args:
        args["only_anomalies"] = _to_bool(args.get("only_anomalies"), True)
    if "limit" not in args:
        args["limit"] = default_limit
    if name == "get_faults":
        return get_faults_atomic_service(**args)
    if name == "get_complaints":
        return get_complaints_atomic_service(**args)
    if name == "get_anomalies":
        return get_anomalies_atomic_service(**args)
    if name == "get_metrics":
        return get_metrics_atomic_service(**args)
    if name == "get_stations":
        return get_stations_atomic_service(**args)
    raise RuntimeError(f"Bilinmeyen tool: {name}")


def _get_llm_client() -> OpenAI:
    api_key = os.getenv("GROQ_API_KEY") or os.getenv("OPENAI_API_KEY")
    if not api_key:
        raise RuntimeError("GROQ_API_KEY (veya OPENAI_API_KEY) tanimli degil.")
    return OpenAI(
        api_key=api_key,
        base_url=os.getenv("GROQ_BASE_URL", "https://api.groq.com/openai/v1"),
    )


def _run_llm_tool_loop(user_message: str, limit: int) -> dict[str, Any]:
    client = _get_llm_client()
    messages: list[dict[str, Any]] = [
        {
            "role": "system",
            "content": (
                "You are a telecom NOC assistant. Use tools when needed. "
                "Final answer MUST be valid JSON with keys: "
                "summary, evidence, root_cause, recommended_actions, confidence. "
                "confidence must be 0..1."
            ),
        },
        {"role": "user", "content": user_message},
    ]

    for _ in range(3):
        resp = client.chat.completions.create(
            model=LLM_MODEL,
            messages=messages,
            tools=TOOL_SCHEMAS,
            tool_choice="auto",
            temperature=0.1,
        )
        msg = resp.choices[0].message
        tool_calls = msg.tool_calls or []
        if not tool_calls:
            raw = msg.content or "{}"
            try:
                parsed = json.loads(raw)
            except json.JSONDecodeError:
                parsed = {
                    "summary": raw.strip() or "Sonuc olusturulamadi.",
                    "evidence": [],
                    "root_cause": "Belirsiz",
                    "recommended_actions": ["Tool cagrisi sonucuna gore manuel inceleme yapin."],
                    "confidence": 0.35,
                }
            return parsed

        messages.append(
            {
                "role": "assistant",
                "content": msg.content or "",
                "tool_calls": [tc.model_dump() for tc in tool_calls],
            }
        )
        for tc in tool_calls:
            fn_name = tc.function.name
            try:
                args = json.loads(tc.function.arguments or "{}")
            except json.JSONDecodeError:
                args = {}
            tool_result = _tool_dispatch(fn_name, args, default_limit=limit)
            messages.append(
                {
                    "role": "tool",
                    "tool_call_id": tc.id,
                    "content": json.dumps(tool_result, ensure_ascii=False),
                }
            )
            log.info("Tool called: %s args=%s", fn_name, args)

    return {
        "summary": "Maksimum tool-calling turuna ulasildi.",
        "evidence": [],
        "root_cause": "Belirsiz",
        "recommended_actions": ["Sorguyu daraltip tekrar deneyin."],
        "confidence": 0.2,
    }


def _normalize_chat_output(raw: dict[str, Any]) -> ChatResponse:
    summary = str(raw.get("summary", "Sonuc olusturulamadi."))
    evidence = raw.get("evidence", [])
    if not isinstance(evidence, list):
        evidence = [{"note": str(evidence)}]
    root_cause = str(raw.get("root_cause", "Belirsiz"))
    recommended_actions = raw.get("recommended_actions", [])
    if not isinstance(recommended_actions, list):
        recommended_actions = [str(recommended_actions)]
    confidence = raw.get("confidence", 0.4)
    try:
        confidence_f = float(confidence)
    except Exception:
        confidence_f = 0.4
    confidence_f = max(0.0, min(1.0, confidence_f))
    return ChatResponse(
        summary=summary,
        evidence=evidence,
        root_cause=root_cause,
        recommended_actions=[str(x) for x in recommended_actions],
        confidence=confidence_f,
    )


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/")
def root() -> dict[str, str]:
    return {"message": "Telecom NOC API is running"}


@app.get("/overview/summary")
def overview_summary_endpoint(
    window_min: int = Query(default=60, ge=5, le=1440),
):
    try:
        return get_homepage_summary_service(window_min=window_min)
    except RuntimeError as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/overview/regions")
def overview_regions_endpoint(
    window_min: int = Query(default=60, ge=5, le=1440),
    top_n: int = Query(default=5, ge=1, le=10),
):
    try:
        return get_region_risk_ranking_service(window_min=window_min, top_n=top_n)
    except RuntimeError as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/overview/events")
def overview_events_endpoint(
    window_min: int = Query(default=60, ge=5, le=1440),
    limit: int = Query(default=12, ge=3, le=30),
):
    try:
        return get_recent_event_stream_service(window_min=window_min, limit=limit)
    except RuntimeError as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/regions/detail")
def region_detail_endpoint(
    region: str,
    window_min: int = Query(default=30, ge=5, le=1440),
    limit: int = Query(default=8, ge=3, le=20),
):
    try:
        return get_region_detail_service(region=region, window_min=window_min, limit=limit)
    except RuntimeError as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/metrics")
def metrics_endpoint(
    cell_id: str,
    slice_type: str | None = None,
    since: str | None = None,
    limit: int = Query(default=10, ge=1, le=500),
):
    try:
        return get_metrics_service(
            cell_id=cell_id, slice_type=slice_type, since=since, limit=limit
        )
    except RuntimeError as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/anomalies")
def anomalies_endpoint(
    cell_id: str | None = None,
    region: str | None = None,
    severity: str | None = None,
    only_anomalies: bool = True,
    limit: int = Query(default=50, ge=1, le=1000),
):
    try:
        return get_anomalies_service(
            cell_id=cell_id,
            region=region,
            severity=severity,
            only_anomalies=only_anomalies,
            limit=limit,
        )
    except RuntimeError as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/faults")
def faults_endpoint(
    fault_id: int | None = None,
    cell_id: str | None = None,
    region: str | None = None,
    severity: str | None = None,
    resolved: bool | None = None,
    window_min: int | None = Query(default=None, ge=5, le=1440),
    limit: int = Query(default=50, ge=1, le=1000),
):
    try:
        return get_faults_service(
            fault_id=fault_id,
            cell_id=cell_id,
            region=region,
            severity=severity,
            resolved=resolved,
            window_min=window_min,
            limit=limit,
        )
    except RuntimeError as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/alarms/summary")
def alarms_summary_endpoint(
    window_min: int = Query(default=30, ge=5, le=1440),
):
    try:
        return get_alarm_summary_service(window_min=window_min)
    except RuntimeError as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/alarms/detail/{fault_id}")
def alarm_detail_endpoint(
    fault_id: int,
    context_window_min: int = Query(default=30, ge=5, le=1440),
    context_limit: int = Query(default=6, ge=1, le=20),
):
    try:
        return get_alarm_detail_service(
            fault_id=fault_id,
            context_window_min=context_window_min,
            context_limit=context_limit,
        )
    except RuntimeError as e:
        raise HTTPException(status_code=404, detail=str(e))


@app.get("/complaints")
def complaints_endpoint(
    cell_id: str | None = None,
    region: str | None = None,
    since: str | None = None,
    limit: int = Query(default=50, ge=1, le=1000),
):
    try:
        return get_complaints_service(
            cell_id=cell_id, region=region, since=since, limit=limit
        )
    except RuntimeError as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/stations")
def stations_endpoint(
    cell_id: str | None = None,
    region: str | None = None,
    status: str | None = None,
    limit: int = Query(default=50, ge=1, le=1000),
):
    try:
        return get_station_service(
            cell_id=cell_id, region=region, status=status, limit=limit
        )
    except RuntimeError as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/chat", response_model=ChatResponse)
def chat_endpoint(payload: ChatRequest):
    msg = payload.message.strip()
    if not msg:
        raise HTTPException(status_code=400, detail="message bos olamaz")
    try:
        raw = _run_llm_tool_loop(msg, payload.limit)
        return _normalize_chat_output(raw)
    except Exception as e:
        log.exception("chat tool-calling failed")
        raise HTTPException(status_code=500, detail=f"Chat akisi hatasi: {e}")
