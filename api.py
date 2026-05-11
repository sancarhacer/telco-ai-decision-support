from typing import Any
from contextlib import asynccontextmanager
import logging

from apscheduler.schedulers.background import BackgroundScheduler
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from jobs import job_generate_mock_data, job_run_anomaly_detection

from services import (
    build_answer,
    extract_cell_id,
    extract_metric_type,
    extract_region,
    extract_station_status,
    is_group_by_region_query,
    is_group_by_issue_query,
    get_anomalies_service,
    get_complaints_service,
    get_faults_service,
    get_metrics_service,
    get_station_service,
    route_chat,
)

log = logging.getLogger(__name__)
scheduler = BackgroundScheduler(timezone="Europe/Istanbul")


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


app = FastAPI(title="Telecom NOC API", version="1.1.0", lifespan=lifespan)
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
    route: str
    parsed: dict[str, Any]
    data: dict[str, Any]
    answer: str
    metric_type: str | None = None  # Yeni alan


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/")
def root() -> dict[str, str]:
    return {"message": "Telecom NOC API is running"}


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
    cell_id: str | None = None,
    region: str | None = None,
    resolved: bool | None = None,
    limit: int = Query(default=50, ge=1, le=1000),
):
    try:
        return get_faults_service(
            cell_id=cell_id, region=region, resolved=resolved, limit=limit
        )
    except RuntimeError as e:
        raise HTTPException(status_code=500, detail=str(e))


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

    route = route_chat(msg)
    cell_id = extract_cell_id(msg)
    region = extract_region(msg)
    metric_type = extract_metric_type(msg)
    station_status = extract_station_status(msg)
    group_by_region = is_group_by_region_query(msg)
    group_by_issue = is_group_by_issue_query(msg)
    parsed = {
        "cell_id": cell_id,
        "region": region,
        "limit": payload.limit,
        "metric_type": metric_type,
        "station_status": station_status,
        "group_by_region": group_by_region,
        "group_by_issue": group_by_issue,
    }

    try:
        if route == "metrics":
            if not cell_id:
                if region:
                    data = get_station_service(region=region, limit=payload.limit)
                    route = "stations"
                else:
                    raise HTTPException(
                        status_code=400,
                        detail="Metrik sorgusu için mesajda CELL_XXX (örn: CELL_018 veya cell_18) belirtin.",
                    )
            else:
                data = get_metrics_service(cell_id=cell_id, limit=payload.limit)
        elif route == "anomalies":
            data = get_anomalies_service(
                cell_id=cell_id, region=region, only_anomalies=True, limit=payload.limit
            )
        elif route == "faults":
            data = get_faults_service(
                cell_id=cell_id,
                region=region,
                resolved=False,
                limit=payload.limit,
                group_by_region=group_by_region,
            )
        elif route == "complaints":
            data = get_complaints_service(
                cell_id=cell_id,
                region=region,
                limit=payload.limit,
                group_by_issue=group_by_issue,
            )
        else:
            data = get_station_service(
                cell_id=cell_id,
                region=region,
                status=station_status,
                limit=payload.limit,
            )
    except RuntimeError as e:
        raise HTTPException(status_code=500, detail=str(e))

    answer = build_answer(route, parsed, data)
    return ChatResponse(
        route=route, parsed=parsed, data=data, answer=answer, metric_type=metric_type
    )
