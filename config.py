import os

from dotenv import load_dotenv

load_dotenv()

DB_CONFIG = {
    "host": os.getenv("DB_HOST", "localhost"),
    "port": int(os.getenv("DB_PORT", "5432")),
    "dbname": os.getenv("DB_NAME", "network_mcp"),
    "user": os.getenv("DB_USER", "postgres"),
    "password": os.getenv("DB_PASSWORD", ""),
}


def _build_db_config(prefix: str, fallback: dict[str, object]) -> dict[str, object]:
    return {
        "host": os.getenv(f"{prefix}_HOST", str(fallback["host"])),
        "port": int(os.getenv(f"{prefix}_PORT", str(fallback["port"]))),
        "dbname": os.getenv(f"{prefix}_NAME", str(fallback["dbname"])),
        "user": os.getenv(f"{prefix}_USER", str(fallback["user"])),
        "password": os.getenv(f"{prefix}_PASSWORD", str(fallback["password"])),
    }


# Logical DB split (with fallback to single DB):
# - TELEMETRY_DB_CONFIG: network_metrics
# - ASSURANCE_DB_CONFIG: faults, anomaly_results
# - CRM_DB_CONFIG: complaints
# - INVENTORY_DB_CONFIG: base_stations
TELEMETRY_DB_CONFIG = _build_db_config("TELEMETRY_DB", DB_CONFIG)
ASSURANCE_DB_CONFIG = _build_db_config("ASSURANCE_DB", DB_CONFIG)
CRM_DB_CONFIG = _build_db_config("CRM_DB", DB_CONFIG)
INVENTORY_DB_CONFIG = _build_db_config("INVENTORY_DB", DB_CONFIG)
