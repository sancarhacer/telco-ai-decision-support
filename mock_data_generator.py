from __future__ import annotations

import json
import logging
import random
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

import psycopg2
import psycopg2.extras

from config import DB_CONFIG

log = logging.getLogger(__name__)

STATE_FILE = Path(".simulation_state.json")
INCIDENT_TYPES = ("CONGESTION", "FIBER_CUT", "RADIO_ISSUE", "SLICE_BOTTLENECK")
TICK_SECONDS = 30
INCIDENT_DURATION_TICKS = 30  # 15 minutes
COMPLAINT_START_TICKS = 14    # ~7 minutes
FAULT_CREATE_TICKS = 20       # ~10 minutes
COMPLAINT_MESSAGES = {
    "connection_drop": [
        "Baglantim surekli kopuyor.",
        "Internet arada gidip geliyor.",
    ],
    "high_latency": [
        "Oyunlarda ping cok yuksek.",
        "Goruntulu konusmada gecikme var.",
    ],
    "slow_internet": [
        "Internet hizi cok dusuk.",
        "Sayfalar cok yavas aciliyor.",
    ],
    "weak_signal": [
        "Telefon cekmiyor.",
        "Bulundugum bolgede sinyal cok zayif.",
    ],
    "high_load": [
        "Aksam saatlerinde internet cok yavasliyor.",
        "Yogun saatlerde baglanti kalitesi dusuyor.",
    ],
    "general_quality": [
        "Son zamanlarda baglanti kalitesi dustu.",
    ],
}


@dataclass
class Incident:
    incident_id: str
    incident_type: str
    region: str
    started_tick: int
    end_tick: int
    fault_id: int | None = None


