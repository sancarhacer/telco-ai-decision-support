import os
import re
from datetime import date, datetime
from typing import Any

import psycopg2
import psycopg2.extras
from config import (
    ASSURANCE_DB_CONFIG,
    CRM_DB_CONFIG,
    DB_CONFIG,
    INVENTORY_DB_CONFIG,
    TELEMETRY_DB_CONFIG,
)


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


DB_MAP: dict[str, dict[str, Any]] = {
    "default": DB_CONFIG,
    "telemetry": TELEMETRY_DB_CONFIG,
    "assurance": ASSURANCE_DB_CONFIG,
    "crm": CRM_DB_CONFIG,
    "inventory": INVENTORY_DB_CONFIG,
}


def query_rows_on(db_key: str, sql: str, params: tuple[Any, ...] = ()) -> list[dict[str, Any]]:
    cfg = DB_MAP.get(db_key, DB_CONFIG)
    try:
        with psycopg2.connect(**cfg) as conn:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                cur.execute(sql, params)
                return list(cur.fetchall())
    except Exception as e:
        raise RuntimeError(f"Veritabani Hatasi ({db_key}): {e}")


def _inventory_cells_by_region(region: str) -> list[str]:
    sql = """
    SELECT cell_id
    FROM base_stations
    WHERE LOWER(region) = LOWER(%s)
    """
    rows = query_rows_on("inventory", sql, (region,))
    return [str(r["cell_id"]) for r in rows]


def _in_clause(values: list[Any]) -> tuple[str, tuple[Any, ...]]:
    placeholders = ", ".join(["%s"] * len(values))
    return f"({placeholders})", tuple(values)


def _as_filter(value: Any) -> Any | None:
    if value is None:
        return None
    if isinstance(value, str):
        cleaned = value.strip()
        if cleaned == "" or cleaned.lower() == "all":
            return None
        return cleaned
    return value


def _resolve_cell_scope(cell_id: str | None, region: str | None) -> list[str] | None:
    scoped_cell = _as_filter(cell_id)
    scoped_region = _as_filter(region)
    if scoped_cell:
        return [str(scoped_cell)]
    if scoped_region:
        cells = _inventory_cells_by_region(str(scoped_region))
        return cells if cells else []
    return None


def _parse_resolved_filter(resolved: str | bool | None) -> bool | None:
    parsed = _as_filter(resolved)
    if parsed is None:
        return None
    if isinstance(parsed, bool):
        return parsed
    lowered = str(parsed).lower()
    if lowered in ("true", "1", "yes", "open_false"):
        return True
    if lowered in ("false", "0", "no", "open_true"):
        return False
    raise RuntimeError("resolved filtresi icin all|true|false kullanin.")


def get_faults_atomic_service(
    cell_id: str = "all",
    region: str = "all",
    severity: str = "all",
    fault_type: str = "all",
    resolved: str | bool = "all",
    window_min: int = 60,
    limit: int = 200,
) -> dict[str, Any]:
    where = ["created_at >= NOW() - make_interval(mins => %s)"]
    params: list[Any] = [window_min]

    cells = _resolve_cell_scope(cell_id, region)
    if cells == []:
        return {"filters": {"cell_id": cell_id, "region": region, "window_min": window_min, "limit": limit}, "count": 0, "items": []}
    if cells:
        in_sql, in_params = _in_clause(cells)
        where.append(f"cell_id IN {in_sql}")
        params.extend(in_params)

    sev = _as_filter(severity)
    if sev:
        where.append("severity = %s")
        params.append(sev)
    f_type = _as_filter(fault_type)
    if f_type:
        where.append("fault_type = %s")
        params.append(f_type)
    resolved_bool = _parse_resolved_filter(resolved)
    if resolved_bool is not None:
        where.append("resolved = %s")
        params.append(resolved_bool)

    params.append(limit)
    rows = query_rows_on(
        "assurance",
        f"""
        SELECT id, cell_id, severity, fault_type, message, resolved, created_at, resolved_at
        FROM faults
        WHERE {' AND '.join(where)}
        ORDER BY created_at DESC
        LIMIT %s
        """,
        tuple(params),
    )
    return {
        "filters": {
            "cell_id": cell_id,
            "region": region,
            "severity": severity,
            "fault_type": fault_type,
            "resolved": resolved,
            "window_min": window_min,
            "limit": limit,
        },
        "count": len(rows),
        "items": _serialize_rows(rows),
    }


def get_complaints_atomic_service(
    cell_id: str = "all",
    region: str = "all",
    issue: str = "all",
    window_min: int = 60,
    limit: int = 200,
) -> dict[str, Any]:
    where = ["created_at >= NOW() - make_interval(mins => %s)"]
    params: list[Any] = [window_min]

    scoped_cell = _as_filter(cell_id)
    if scoped_cell:
        where.append("cell_id = %s")
        params.append(scoped_cell)
    scoped_region = _as_filter(region)
    if scoped_region:
        where.append("LOWER(region) = LOWER(%s)")
        params.append(scoped_region)
    scoped_issue = _as_filter(issue)
    if scoped_issue:
        where.append("issue ILIKE %s")
        params.append(f"%{scoped_issue}%")

    params.append(limit)
    rows = query_rows_on(
        "crm",
        f"""
        SELECT id, customer_id, region, issue, cell_id, created_at
        FROM complaints
        WHERE {' AND '.join(where)}
        ORDER BY created_at DESC
        LIMIT %s
        """,
        tuple(params),
    )
    return {
        "filters": {
            "cell_id": cell_id,
            "region": region,
            "issue": issue,
            "window_min": window_min,
            "limit": limit,
        },
        "count": len(rows),
        "items": _serialize_rows(rows),
    }


