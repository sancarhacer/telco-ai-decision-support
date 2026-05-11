import os
import re
from datetime import date, datetime
from typing import Any

import psycopg2
import psycopg2.extras
from config import DB_CONFIG


KNOWN_REGIONS = [
    "Bornova",
    "Konak",
    "Karsiyaka",
    "Buca",
    "Cigli",
    "Bayrakli",
    "Gaziemir",
    "Menemen",
    "Torbali",
    "Kemalpasa",
    "Karabaglar",
    "Urla",
    "Balcova",
    "Narlidere",
    "Guzelbahce",
    "Seferihisar",
    "Menderes",
    "Aliaga",
    "Cesme",
    "Selcuk",
    "Foca",
    "Karaburun",
    "Tire",
    "Odemis",
    "Kiraz",
    "Beydag",
    "Kinik",
    "Dikili",
    "Bergama",
    "Bayindir",
]


def _serialize_value(value: Any) -> Any:
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    return value


def _serialize_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [{k: _serialize_value(v) for k, v in row.items()} for row in rows]


def query_rows(sql: str, params: tuple[Any, ...] = ()) -> list[dict[str, Any]]:
    try:
        with psycopg2.connect(**DB_CONFIG) as conn:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                cur.execute(sql, params)
                return list(cur.fetchall())
    except Exception as e:
        raise RuntimeError(f"Veritabani Hatasi: {e}")


def get_metrics_service(
    cell_id: str,
    slice_type: str | None = None,
    since: str | None = None,
    limit: int = 10,
) -> dict[str, Any]:
    where = ["nm.cell_id = %s"]
    params: list[Any] = [cell_id]
    if slice_type:
        where.append("nm.slice_type = %s")
        params.append(slice_type)
    if since:
        where.append("nm.recorded_at >= %s")
        params.append(since)
    params.append(limit)
    sql = f"""
    SELECT nm.id, nm.cell_id, nm.slice_type, nm.latency_ms, nm.packet_loss_pct,
           nm.throughput_mbps, nm.load_pct, nm.rsrp_dbm, nm.rsrq_db,
           nm.connected_users, nm.recorded_at
    FROM network_metrics nm
    WHERE {' AND '.join(where)}
    ORDER BY nm.recorded_at DESC
    LIMIT %s
    """
    rows = _serialize_rows(query_rows(sql, tuple(params)))
    return {
        "cell_id": cell_id,
        "slice_type": slice_type,
        "since": since,
        "limit": limit,
        "count": len(rows),
        "items": rows,
    }


def get_anomalies_service(
    cell_id: str | None = None,
    region: str | None = None,
    severity: str | None = None,
    only_anomalies: bool = True,
    limit: int = 50,
) -> dict[str, Any]:
    where = ["ar.algorithm = 'combined'"]
    params: list[Any] = []
    if only_anomalies:
        where.append("ar.is_anomaly = TRUE")
    if cell_id:
        where.append("ar.cell_id = %s")
        params.append(cell_id)
    if region:
        where.append("LOWER(bs.region) = LOWER(%s)")
        params.append(region)
    if severity:
        where.append("ar.severity = %s")
        params.append(severity)
    params.append(limit)
    sql = f"""
    SELECT ar.id, ar.cell_id, ar.metric_id, ar.is_anomaly, ar.anomaly_score,
           ar.triggered_by, ar.severity, ar.root_cause, ar.metric_recorded_at,
           ar.detected_at, bs.region
    FROM anomaly_results ar
    JOIN base_stations bs ON bs.cell_id = ar.cell_id
    WHERE {' AND '.join(where)}
    ORDER BY ar.metric_recorded_at DESC
    LIMIT %s
    """
    rows = _serialize_rows(query_rows(sql, tuple(params)))
    return {
        "filters": {
            "cell_id": cell_id,
            "region": region,
            "severity": severity,
            "only_anomalies": only_anomalies,
            "limit": limit,
        },
        "count": len(rows),
        "items": rows,
    }


