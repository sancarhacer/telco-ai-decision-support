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
            "description": "Network hataları ve arızaları sorgular. Kullanım: hata, fault, arıza, problem sorguları için.",
            "parameters": {
                "type": "object",
                "properties": {
                    "cell_id": {"type": "string", "description": "CELL_XXX veya all"},
                    "region": {
                        "type": "string",
                        "description": "Bölge adı (Buca, Konak, vb.) veya all",
                    },
                    "severity": {
                        "type": "string",
                        "description": "CRITICAL/MAJOR/MINOR/WARNING/all",
                    },
                    "fault_type": {
                        "type": "string",
                        "description": "Fault tipi veya all",
                    },
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
            "description": "Kullanıcı şikayetlerini sorgular. Kullanım: şikayet, complaint, müşteri sorguları için.",
            "parameters": {
                "type": "object",
                "properties": {
                    "cell_id": {"type": "string"},
                    "region": {
                        "type": "string",
                        "description": "Bölge adı (Buca, Konak, vb.)",
                    },
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
            "description": "Metrik anomalilerini sorgular. Kullanım: anomali, anormal durum, performans sorunu sorguları için.",
            "parameters": {
                "type": "object",
                "properties": {
                    "cell_id": {"type": "string"},
                    "region": {
                        "type": "string",
                        "description": "Bölge adı (Buca, Konak, vb.)",
                    },
                    "severity": {"type": "string"},
                    "only_anomalies": {
                        "anyOf": [{"type": "boolean"}, {"type": "string"}],
                        "description": "true: sadece anomaliler",
                    },
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
            "description": "Network performans metriklerini (throughput, latency, packet loss) sorgular. Kullanım: performans, metrik, hız, gecikme sorguları için.",
            "parameters": {
                "type": "object",
                "properties": {
                    "cell_id": {"type": "string", "description": "CELL_XXX veya all"},
                    "region": {
                        "type": "string",
                        "description": "Bölge adı (Buca, Konak, vb.) veya all",
                    },
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
            "description": "Baz istasyonlarının bilgilerini (cell ID, bölge, durum) sorgular. Kullanım: istasyon bilgisi, cell bilgisi sorguları için.",
            "parameters": {
                "type": "object",
                "properties": {
                    "cell_id": {"type": "string", "description": "CELL_XXX veya all"},
                    "region": {
                        "type": "string",
                        "description": "Bölge adı (Buca, Konak, vb.) veya all",
                    },
                    "status": {"type": "string"},
                    "limit": {"anyOf": [{"type": "integer"}, {"type": "string"}]},
                },
            },
        },
    },
]


def _tool_dispatch(
    name: str, args: dict[str, Any], default_limit: int
) -> dict[str, Any]:
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
                "Sen bir telecom ağ operasyon merkezi asistanısın. Türkçe konuş. "
                "\n"
                "KRİTİK: HER SORUDA MUTLAKA TOOL ÇAĞIR!\n"
                "Asla tahmin yapma, her zaman tool sonucuna göre cevap ver.\n"
                "\n"
                "TOOL SEÇİM KURALLARI (ZORUNLU):\n"
                "- 'anomali' kelimesi → get_anomalies({region, only_anomalies: true})\n"
                "- 'hata/fault/arıza' kelimesi → get_faults({region, resolved: 'false'})\n"
                "- 'şikayet' kelimesi → get_complaints({region})\n"
                "- 'metrik/performans' kelimesi → get_metrics({cell_id veya region})\n"
                "- 'cell/istasyon' bilgisi → get_stations({cell_id veya region})\n"
                "\n"
                "PARAMETRE KURALLARI:\n"
                "- region: Bölge adı string olarak (örn: 'Karşıyaka', 'Konak')\n"
                "- cell_id: Cell string olarak (örn: 'CELL_017')\n"
                "- window_min: SADECE SAYI (örn: 30, 60, 120) - '1h' YAZMA!\n"
                "- limit: SADECE SAYI (örn: 10, 20)\n"
                "- resolved: SADECE 'true' veya 'false' string olarak\n"
                "- only_anomalies: SADECE true veya false (string değil)\n"
                "\n"
                "TOOL SONUCU YORUMLAMA:\n"
                "1. count > 0 → DETAYLI AÇIKLAMA YAP!\n"
                "   - Metrikse: BÜTÜN metriklerin adını ve değerini listele\n"
                "   - Faultsa: Kaç tane, hangi severity, cell ID'leri, fault tipleri\n"
                "   - Şikayetse: Kaç tane, hangi konular, örnekler\n"
                "   - Anomaliyse: Kaç tane, hangi metrikler, severity seviyeleri\n"
                "2. count = 0 → 'Veri bulunamadı' de\n"
                "3. ASLA sadece 'var' veya 'yok' deme, detay ver!\n"
                "4. Özet değil, TAM BİLGİ ver (minimum 3-4 cümle)!\n"
                "\n"
                "METRİK FORMATI:\n"
                "Metrik_Adı değer (örn: RSRP_DBM -89.7)\n"
                "\n"
                "SADECE bu tool'ları kullan: get_faults, get_complaints, get_anomalies, get_metrics, get_stations\n"
                "\n"
                "ÖNEMLİ: Final cevabın SADECE bu JSON olmalı, başka metin olmasın:\n"
                "{\n"
                '  "summary": "Detaylı bulgu açıklaması burada",\n'
                '  "evidence": [],\n'
                '  "root_cause": "N/A",\n'
                '  "recommended_actions": [],\n'
                '  "confidence": 0.8\n'
                "}\n"
                "JSON dışında HİÇBİR ŞEY yazma!"
            ),
        },
        {"role": "user", "content": user_message},
    ]

    for _ in range(5):  # 5 tura çıkarıldı
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
            parsed = None

            # 1. Direkt JSON parse dene
            try:
                parsed = json.loads(raw)
            except json.JSONDecodeError:
                pass

            # 2. JSON bloğu ara (```json veya tek başına {})
            if not parsed:
                import re

                # Code block içinde JSON
                json_match = re.search(
                    r"```(?:json)?\s*(\{.*?\})\s*```", raw, re.DOTALL
                )
                if not json_match:
                    # Tek JSON objesi
                    json_match = re.search(
                        r'(\{[^{}]*"summary"[^{}]*\})', raw, re.DOTALL
                    )

                if json_match:
                    try:
                        parsed = json.loads(json_match.group(1))
                    except json.JSONDecodeError:
                        pass

            # 3. Hala başarısız - güvenli fallback
            if not parsed:
                # Raw text içindeki JSON değerlerini elle çıkar
                summary_match = re.search(r'"summary":\s*"([^"]+)"', raw)
                confidence_match = re.search(r'"confidence":\s*([\d.]+)', raw)

                parsed = {
                    "summary": (
                        summary_match.group(1)
                        if summary_match
                        else "Sonuç oluşturulamadı."
                    ),
                    "evidence": [],
                    "root_cause": "N/A",
                    "recommended_actions": [],
                    "confidence": (
                        float(confidence_match.group(1)) if confidence_match else 0.5
                    ),
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
        "summary": "Sorgunuz için yeterli bilgi bulunamadı veya sorgu çok karmaşık.",
        "evidence": [],
        "root_cause": "Veri yetersiz",
        "recommended_actions": [
            "Daha spesifik bir soru sorun (örn: 'Cell 10 için hata var mı?')",
            "Belirli bir bölge veya zaman aralığı belirtin",
        ],
        "confidence": 0.2,
    }


def _normalize_chat_output(raw: dict[str, Any]) -> ChatResponse:
    summary = str(raw.get("summary", "Yanıt oluşturulamadı."))
    evidence = raw.get("evidence", [])

    # Evidence'ı normalize et - her elemanın dict olduğundan emin ol
    if not isinstance(evidence, list):
        evidence = [{"note": str(evidence)}]
    else:
        normalized_evidence = []
        for item in evidence:
            if isinstance(item, dict):
                normalized_evidence.append(item)
            elif isinstance(item, str):
                # String ise {"note": "..."} formatına çevir
                normalized_evidence.append({"note": item})
            else:
                normalized_evidence.append({"note": str(item)})
        evidence = normalized_evidence

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
        return get_region_detail_service(
            region=region, window_min=window_min, limit=limit
        )
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
            cell_id=cell_id,
            region=region,
            severity=severity,
            resolved=resolved,
            limit=limit,
            fault_id=fault_id,
            # # cell_id=cell_id,
            # region=region,
            # severity=severity,
            # resolved=resolved,
            # window_min=window_min,
            # limit=limit,
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