def get_anomalies_atomic_service(
    cell_id: str = "all",
    region: str = "all",
    severity: str = "all",
    only_anomalies: bool = True,
    window_min: int = 60,
    limit: int = 200,
) -> dict[str, Any]:
    where = [
        "metric_recorded_at >= NOW() - make_interval(mins => %s)",
        "algorithm = 'combined'",
    ]
    params: list[Any] = [window_min]

    if only_anomalies:
        where.append("is_anomaly = TRUE")

    cells = _resolve_cell_scope(cell_id, region)
    if cells == []:
        return {"filters": {"cell_id": cell_id, "region": region, "window_min": window_min, "limit": limit}, "count": 0, "items": []}
    if cells:
        in_sql, in_params = _in_clause(cells)
        where.append(f"cell_id IN {in_sql}")
        params.extend(in_params)

    sev = _as_filter(severity)
    if sev:
        where.append("severity = %s")
        params.append(sev)

    params.append(limit)
    rows = query_rows_on(
        "assurance",
        f"""
        SELECT id, cell_id, metric_id, is_anomaly, anomaly_score, triggered_by,
               severity, root_cause, metric_recorded_at, detected_at
        FROM anomaly_results
        WHERE {' AND '.join(where)}
        ORDER BY metric_recorded_at DESC
        LIMIT %s
        """,
        tuple(params),
    )
    return {
        "filters": {
            "cell_id": cell_id,
            "region": region,
            "severity": severity,
            "only_anomalies": only_anomalies,
            "window_min": window_min,
            "limit": limit,
        },
        "count": len(rows),
        "items": _serialize_rows(rows),
    }


def get_metrics_atomic_service(
    cell_id: str = "all",
    region: str = "all",
    slice_type: str = "all",
    window_min: int = 60,
    limit: int = 200,
) -> dict[str, Any]:
    where = ["recorded_at >= NOW() - make_interval(mins => %s)"]
    params: list[Any] = [window_min]

    cells = _resolve_cell_scope(cell_id, region)
    if cells == []:
        return {"filters": {"cell_id": cell_id, "region": region, "window_min": window_min, "limit": limit}, "count": 0, "items": []}
    if cells:
        in_sql, in_params = _in_clause(cells)
        where.append(f"cell_id IN {in_sql}")
        params.extend(in_params)

    s_type = _as_filter(slice_type)
    if s_type:
        where.append("slice_type = %s")
        params.append(s_type)

    params.append(limit)
    rows = query_rows_on(
        "telemetry",
        f"""
        SELECT id, cell_id, slice_type, rsrp_dbm, rsrq_db, throughput_mbps,
               latency_ms, packet_loss_pct, connected_users, load_pct, recorded_at
        FROM network_metrics
        WHERE {' AND '.join(where)}
        ORDER BY recorded_at DESC
        LIMIT %s
        """,
        tuple(params),
    )
    return {
        "filters": {
            "cell_id": cell_id,
            "region": region,
            "slice_type": slice_type,
            "window_min": window_min,
            "limit": limit,
        },
        "count": len(rows),
        "items": _serialize_rows(rows),
    }


def get_stations_atomic_service(
    cell_id: str = "all",
    region: str = "all",
    status: str = "all",
    limit: int = 200,
) -> dict[str, Any]:
    where = ["1=1"]
    params: list[Any] = []

    scoped_cell = _as_filter(cell_id)
    if scoped_cell:
        where.append("cell_id = %s")
        params.append(scoped_cell)
    scoped_region = _as_filter(region)
    if scoped_region:
        where.append("LOWER(region) = LOWER(%s)")
        params.append(scoped_region)
    scoped_status = _as_filter(status)
    if scoped_status:
        where.append("LOWER(status) = LOWER(%s)")
        params.append(scoped_status)

    params.append(limit)
    rows = query_rows_on(
        "inventory",
        f"""
        SELECT cell_id, region, lat, lng, status
        FROM base_stations
        WHERE {' AND '.join(where)}
        ORDER BY cell_id
        LIMIT %s
        """,
        tuple(params),
    )
    return {
        "filters": {"cell_id": cell_id, "region": region, "status": status, "limit": limit},
        "count": len(rows),
        "items": _serialize_rows(rows),
    }