def _load_state() -> dict[str, Any]:
    if not STATE_FILE.exists():
        return {"tick": 0, "active_incidents": [], "next_incident_id": 1}
    try:
        return json.loads(STATE_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {"tick": 0, "active_incidents": [], "next_incident_id": 1}


def _save_state(state: dict[str, Any]) -> None:
    STATE_FILE.write_text(json.dumps(state, ensure_ascii=True, indent=2), encoding="utf-8")


def get_base_stations(conn) -> list[dict[str, Any]]:
    with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute(
            """
            SELECT cell_id, region, status
            FROM base_stations
            WHERE LOWER(status) = 'active'
            ORDER BY cell_id
            """
        )
        return list(cur.fetchall())


def group_cells_by_region(stations: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    grouped: dict[str, list[dict[str, Any]]] = {}
    for row in stations:
        grouped.setdefault(row["region"], []).append(row)
    return grouped


def _hourly_load_profile(hour: int) -> float:
    profile = {
        0: 0.12,
        1: 0.10,
        2: 0.09,
        3: 0.08,
        4: 0.08,
        5: 0.10,
        6: 0.24,
        7: 0.48,
        8: 0.62,
        9: 0.56,
        10: 0.50,
        11: 0.54,
        12: 0.70,
        13: 0.74,
        14: 0.60,
        15: 0.56,
        16: 0.64,
        17: 0.76,
        18: 0.84,
        19: 0.89,
        20: 0.91,
        21: 0.78,
        22: 0.58,
        23: 0.38,
    }
    return profile.get(hour, 0.5)


def _jitter(value: float, pct: float) -> float:
    return value * (1 + random.uniform(-pct, pct))


def generate_region_baseline(region: str, tick: int, now: datetime) -> dict[str, float]:
    random.seed(f"{region}-{tick // 10}")
    base_load = _hourly_load_profile(now.hour)
    load = min(0.95, max(0.08, _jitter(base_load, 0.12)))
    packet_loss = max(0.1, min(7.0, _jitter(0.25 + (load**2) * 4, 0.25)))
    latency = max(8.0, _jitter(12 + load * 72 + packet_loss * 2.5, 0.10))
    rsrp = _jitter(-86.0, 0.04)
    rsrq = _jitter(-10.0, 0.08)
    throughput = max(5.0, _jitter(165 - load * 105 - packet_loss * 2.2, 0.10))
    users = max(5, int(_jitter(load * 210, 0.10)))
    return {
        "load_pct": load * 100,
        "packet_loss_pct": packet_loss,
        "latency_ms": latency,
        "rsrp_dbm": rsrp,
        "rsrq_db": rsrq,
        "throughput_mbps": throughput,
        "connected_users": users,
    }


def maybe_start_incident(state: dict[str, Any], regions: list[str]) -> None:
    if state.get("active_incidents"):
        return
    if not regions:
        return
    # Deterministic cycle: if no active incident, immediately start a new one.
    region = random.choice(regions)
    is_first_incident = state["next_incident_id"] == 1
    incident_type = "FIBER_CUT" if is_first_incident else random.choice(INCIDENT_TYPES)
    incident_id = f"INC_{state['next_incident_id']:06d}"
    state["next_incident_id"] += 1
    start_tick = state["tick"]
    state["active_incidents"] = [
        {
            "incident_id": incident_id,
            "incident_type": incident_type,
            "region": region,
            "started_tick": start_tick,
            "end_tick": start_tick + INCIDENT_DURATION_TICKS,
            "fault_id": None,
            "force_critical": is_first_incident,
        }
    ]
    log.info("Incident started: %s %s %s", incident_id, incident_type, region)


def update_active_incidents(state: dict[str, Any]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    active = []
    resolved = []
    for inc in state.get("active_incidents", []):
        if state["tick"] >= inc["end_tick"]:
            resolved.append(inc)
        else:
            active.append(inc)
    state["active_incidents"] = active
    return active, resolved


def apply_incident_to_metric(metric: dict[str, Any], incident: dict[str, Any], slice_type: str) -> None:
    incident_type = incident["incident_type"]
    force_critical = bool(incident.get("force_critical"))
    if incident_type == "CONGESTION":
        metric["load_pct"] = min(99.0, metric["load_pct"] + random.uniform(12, 25))
        metric["latency_ms"] += random.uniform(60, 160)
        metric["packet_loss_pct"] += random.uniform(2.5, 7.5)
        metric["throughput_mbps"] = max(3.0, metric["throughput_mbps"] - random.uniform(20, 55))
        metric["connected_users"] = int(metric["connected_users"] * random.uniform(1.1, 1.35))
    elif incident_type == "FIBER_CUT":
        metric["packet_loss_pct"] = max(metric["packet_loss_pct"], random.uniform(12, 22))
        metric["throughput_mbps"] = min(metric["throughput_mbps"], random.uniform(1.5, 10))
        metric["latency_ms"] = max(metric["latency_ms"], random.uniform(220, 620))
    elif incident_type == "RADIO_ISSUE":
        metric["rsrp_dbm"] = min(metric["rsrp_dbm"], random.uniform(-120, -109))
        metric["rsrq_db"] = min(metric["rsrq_db"], random.uniform(-28, -18))
        metric["throughput_mbps"] = max(3.0, metric["throughput_mbps"] - random.uniform(18, 50))
        metric["latency_ms"] += random.uniform(20, 90)
        metric["packet_loss_pct"] += random.uniform(1.0, 5.0)
    elif incident_type == "SLICE_BOTTLENECK" and slice_type == "URLLC":
        metric["latency_ms"] = max(metric["latency_ms"], random.uniform(90, 260))
        metric["packet_loss_pct"] = max(metric["packet_loss_pct"], random.uniform(3, 11))
        metric["throughput_mbps"] = max(3.0, metric["throughput_mbps"] - random.uniform(8, 30))

    if force_critical:
        # Guarantee CRITICAL thresholds used by anomaly_detector severity rules.
        metric["packet_loss_pct"] = max(metric["packet_loss_pct"], random.uniform(16, 24))
        metric["latency_ms"] = max(metric["latency_ms"], random.uniform(320, 650))
        metric["throughput_mbps"] = min(metric["throughput_mbps"], random.uniform(1.0, 8.0))


def generate_cell_metric(cell: dict[str, Any], baseline: dict[str, float], incident: dict[str, Any] | None) -> dict[str, Any]:
    slice_type = random.choices(["eMBB", "URLLC", "mMTC"], weights=[0.65, 0.25, 0.10], k=1)[0]
    metric = {
        "cell_id": cell["cell_id"],
        "slice_type": slice_type,
        "load_pct": max(5.0, min(100.0, _jitter(baseline["load_pct"], 0.06))),
        "packet_loss_pct": max(0.0, min(30.0, _jitter(baseline["packet_loss_pct"], 0.22))),
        "latency_ms": max(3.0, _jitter(baseline["latency_ms"], 0.10)),
        "rsrp_dbm": _jitter(baseline["rsrp_dbm"], 0.05),
        "rsrq_db": _jitter(baseline["rsrq_db"], 0.10),
        "throughput_mbps": max(1.0, _jitter(baseline["throughput_mbps"], 0.12)),
        "connected_users": max(1, int(_jitter(float(baseline["connected_users"]), 0.12))),
    }
    if incident:
        apply_incident_to_metric(metric, incident, slice_type)

    # relational consistency nudges
    load_factor = metric["load_pct"] / 100.0
    metric["latency_ms"] = max(metric["latency_ms"], 8 + load_factor * 65 + metric["packet_loss_pct"] * 1.8)
    metric["throughput_mbps"] = max(
        1.0,
        metric["throughput_mbps"] - load_factor * 10 - max(0.0, (-100 - metric["rsrp_dbm"])) * 0.2,
    )
    metric["connected_users"] = max(metric["connected_users"], int(load_factor * 180))
    return metric


def insert_network_metrics_batch(conn, metrics: list[dict[str, Any]], recorded_at: datetime) -> int:
    rows = [
        (
            m["cell_id"],
            m["slice_type"],
            round(m["rsrp_dbm"], 2),
            round(m["rsrq_db"], 2),
            round(m["throughput_mbps"], 2),
            round(m["latency_ms"], 2),
            round(m["packet_loss_pct"], 3),
            int(m["connected_users"]),
            round(m["load_pct"], 2),
            recorded_at,
        )
        for m in metrics
    ]
    with conn.cursor() as cur:
        cur.executemany(
            """
            INSERT INTO network_metrics
            (cell_id, slice_type, rsrp_dbm, rsrq_db, throughput_mbps, latency_ms,
             packet_loss_pct, connected_users, load_pct, recorded_at)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            """,
            rows,
        )
    return len(rows)


def _table_columns(conn, table_name: str) -> set[str]:
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT column_name
            FROM information_schema.columns
            WHERE table_schema='public' AND table_name=%s
            """,
            (table_name,),
        )
        return {r[0] for r in cur.fetchall()}


def create_fault_if_needed(conn, incident: dict[str, Any]) -> int | None:
    cols = _table_columns(conn, "faults")
    if "cell_id" not in cols:
        return None

    with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute(
            """
            SELECT cell_id
            FROM base_stations
            WHERE region = %s AND LOWER(status)='active'
            ORDER BY cell_id
            LIMIT 1
            """,
            (incident["region"],),
        )
        row = cur.fetchone()
        if not row:
            return None
        cell_id = row["cell_id"]

        if "resolved" in cols:
            cur.execute(
                """
                SELECT id FROM faults
                WHERE cell_id=%s AND fault_type=%s AND resolved=FALSE
                ORDER BY created_at DESC
                LIMIT 1
                """,
                (cell_id, incident["incident_type"]),
            )
            open_fault = cur.fetchone()
            if open_fault:
                return int(open_fault["id"])

        severity = "CRITICAL" if incident["incident_type"] in ("FIBER_CUT", "RADIO_ISSUE") else "MAJOR"
        message = f"Simulated incident {incident['incident_id']} ({incident['incident_type']}) in {incident['region']}"
        insert_cols = ["cell_id", "severity", "fault_type", "message"]
        values: list[Any] = [cell_id, severity, incident["incident_type"], message]
        if "resolved" in cols:
            insert_cols.append("resolved")
            values.append(False)
        if "created_at" in cols:
            insert_cols.append("created_at")
            values.append(datetime.now())

        placeholders = ", ".join(["%s"] * len(values))
        col_names = ", ".join(insert_cols)
        cur.execute(
            f"INSERT INTO faults ({col_names}) VALUES ({placeholders}) RETURNING id",
            tuple(values),
        )
        new_id = int(cur.fetchone()["id"])
        return new_id


def _has_serious_anomaly_for_region(conn, region: str) -> bool:
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT 1
                FROM anomaly_results ar
                JOIN base_stations bs ON bs.cell_id = ar.cell_id
                WHERE bs.region = %s
                  AND ar.algorithm = 'combined'
                  AND ar.is_anomaly = TRUE
                  AND ar.severity IN ('CRITICAL', 'MAJOR')
                  AND ar.metric_recorded_at >= NOW() - INTERVAL '10 minutes'
                LIMIT 1
                """,
                (region,),
            )
            return cur.fetchone() is not None
    except Exception:
        return False


def _complaint_category(metric: dict[str, Any]) -> str:
    if metric["packet_loss_pct"] > 8:
        return "connection_drop"
    if metric["latency_ms"] > 120:
        return "high_latency"
    if metric["throughput_mbps"] < 15:
        return "slow_internet"
    if metric["rsrp_dbm"] < -110 or metric["rsrq_db"] < -18:
        return "weak_signal"
    if metric["load_pct"] > 88:
        return "high_load"
    return "general_quality"


def create_complaints_if_needed(
    conn,
    incident: dict[str, Any],
    metrics: list[dict[str, Any]],
    tick: int,
) -> int:
    if tick - incident["started_tick"] < COMPLAINT_START_TICKS:
        return 0

    cols = _table_columns(conn, "complaints")
    required = {"customer_id", "region", "issue"}
    if not required.issubset(cols):
        return 0

    rows = []
    for metric in metrics:
        if random.random() > 0.25:
            continue
        category = _complaint_category(metric)
        issue = random.choice(COMPLAINT_MESSAGES[category])
        customer_id = f"CUST_{incident['region'][:3].upper()}_{random.randint(1000, 9999)}"
        row: dict[str, Any] = {"customer_id": customer_id, "region": incident["region"], "issue": issue}
        if "cell_id" in cols:
            row["cell_id"] = metric["cell_id"]
        if "created_at" in cols:
            row["created_at"] = datetime.now()
        rows.append(row)

    # very low probability background complaints from healthy zones
    if random.random() < 0.02:
        rows.append(
            {
                "customer_id": f"CUST_GEN_{random.randint(1000, 9999)}",
                "region": incident["region"],
                "issue": random.choice(COMPLAINT_MESSAGES["general_quality"]),
                **({"created_at": datetime.now()} if "created_at" in cols else {}),
            }
        )

    if not rows:
        return 0

    insert_cols = list(rows[0].keys())
    values = [tuple(r.get(col) for col in insert_cols) for r in rows]
    placeholders = ", ".join(["%s"] * len(insert_cols))
    col_names = ", ".join(insert_cols)
    with conn.cursor() as cur:
        psycopg2.extras.execute_batch(
            cur,
            f"INSERT INTO complaints ({col_names}) VALUES ({placeholders})",
            values,
            page_size=200,
        )
    return len(rows)


def resolve_incident_if_needed(conn, incident: dict[str, Any]) -> None:
    if not incident.get("fault_id"):
        return
    cols = _table_columns(conn, "faults")
    updates = []
    values: list[Any] = []
    if "resolved" in cols:
        updates.append("resolved = TRUE")
    if "resolved_at" in cols:
        updates.append("resolved_at = %s")
        values.append(datetime.now())
    if "closed_at" in cols:
        updates.append("closed_at = %s")
        values.append(datetime.now())
    if "status" in cols:
        updates.append("status = %s")
        values.append("closed")
    if not updates:
        return
    values.append(incident["fault_id"])
    with conn.cursor() as cur:
        cur.execute(f"UPDATE faults SET {', '.join(updates)} WHERE id = %s", tuple(values))


def _incident_for_region(active_incidents: list[dict[str, Any]], region: str) -> dict[str, Any] | None:
    for inc in active_incidents:
        if inc["region"] == region:
            return inc
    return None


def generate_mock_data_tick() -> int:
    state = _load_state()
    state["tick"] += 1
    now = datetime.now()

    with psycopg2.connect(**DB_CONFIG) as conn:
        conn.autocommit = False
        stations = get_base_stations(conn)
        grouped = group_cells_by_region(stations)
        regions = list(grouped.keys())

        maybe_start_incident(state, regions)
        active_incidents, resolved_incidents = update_active_incidents(state)

        metrics: list[dict[str, Any]] = []
        incident_metrics_map: dict[str, list[dict[str, Any]]] = {}

        for region, cells in grouped.items():
            baseline = generate_region_baseline(region, state["tick"], now)
            incident = _incident_for_region(active_incidents, region)
            for cell in cells:
                metric = generate_cell_metric(cell, baseline, incident)
                metrics.append(metric)
                if incident:
                    incident_metrics_map.setdefault(incident["incident_id"], []).append(metric)

        inserted_count = insert_network_metrics_batch(conn, metrics, now)
        conn.commit()

        for inc in active_incidents:
            incident_age = state["tick"] - inc["started_tick"]
            if (
                inc.get("fault_id") is None
                and incident_age >= FAULT_CREATE_TICKS
                and _has_serious_anomaly_for_region(conn, inc["region"])
            ):
                fault_id = create_fault_if_needed(conn, inc)
                if fault_id:
                    inc["fault_id"] = fault_id
            region_metrics = incident_metrics_map.get(inc["incident_id"], [])
            if region_metrics:
                created = create_complaints_if_needed(conn, inc, region_metrics, state["tick"])
                if created:
                    log.info(
                        "Complaints created for %s: %s",
                        inc["incident_id"],
                        created,
                    )

        for inc in resolved_incidents:
            resolve_incident_if_needed(conn, inc)
            log.info("Incident resolved: %s", inc["incident_id"])

        conn.commit()

    _save_state(state)
    return inserted_count