def get_faults_service(
    cell_id: str | None = None,
    region: str | None = None,
    resolved: bool | None = None,
    limit: int = 50,
    group_by_region: bool = False,
) -> dict[str, Any]:
    where = ["1=1"]
    params: list[Any] = []
    if cell_id:
        where.append("f.cell_id = %s")
        params.append(cell_id)
    if region:
        where.append("LOWER(bs.region) = LOWER(%s)")
        params.append(region)
    if resolved is not None:
        where.append("f.resolved = %s")
        params.append(resolved)

    if group_by_region:
        sql = f"""
        SELECT bs.region, COUNT(*) as fault_count,
               SUM(CASE WHEN f.severity='CRITICAL' THEN 1 ELSE 0 END) as critical,
               SUM(CASE WHEN f.severity='MAJOR' THEN 1 ELSE 0 END) as major,
               SUM(CASE WHEN f.severity='MINOR' THEN 1 ELSE 0 END) as minor
        FROM faults f
        JOIN base_stations bs ON bs.cell_id = f.cell_id
        WHERE {' AND '.join(where)}
        GROUP BY bs.region
        ORDER BY fault_count DESC
        LIMIT %s
        """
        params.append(limit)
        rows = _serialize_rows(query_rows(sql, tuple(params)))
        return {
            "filters": {"group_by": "region", "resolved": resolved, "limit": limit},
            "count": len(rows),
            "grouped": True,
            "items": rows,
        }

    params.append(limit)
    sql = f"""
    SELECT f.id, f.cell_id, bs.region, f.severity, f.fault_type, f.message,
           f.resolved, f.created_at, f.resolved_at
    FROM faults f
    JOIN base_stations bs ON bs.cell_id = f.cell_id
    WHERE {' AND '.join(where)}
    ORDER BY f.created_at DESC
    LIMIT %s
    """
    rows = _serialize_rows(query_rows(sql, tuple(params)))
    return {
        "filters": {
            "cell_id": cell_id,
            "region": region,
            "resolved": resolved,
            "limit": limit,
        },
        "count": len(rows),
        "grouped": False,
        "items": rows,
    }


def get_complaints_service(
    cell_id: str | None = None,
    region: str | None = None,
    since: str | None = None,
    limit: int = 50,
    group_by_issue: bool = False,
) -> dict[str, Any]:
    where = ["1=1"]
    params: list[Any] = []
    if cell_id:
        where.append("c.cell_id = %s")
        params.append(cell_id)
    if region:
        where.append("LOWER(c.region) = LOWER(%s)")
        params.append(region)
    if since:
        where.append("c.created_at >= %s")
        params.append(since)

    if group_by_issue:
        sql = f"""
        SELECT c.issue, COUNT(*) as complaint_count,
               MIN(c.created_at) as first_seen,
               MAX(c.created_at) as last_seen
        FROM complaints c
        WHERE {' AND '.join(where)}
        GROUP BY c.issue
        ORDER BY complaint_count DESC
        LIMIT %s
        """
        params.append(limit)
        rows = _serialize_rows(query_rows(sql, tuple(params)))
        return {
            "filters": {"cell_id": cell_id, "region": region, "limit": limit},
            "count": len(rows),
            "grouped": True,
            "items": rows,
        }

    params.append(limit)
    sql = f"""
    SELECT c.id, c.customer_id, c.region, c.issue, c.cell_id, c.created_at
    FROM complaints c
    WHERE {' AND '.join(where)}
    ORDER BY c.created_at DESC
    LIMIT %s
    """
    rows = _serialize_rows(query_rows(sql, tuple(params)))
    return {
        "filters": {
            "cell_id": cell_id,
            "region": region,
            "since": since,
            "limit": limit,
        },
        "count": len(rows),
        "grouped": False,
        "items": rows,
    }


def get_station_service(
    cell_id: str | None = None,
    region: str | None = None,
    status: str | None = None,
    limit: int = 50,
) -> dict[str, Any]:
    where = ["1=1"]
    params: list[Any] = []
    if cell_id:
        where.append("bs.cell_id = %s")
        params.append(cell_id)
    if region:
        where.append("LOWER(bs.region) = LOWER(%s)")
        params.append(region)
    if status:
        where.append("LOWER(bs.status) = LOWER(%s)")
        params.append(status)
    params.append(limit)
    sql = f"""
    SELECT bs.cell_id, bs.region, bs.lat, bs.lng, bs.status
    FROM base_stations bs
    WHERE {' AND '.join(where)}
    ORDER BY bs.cell_id
    LIMIT %s
    """
    rows = _serialize_rows(query_rows(sql, tuple(params)))
    return {
        "filters": {
            "cell_id": cell_id,
            "region": region,
            "status": status,
            "limit": limit,
        },
        "count": len(rows),
        "items": rows,
    }


def extract_cell_id(text: str) -> str | None:
    # cell_18, CELL_18, Cell_18, CELL_018 gibi formatları yakala
    match = re.search(r"\b(cell[_\s]?\d{1,3})\b", text, flags=re.IGNORECASE)
    if match:
        raw = match.group(1).upper().replace(" ", "_")
        num_match = re.search(r"\d+", raw)
        if num_match:
            num = int(num_match.group())
            return f"CELL_{num:03d}"
    return None