def get_homepage_summary_service(window_min: int = 60) -> dict[str, Any]:
    faults_summary = query_rows_on(
        "assurance",
        """
        SELECT
            COUNT(*) FILTER (WHERE resolved = FALSE AND severity = 'CRITICAL') AS critical_open_faults,
            MAX(created_at) AS latest_fault_at
        FROM faults
        WHERE created_at >= NOW() - make_interval(mins => %s)
        """,
        (window_min,),
    )[0]

    anomalies_summary = query_rows_on(
        "assurance",
        """
        SELECT
            COUNT(*) FILTER (WHERE is_anomaly = TRUE AND algorithm = 'combined') AS anomaly_count,
            MAX(metric_recorded_at) AS latest_anomaly_at
        FROM anomaly_results
        WHERE metric_recorded_at >= NOW() - make_interval(mins => %s)
        """,
        (window_min,),
    )[0]

    complaints_summary = query_rows_on(
        "crm",
        """
        SELECT
            COUNT(*) AS complaint_count,
            MAX(created_at) AS latest_complaint_at
        FROM complaints
        WHERE created_at >= NOW() - make_interval(mins => %s)
        """,
        (window_min,),
    )[0]

    metrics_summary = query_rows_on(
        "telemetry",
        """
        SELECT MAX(recorded_at) AS latest_metric_at
        FROM network_metrics
        WHERE recorded_at >= NOW() - make_interval(mins => %s)
        """,
        (window_min,),
    )[0]

    inventory_rows = query_rows_on("inventory", "SELECT cell_id, region FROM base_stations")
    cell_to_region = {
        str(row["cell_id"]): str(row["region"])
        for row in inventory_rows
        if row.get("cell_id") is not None and row.get("region") is not None
    }
    region_summary: dict[str, dict[str, Any]] = {}

    def ensure_region(region_name: str) -> dict[str, Any]:
        return region_summary.setdefault(
            region_name,
            {
                "region": region_name,
                "faults": 0,
                "anomalies": 0,
                "complaints": 0,
                "risk_score": 0.0,
            },
        )

    fault_regions = query_rows_on(
        "assurance",
        """
        SELECT cell_id, COUNT(*) AS cnt
        FROM faults
        WHERE created_at >= NOW() - make_interval(mins => %s)
          AND resolved = FALSE
        GROUP BY cell_id
        """,
        (window_min,),
    )
    for row in fault_regions:
        region_name = cell_to_region.get(str(row["cell_id"]))
        if not region_name:
            continue
        ensure_region(region_name)["faults"] += int(row["cnt"] or 0)

    anomaly_regions = query_rows_on(
        "assurance",
        """
        SELECT cell_id, COUNT(*) AS cnt
        FROM anomaly_results
        WHERE metric_recorded_at >= NOW() - make_interval(mins => %s)
          AND is_anomaly = TRUE
          AND algorithm = 'combined'
        GROUP BY cell_id
        """,
        (window_min,),
    )
    for row in anomaly_regions:
        region_name = cell_to_region.get(str(row["cell_id"]))
        if not region_name:
            continue
        ensure_region(region_name)["anomalies"] += int(row["cnt"] or 0)

    complaint_regions = query_rows_on(
        "crm",
        """
        SELECT region, COUNT(*) AS cnt
        FROM complaints
        WHERE created_at >= NOW() - make_interval(mins => %s)
        GROUP BY region
        """,
        (window_min,),
    )
    for row in complaint_regions:
        region_name = str(row["region"])
        ensure_region(region_name)["complaints"] += int(row["cnt"] or 0)

    ranked_regions: list[dict[str, Any]] = []
    for item in region_summary.values():
        item["risk_score"] = round(
            (item["faults"] * 0.5) + (item["anomalies"] * 0.3) + (item["complaints"] * 0.2),
            2,
        )
        ranked_regions.append(item)

    ranked_regions.sort(key=lambda item: item["risk_score"], reverse=True)
    affected_region_count = sum(
        1
        for item in ranked_regions
        if item["faults"] > 0 or item["anomalies"] > 0 or item["complaints"] > 0
    )

    latest_values = [
        faults_summary.get("latest_fault_at"),
        anomalies_summary.get("latest_anomaly_at"),
        complaints_summary.get("latest_complaint_at"),
        metrics_summary.get("latest_metric_at"),
    ]
    latest_timestamp = max((value for value in latest_values if value is not None), default=None)

    return {
        "window_min": window_min,
        "critical_open_faults": int(faults_summary.get("critical_open_faults") or 0),
        "anomaly_count": int(anomalies_summary.get("anomaly_count") or 0),
        "complaint_count": int(complaints_summary.get("complaint_count") or 0),
        "affected_region_count": affected_region_count,
        "riskiest_region": ranked_regions[0] if ranked_regions else None,
        "last_updated_at": _serialize_value(latest_timestamp),
    }


def get_region_risk_ranking_service(window_min: int = 60, top_n: int = 5) -> dict[str, Any]:
    inventory_rows = query_rows_on("inventory", "SELECT cell_id, region FROM base_stations")
    cell_to_region = {
        str(row["cell_id"]): str(row["region"])
        for row in inventory_rows
        if row.get("cell_id") is not None and row.get("region") is not None
    }

    summary: dict[str, dict[str, Any]] = {}

    def ensure_region(region_name: str) -> dict[str, Any]:
        return summary.setdefault(
            region_name,
            {
                "region": region_name,
                "faults": 0,
                "anomalies": 0,
                "complaints": 0,
                "risk_score": 0.0,
            },
        )

    faults = query_rows_on(
        "assurance",
        """
        SELECT cell_id, COUNT(*) AS cnt
        FROM faults
        WHERE created_at >= NOW() - make_interval(mins => %s)
          AND resolved = FALSE
        GROUP BY cell_id
        """,
        (window_min,),
    )
    for row in faults:
        region_name = cell_to_region.get(str(row["cell_id"]))
        if region_name:
            ensure_region(region_name)["faults"] += int(row["cnt"] or 0)

    anomalies = query_rows_on(
        "assurance",
        """
        SELECT cell_id, COUNT(*) AS cnt
        FROM anomaly_results
        WHERE metric_recorded_at >= NOW() - make_interval(mins => %s)
          AND is_anomaly = TRUE
          AND algorithm = 'combined'
        GROUP BY cell_id
        """,
        (window_min,),
    )
    for row in anomalies:
        region_name = cell_to_region.get(str(row["cell_id"]))
        if region_name:
            ensure_region(region_name)["anomalies"] += int(row["cnt"] or 0)

    complaints = query_rows_on(
        "crm",
        """
        SELECT region, COUNT(*) AS cnt
        FROM complaints
        WHERE created_at >= NOW() - make_interval(mins => %s)
        GROUP BY region
        """,
        (window_min,),
    )
    for row in complaints:
        region_name = str(row["region"])
        ensure_region(region_name)["complaints"] += int(row["cnt"] or 0)

    ranked = list(summary.values())
    for item in ranked:
        item["risk_score"] = round(
            (item["faults"] * 0.5) + (item["anomalies"] * 0.3) + (item["complaints"] * 0.2),
            2,
        )

    ranked.sort(key=lambda item: item["risk_score"], reverse=True)
    items = [item for item in ranked if item["risk_score"] > 0][:top_n]
    return {
        "window_min": window_min,
        "top_n": top_n,
        "count": len(items),
        "items": items,
    }


def get_recent_event_stream_service(window_min: int = 60, limit: int = 12) -> dict[str, Any]:
    faults = query_rows(
        """
        SELECT f.cell_id, bs.region, f.severity, f.fault_type, f.created_at
        FROM faults f
        JOIN base_stations bs ON bs.cell_id = f.cell_id
        WHERE f.created_at >= NOW() - make_interval(mins => %s)
        ORDER BY f.created_at DESC
        LIMIT %s
        """,
        (window_min, limit),
    )

    complaints = query_rows_on(
        "crm",
        """
        SELECT cell_id, region, issue, created_at
        FROM complaints
        WHERE created_at >= NOW() - make_interval(mins => %s)
        ORDER BY created_at DESC
        LIMIT %s
        """,
        (window_min, limit),
    )

    anomalies = query_rows(
        """
        SELECT ar.cell_id, bs.region, ar.severity, ar.root_cause, ar.metric_recorded_at
        FROM anomaly_results ar
        JOIN base_stations bs ON bs.cell_id = ar.cell_id
        WHERE ar.metric_recorded_at >= NOW() - make_interval(mins => %s)
          AND ar.is_anomaly = TRUE
          AND ar.algorithm = 'combined'
        ORDER BY ar.metric_recorded_at DESC
        LIMIT %s
        """,
        (window_min, limit),
    )

    items: list[dict[str, Any]] = []
    for row in faults:
        items.append(
            {
                "event_type": "fault",
                "cell_id": row["cell_id"],
                "region": row["region"],
                "severity": row["severity"],
                "label": row["fault_type"],
                "timestamp": _serialize_value(row["created_at"]),
            }
        )
    for row in complaints:
        items.append(
            {
                "event_type": "complaint",
                "cell_id": row.get("cell_id"),
                "region": row.get("region"),
                "severity": "INFO",
                "label": row.get("issue") or "Complaint",
                "timestamp": _serialize_value(row["created_at"]),
            }
        )
    for row in anomalies:
        items.append(
            {
                "event_type": "anomaly",
                "cell_id": row["cell_id"],
                "region": row["region"],
                "severity": row["severity"] or "WARNING",
                "label": row.get("root_cause") or "Anomaly detected",
                "timestamp": _serialize_value(row["metric_recorded_at"]),
            }
        )

    items.sort(key=lambda item: item["timestamp"] or "", reverse=True)
    items = items[:limit]
    return {
        "window_min": window_min,
        "count": len(items),
        "items": items,
    }


def get_region_detail_service(region: str, window_min: int = 30, limit: int = 8) -> dict[str, Any]:
    region_name = (region or "").strip()
    if not region_name:
        raise RuntimeError("region is required")

    faults = get_faults_atomic_service(
        region=region_name,
        resolved="all",
        window_min=window_min,
        limit=limit,
    )
    anomalies = get_anomalies_atomic_service(
        region=region_name,
        severity="all",
        only_anomalies=True,
        window_min=window_min,
        limit=limit,
    )
    complaints = get_complaints_atomic_service(
        region=region_name,
        issue="all",
        window_min=window_min,
        limit=limit,
    )
    stations = get_stations_atomic_service(
        region=region_name,
        status="all",
        limit=200,
    )

    station_items = stations.get("items", [])
    active_station_count = sum(
        1 for item in station_items if str(item.get("status", "")).lower() == "active"
    )

    severity_mix: dict[str, int] = {"CRITICAL": 0, "MAJOR": 0, "MINOR": 0, "WARNING": 0}
    for item in faults.get("items", []):
        sev = str(item.get("severity") or "").upper()
        if sev in severity_mix:
            severity_mix[sev] += 1
    for item in anomalies.get("items", []):
        sev = str(item.get("severity") or "").upper()
        if sev in severity_mix:
            severity_mix[sev] += 1

    return {
        "region": region_name,
        "window_min": window_min,
        "summary": {
            "fault_count": int(faults.get("count") or 0),
            "anomaly_count": int(anomalies.get("count") or 0),
            "complaint_count": int(complaints.get("count") or 0),
            "station_count": int(stations.get("count") or 0),
            "active_station_count": active_station_count,
            "severity_mix": severity_mix,
        },
        "faults": faults.get("items", []),
        "anomalies": anomalies.get("items", []),
        "complaints": complaints.get("items", []),
        "stations": station_items[:20],
    }