def extract_station_status(text: str) -> str | None:
    """Kullanıcının sorduğu istasyon durumunu tespit eder."""
    m = text.lower()
    if any(
        k in m
        for k in [
            "offline",
            "çevrimdışı",
            "cevrimdisi",
            "kapalı",
            "kapali",
            "inactive",
            "inaktif",
        ]
    ):
        return "offline"
    if any(k in m for k in ["maintenance", "bakım", "bakim", "servis"]):
        return "maintenance"
    if any(
        k in m
        for k in ["online", "aktif", "active", "açık", "acik", "çalışıyor", "calisiyor"]
    ):
        return "active"
    return None


def extract_region(text: str) -> str | None:
    normalized = text.lower()
    for region in KNOWN_REGIONS:
        if region.lower() in normalized:
            return region
    return None


def extract_metric_type(text: str) -> str | None:
    """Kullanıcının sorduğu spesifik metrik tipini tespit eder"""
    m = text.lower()

    # Packet loss
    if any(k in m for k in ["packet loss", "paket kayb", "paket kayıp"]):
        return "packet_loss"

    # Latency / Gecikme
    if any(k in m for k in ["latency", "gecikme", "ping", "delay"]):
        return "latency"

    # Sinyal gücü
    if any(
        k in m for k in ["sinyal", "signal", "rsrp", "rsrq", "güç", "guc", "kalite"]
    ):
        return "signal"

    # Yük / Load
    if any(k in m for k in ["yük", "yuk", "load", "kapasite", "doluluk"]):
        return "load"

    # Throughput / Hız
    if any(k in m for k in ["throughput", "hız", "hiz", "mbps", "bandwidth", "bant"]):
        return "throughput"

    return None


def is_group_by_region_query(text: str) -> bool:
    """'Hangi bölgede en çok X var' gibi gruplama sorgusu mu?"""
    m = text.lower()
    return any(
        k in m
        for k in [
            "hangi bölge",
            "hangi bolge",
            "bölge bazlı",
            "bolge bazli",
            "en çok",
            "en cok",
            "en fazla",
            "sıralama",
            "siralama",
            "karşılaştır",
            "karsilastir",
            "dağılım",
            "dagilim",
        ]
    )


def is_group_by_issue_query(text: str) -> bool:
    """'Ne tür sorunlardan kaynaklanıyor' gibi issue gruplama sorgusu mu?"""
    m = text.lower()
    return any(
        k in m
        for k in [
            "ne tür",
            "ne tur",
            "kaynaklan",
            "neden",
            "sebep",
            "tür",
            "tur",
            "çeşit",
            "cesit",
            "kategori",
        ]
    )


def route_chat(message: str) -> str:
    m = message.lower()

    # Şikayet anahtar kelimeleri — anomaliden ÖNCE kontrol et
    if any(
        k in m
        for k in [
            "şikayet",
            "sikayet",
            "şikayetler",
            "sikayetler",
            "complaint",
            "musteri",
            "müşteri",
            "kullanici",
            "kullanıcı",
            "kaynaklan",
            "neden",
            "ne tür sorun",
            "ne tur sorun",
        ]
    ):
        return "complaints"

    # Arıza/fault anahtar kelimeleri
    if any(k in m for k in ["fault", "ariza", "arıza", "alarm", "kesinti"]):
        return "faults"

    # Anomali ile ilgili anahtar kelimeler
    if any(
        k in m
        for k in [
            "anomali",
            "anomaly",
            "severity",
            "root cause",
            "arttı",
            "artti",
            "düştü",
            "dustu",
            "yükseldi",
            "azaldı",
            "azaldi",
            "packet loss",
            "paket kayb",
            "gecikme",
            "latency",
            "sinyal",
            "sorun",
            "problem",
            "hata",
        ]
    ):
        return "anomalies"

    # İstasyon durumu anahtar kelimeleri
    if any(
        k in m for k in ["station", "istasyon", "status", "offline", "online", "durum"]
    ):
        return "stations"

    # Varsayılan: metrik sorgusu
    return "metrics"


def build_answer(route: str, parsed: dict[str, Any], data: dict[str, Any]) -> str:
    count = data.get("count", 0)
    if route == "metrics":
        target = parsed.get("cell_id") or "hedef"
        return f"{target} icin {count} metrik kaydi bulundu."
    if route == "anomalies":
        target = parsed.get("cell_id") or parsed.get("region") or "secim"
        return f"{target} icin {count} anomali kaydi bulundu."
    if route == "faults":
        target = parsed.get("region") or parsed.get("cell_id") or "secim"
        return f"{target} icin {count} fault kaydi bulundu."
    if route == "complaints":
        target = parsed.get("region") or parsed.get("cell_id") or "secim"
        return f"{target} icin {count} sikayet kaydi bulundu."
    target = parsed.get("region") or parsed.get("cell_id") or "secim"
    return f"{target} icin {count} istasyon kaydi bulundu."