# def get_noc_overview_service(window_min: int = 15) -> dict[str, Any]:
#     faults_sql = """
#     SELECT
#       COUNT(*) FILTER (WHERE resolved = FALSE) AS open_faults,
#       COUNT(*) FILTER (WHERE resolved = FALSE AND severity = 'CRITICAL') AS critical_open_faults
#     FROM faults
#     WHERE created_at >= NOW() - make_interval(mins => %s)
#     """
#     anomalies_sql = """
#     SELECT
#       COUNT(*) AS total_rows,
#       COUNT(*) FILTER (WHERE is_anomaly = TRUE) AS anomaly_rows
#     FROM anomaly_results
#     WHERE metric_recorded_at >= NOW() - make_interval(mins => %s)
#       AND algorithm = 'combined'
#     """
#     complaints_sql = """
#     SELECT COUNT(*) AS complaint_count
#     FROM complaints
#     WHERE created_at >= NOW() - make_interval(mins => %s)
#     """
#     metrics_sql = """
#     SELECT COUNT(*) AS metrics_count
#     FROM network_metrics
#     WHERE recorded_at >= NOW() - make_interval(mins => %s)
#     """
#     f = query_rows_on("assurance", faults_sql, (window_min,))[0]
#     a = query_rows_on("assurance", anomalies_sql, (window_min,))[0]
#     c = query_rows_on("crm", complaints_sql, (window_min,))[0]
#     m = query_rows_on("telemetry", metrics_sql, (window_min,))[0]

#     total_anom = int(a["total_rows"] or 0)
#     anomaly_rows = int(a["anomaly_rows"] or 0)
#     anomaly_rate = (anomaly_rows / total_anom) if total_anom else 0.0

#     return {
#         "window_min": window_min,
#         "open_faults": int(f["open_faults"] or 0),
#         "critical_open_faults": int(f["critical_open_faults"] or 0),
#         "anomaly_rate": round(anomaly_rate, 4),
#         "complaint_count": int(c["complaint_count"] or 0),
#         "metrics_count": int(m["metrics_count"] or 0),
#     }


# def get_region_risk_ranking_service(window_min: int = 60, top_n: int = 10) -> dict[str, Any]:
#     inv = query_rows_on("inventory", "SELECT cell_id, region FROM base_stations")
#     cell_to_region = {str(r["cell_id"]): str(r["region"]) for r in inv}
#     regions = sorted(set(cell_to_region.values()))
#     summary = {r: {"region": r, "faults": 0, "anomalies": 0, "complaints": 0, "risk_score": 0.0} for r in regions}

#     faults = query_rows_on(
#         "assurance",
#         """
#         SELECT cell_id, COUNT(*) AS cnt
#         FROM faults
#         WHERE created_at >= NOW() - make_interval(mins => %s)
#         GROUP BY cell_id
#         """,
#         (window_min,),
#     )
#     anomalies = query_rows_on(
#         "assurance",
#         """
#         SELECT cell_id, COUNT(*) AS cnt
#         FROM anomaly_results
#         WHERE metric_recorded_at >= NOW() - make_interval(mins => %s)
#           AND is_anomaly = TRUE
#           AND algorithm = 'combined'
#         GROUP BY cell_id
#         """,
#         (window_min,),
#     )
#     complaints = query_rows_on(
#         "crm",
#         """
#         SELECT region, COUNT(*) AS cnt
#         FROM complaints
#         WHERE created_at >= NOW() - make_interval(mins => %s)
#         GROUP BY region
#         """,
#         (window_min,),
#     )

#     for row in faults:
#         region = cell_to_region.get(str(row["cell_id"]))
#         if region in summary:
#             summary[region]["faults"] += int(row["cnt"] or 0)
#     for row in anomalies:
#         region = cell_to_region.get(str(row["cell_id"]))
#         if region in summary:
#             summary[region]["anomalies"] += int(row["cnt"] or 0)
#     for row in complaints:
#         region = str(row["region"])
#         if region in summary:
#             summary[region]["complaints"] += int(row["cnt"] or 0)

#     for region_data in summary.values():
#         region_data["risk_score"] = round(
#             (region_data["faults"] * 0.5) + (region_data["anomalies"] * 0.3) + (region_data["complaints"] * 0.2),
#             2,
#         )

#     ranked = sorted(summary.values(), key=lambda x: x["risk_score"], reverse=True)[:top_n]
#     return {"window_min": window_min, "top_n": top_n, "count": len(ranked), "items": ranked}


# def get_cell_health_score_service(cell_id: str, window_min: int = 60) -> dict[str, Any]:
#     metrics = query_rows_on(
#         "telemetry",
#         """
#         SELECT AVG(latency_ms) AS avg_latency,
#                AVG(packet_loss_pct) AS avg_packet_loss,
#                AVG(throughput_mbps) AS avg_throughput,
#                AVG(load_pct) AS avg_load,
#                AVG(rsrp_dbm) AS avg_rsrp,
#                AVG(rsrq_db) AS avg_rsrq
#         FROM network_metrics
#         WHERE cell_id = %s
#           AND recorded_at >= NOW() - make_interval(mins => %s)
#         """,
#         (cell_id, window_min),
#     )[0]
#     faults = query_rows_on(
#         "assurance",
#         """
#         SELECT COUNT(*) FILTER (WHERE resolved = FALSE) AS open_faults
#         FROM faults
#         WHERE cell_id = %s
#           AND created_at >= NOW() - make_interval(mins => %s)
#         """,
#         (cell_id, window_min),
#     )[0]
#     anomalies = query_rows_on(
#         "assurance",
#         """
#         SELECT COUNT(*) AS anomaly_count
#         FROM anomaly_results
#         WHERE cell_id = %s
#           AND metric_recorded_at >= NOW() - make_interval(mins => %s)
#           AND is_anomaly = TRUE
#           AND algorithm = 'combined'
#         """,
#         (cell_id, window_min),
#     )[0]

#     # Simple skeleton scoring (replace with calibrated formula later).
#     score = 100.0
#     score -= min(float(metrics["avg_latency"] or 0) / 5.0, 20)
#     score -= min(float(metrics["avg_packet_loss"] or 0) * 4.0, 20)
#     score -= min(int(faults["open_faults"] or 0) * 10.0, 30)
#     score -= min(int(anomalies["anomaly_count"] or 0) * 2.0, 20)
#     score = max(0.0, round(score, 2))

#     return {
#         "cell_id": cell_id,
#         "window_min": window_min,
#         "health_score": score,
#         "open_faults": int(faults["open_faults"] or 0),
#         "anomaly_count": int(anomalies["anomaly_count"] or 0),
#         "metrics_summary": {k: (round(float(v), 3) if v is not None else None) for k, v in metrics.items()},
#     }


# def get_cross_domain_correlations_service(
#     region: str | None = None,
#     window_min: int = 120,
#     min_severity: str = "MAJOR",
# ) -> dict[str, Any]:
#     sev = (min_severity or "MAJOR").upper()
#     severity_rank = {"WARNING": 1, "MINOR": 2, "MAJOR": 3, "CRITICAL": 4}
#     threshold = severity_rank.get(sev, 1)
#     allowed = [k for k, v in severity_rank.items() if v >= threshold]
#     cell_ids: list[str] | None = None
#     if region:
#         cell_ids = _inventory_cells_by_region(region)
#         if not cell_ids:
#             return {"region": region, "window_min": window_min, "count": 0, "items": []}

#     where_cell = ""
#     params_fault: list[Any] = [window_min]
#     params_anom: list[Any] = [window_min, allowed]
#     params_comp: list[Any] = [window_min]
#     if cell_ids:
#         in_sql, in_params = _in_clause(cell_ids)
#         where_cell = f" AND cell_id IN {in_sql}"
#         params_fault.extend(in_params)
#         params_anom.extend(in_params)
#         params_comp.extend(in_params)

#     faults = query_rows_on(
#         "assurance",
#         f"""
#         SELECT cell_id, COUNT(*) AS cnt
#         FROM faults
#         WHERE created_at >= NOW() - make_interval(mins => %s)
#         {where_cell}
#         GROUP BY cell_id
#         """,
#         tuple(params_fault),
#     )
#     anomalies = query_rows_on(
#         "assurance",
#         f"""
#         SELECT cell_id, COUNT(*) AS cnt
#         FROM anomaly_results
#         WHERE metric_recorded_at >= NOW() - make_interval(mins => %s)
#           AND is_anomaly = TRUE
#           AND algorithm = 'combined'
#           AND severity = ANY(%s::text[])
#           {where_cell}
#         GROUP BY cell_id
#         """,
#         tuple(params_anom),
#     )
#     complaints = query_rows_on(
#         "crm",
#         f"""
#         SELECT cell_id, COUNT(*) AS cnt
#         FROM complaints
#         WHERE created_at >= NOW() - make_interval(mins => %s)
#           AND cell_id IS NOT NULL
#           {where_cell}
#         GROUP BY cell_id
#         """,
#         tuple(params_comp),
#     )

#     f_map = {str(r["cell_id"]): int(r["cnt"] or 0) for r in faults}
#     a_map = {str(r["cell_id"]): int(r["cnt"] or 0) for r in anomalies}
#     c_map = {str(r["cell_id"]): int(r["cnt"] or 0) for r in complaints}
#     cells = set(f_map.keys()) | set(a_map.keys()) | set(c_map.keys())

#     items: list[dict[str, Any]] = []
#     for cell in sorted(cells):
#         f_cnt = f_map.get(cell, 0)
#         a_cnt = a_map.get(cell, 0)
#         c_cnt = c_map.get(cell, 0)
#         signals: list[str] = []
#         if f_cnt > 0:
#             signals.append("fault_present")
#         if a_cnt > 0:
#             signals.append("anomaly_present")
#         if c_cnt > 0:
#             signals.append("complaint_present")
#         if c_cnt == 0:
#             signals.append("no_complaint")
#         if f_cnt == 0:
#             signals.append("no_fault")

#         # Backward-compatible primary label for fast triage.
#         if c_cnt > 0 and f_cnt == 0:
#             corr = "complaint_spike_without_fault"
#         elif f_cnt > 0 and c_cnt == 0:
#             corr = "fault_without_complaints"
#         elif a_cnt > 0 and f_cnt == 0:
#             corr = "anomaly_without_fault"
#         elif f_cnt > 0 and a_cnt > 0 and c_cnt > 0:
#             corr = "fully_correlated"
#         else:
#             corr = "aligned"
#         items.append(
#             {
#                 "cell_id": cell,
#                 "fault_count": f_cnt,
#                 "anomaly_count": a_cnt,
#                 "complaint_count": c_cnt,
#                 "primary_correlation": corr,
#                 "signals": signals,
#             }
#         )

#     return {
#         "region": region,
#         "window_min": window_min,
#         "min_severity": sev,
#         "count": len(items),
#         "items": items,
#     }


# def get_incident_timeline_service(cell_id: str, since: str) -> dict[str, Any]:
#     metrics = query_rows_on(
#         "telemetry",
#         """
#         SELECT 'metric'::text AS event_type, recorded_at AS event_time,
#                json_build_object(
#                  'latency_ms', latency_ms,
#                  'packet_loss_pct', packet_loss_pct,
#                  'throughput_mbps', throughput_mbps,
#                  'load_pct', load_pct
#                ) AS details
#         FROM network_metrics
#         WHERE cell_id = %s AND recorded_at >= %s
#         ORDER BY recorded_at DESC
#         LIMIT 200
#         """,
#         (cell_id, since),
#     )
#     anomalies = query_rows_on(
#         "assurance",
#         """
#         SELECT 'anomaly'::text AS event_type, metric_recorded_at AS event_time,
#                json_build_object(
#                  'severity', severity,
#                  'score', anomaly_score,
#                  'root_cause', root_cause
#                ) AS details
#         FROM anomaly_results
#         WHERE cell_id = %s AND metric_recorded_at >= %s AND algorithm='combined'
#         ORDER BY metric_recorded_at DESC
#         LIMIT 200
#         """,
#         (cell_id, since),
#     )
#     faults = query_rows_on(
#         "assurance",
#         """
#         SELECT 'fault'::text AS event_type, created_at AS event_time,
#                json_build_object(
#                  'severity', severity,
#                  'fault_type', fault_type,
#                  'resolved', resolved,
#                  'message', message
#                ) AS details
#         FROM faults
#         WHERE cell_id = %s AND created_at >= %s
#         ORDER BY created_at DESC
#         LIMIT 200
#         """,
#         (cell_id, since),
#     )
#     complaints = query_rows_on(
#         "crm",
#         """
#         SELECT 'complaint'::text AS event_type, created_at AS event_time,
#                json_build_object(
#                  'issue', issue,
#                  'customer_id', customer_id
#                ) AS details
#         FROM complaints
#         WHERE cell_id = %s AND created_at >= %s
#         ORDER BY created_at DESC
#         LIMIT 200
#         """,
#         (cell_id, since),
#     )

#     timeline = metrics + anomalies + faults + complaints
#     timeline = sorted(timeline, key=lambda r: r["event_time"], reverse=True)
#     return {"cell_id": cell_id, "since": since, "count": len(timeline), "items": _serialize_rows(timeline)}


# def get_slice_sla_breaches_service(slice_type: str | None = None, window_min: int = 60) -> dict[str, Any]:
#     where = ["recorded_at >= NOW() - make_interval(mins => %s)"]
#     params: list[Any] = [window_min]
#     if slice_type:
#         where.append("slice_type = %s")
#         params.append(slice_type)

#     sql = f"""
#     SELECT slice_type,
#            COUNT(*) AS total_samples,
#            COUNT(*) FILTER (WHERE latency_ms > CASE
#              WHEN slice_type='URLLC' THEN 10
#              WHEN slice_type='eMBB' THEN 60
#              ELSE 120 END) AS latency_breaches,
#            COUNT(*) FILTER (WHERE packet_loss_pct > CASE
#              WHEN slice_type='URLLC' THEN 1
#              WHEN slice_type='eMBB' THEN 3
#              ELSE 5 END) AS packet_loss_breaches
#     FROM network_metrics
#     WHERE {' AND '.join(where)}
#     GROUP BY slice_type
#     ORDER BY total_samples DESC
#     """
#     rows = query_rows_on("telemetry", sql, tuple(params))
#     items = []
#     for r in rows:
#         total = int(r["total_samples"] or 0)
#         lat_b = int(r["latency_breaches"] or 0)
#         pl_b = int(r["packet_loss_breaches"] or 0)
#         items.append(
#             {
#                 "slice_type": r["slice_type"],
#                 "total_samples": total,
#                 "latency_breaches": lat_b,
#                 "packet_loss_breaches": pl_b,
#                 "latency_breach_rate": round((lat_b / total) if total else 0.0, 4),
#                 "packet_loss_breach_rate": round((pl_b / total) if total else 0.0, 4),
#             }
#         )
#     return {"window_min": window_min, "slice_type": slice_type, "count": len(items), "items": items}


# def get_recommended_actions_service(target_type: str, target_id: str) -> dict[str, Any]:
#     target_type = target_type.lower().strip()
#     actions: list[str] = []
#     rationale: list[str] = []

#     if target_type == "cell":
#         health = get_cell_health_score_service(cell_id=target_id, window_min=60)
#         if health["open_faults"] > 0:
#             actions.append("Open fault kayitlarini onceliklendir ve saha ekibini yonlendir.")
#             rationale.append("Cell uzerinde acik fault var.")
#         if health["anomaly_count"] > 5:
#             actions.append("Son 60 dk anomaly trendini inceleyip threshold tuning baslat.")
#             rationale.append("Anomaly yogunlugu yuksek.")
#         actions.append("Komsu hucre handover/load durumunu kontrol et.")
#     elif target_type == "region":
#         actions.extend(
#             [
#                 "Bolge risk siralamasina gore ilk 3 hucre icin war-room ac.",
#                 "CRM sikayet tiplerini fault tipleriyle eslestirip runbook tetikle.",
#                 "Backhaul/fiber ve RAN ekipleriyle ortak triage baslat.",
#             ]
#         )
#         rationale.append("Bolgesel olaylarda domainler arasi koordinasyon gerekir.")
#     elif target_type == "fault_type":
#         mapping = {
#             "fiber_cut": "Backhaul link continuity testi ve saha kablo denetimi yap.",
#             "interference": "Frekans taramasi ve dis kaynak girisim analizi yap.",
#             "slice_congestion": "Slice policy ve resource re-allocation uygula.",
#             "hw_failure": "Saha ekip sevki + donanim degisim proseduru baslat.",
#         }
#         actions.append(mapping.get(target_id.lower(), "Genel incident runbook adimlarini uygula."))
#         rationale.append("Fault tipine gore kural tabanli aksiyon.")
#     else:
#         actions.append("Target type desteklenmiyor: cell | region | fault_type kullan.")
#         rationale.append("Gecerli hedef tipi gerekli.")

#     return {
#         "target_type": target_type,
#         "target_id": target_id,
#         "actions": actions,
#         "rationale": rationale,
#     }


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
    fault_id: int | None = None,
    cell_id: str | None = None,
    region: str | None = None,
    severity: str | None = None,
    resolved: bool | None = None,
    window_min: int | None = None,
    limit: int = 50,
    group_by_region: bool = False,
) -> dict[str, Any]:
    where = ["1=1"]
    params: list[Any] = []
    if fault_id is not None:
        where.append("f.id = %s")
        params.append(fault_id)
    if cell_id:
        where.append("f.cell_id = %s")
        params.append(cell_id)
    if region:
        where.append("LOWER(bs.region) = LOWER(%s)")
        params.append(region)
    if severity:
        where.append("f.severity = %s")
        params.append(severity)
    if resolved is not None:
        where.append("f.resolved = %s")
        params.append(resolved)
    if window_min is not None:
        where.append("f.created_at >= NOW() - make_interval(mins => %s)")
        params.append(window_min)

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
            "filters": {
                "group_by": "region",
                "fault_id": fault_id,
                "severity": severity,
                "resolved": resolved,
                "window_min": window_min,
                "limit": limit,
            },
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
            "fault_id": fault_id,
            "cell_id": cell_id,
            "region": region,
            "severity": severity,
            "resolved": resolved,
            "window_min": window_min,
            "limit": limit,
        },
        "count": len(rows),
        "grouped": False,
        "items": rows,
    }


def get_alarm_summary_service(window_min: int = 30) -> dict[str, Any]:
    summary_row = query_rows(
        """
        SELECT
            COUNT(*) FILTER (WHERE resolved = FALSE) AS open_total,
            COUNT(*) FILTER (WHERE resolved = FALSE AND severity = 'CRITICAL') AS open_critical,
            COUNT(*) FILTER (WHERE resolved = FALSE AND severity = 'MAJOR') AS open_major,
            COUNT(*) FILTER (WHERE created_at >= NOW() - make_interval(mins => %s)) AS new_alarm_count
        FROM faults
        """,
        (window_min,),
    )[0]

    busiest_region_rows = query_rows(
        """
        SELECT bs.region, COUNT(*) AS alarm_count
        FROM faults f
        JOIN base_stations bs ON bs.cell_id = f.cell_id
        WHERE f.resolved = FALSE
          AND f.created_at >= NOW() - make_interval(mins => %s)
        GROUP BY bs.region
        ORDER BY alarm_count DESC, bs.region ASC
        LIMIT 1
        """,
        (window_min,),
    )
    busiest_region = busiest_region_rows[0] if busiest_region_rows else None

    latest_alarm_rows = query_rows(
        """
        SELECT MAX(created_at) AS latest_alarm_at
        FROM faults
        WHERE created_at >= NOW() - make_interval(mins => %s)
        """,
        (window_min,),
    )
    latest_alarm_at = latest_alarm_rows[0].get("latest_alarm_at") if latest_alarm_rows else None

    return {
        "window_min": window_min,
        "open_total": int(summary_row.get("open_total") or 0),
        "open_critical": int(summary_row.get("open_critical") or 0),
        "open_major": int(summary_row.get("open_major") or 0),
        "new_alarm_count": int(summary_row.get("new_alarm_count") or 0),
        "busiest_region": busiest_region,
        "last_updated_at": _serialize_value(latest_alarm_at),
    }


def get_alarm_detail_service(
    fault_id: int,
    context_window_min: int = 30,
    context_limit: int = 6,
) -> dict[str, Any]:
    fault_payload = get_faults_service(fault_id=fault_id, limit=1)
    items = fault_payload.get("items", [])
    if not items:
        raise RuntimeError("Alarm kaydi bulunamadi.")

    alarm = items[0]
    cell_id = alarm.get("cell_id")
    region = alarm.get("region")

    related_faults = get_faults_atomic_service(
        cell_id=cell_id or "all",
        resolved="all",
        window_min=context_window_min,
        limit=context_limit + 1,
    ).get("items", [])
    related_faults = [item for item in related_faults if item.get("id") != fault_id][:context_limit]

    related_anomalies = get_anomalies_atomic_service(
        cell_id=cell_id or "all",
        window_min=context_window_min,
        limit=context_limit,
    ).get("items", [])

    related_complaints = get_complaints_atomic_service(
        cell_id=cell_id or "all",
        region=region or "all",
        window_min=context_window_min,
        limit=context_limit,
    ).get("items", [])

    station_payload = get_stations_atomic_service(cell_id=cell_id or "all", limit=1)
    station = station_payload.get("items", [None])[0]

    return {
        "alarm": alarm,
        "context_window_min": context_window_min,
        "related_faults": related_faults,
        "related_anomalies": related_anomalies,
        "related_complaints": related_complaints,
        "station": station,
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
