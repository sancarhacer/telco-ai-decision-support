import psycopg2
import pandas as pd
from mcp.server.fastmcp import FastMCP
from sklearn.ensemble import IsolationForest
from sklearn.preprocessing import StandardScaler
from config import DB_CONFIG

mcp = FastMCP("Telecom_AI_Agent")



def run_query(query, params=None):
    """Parametre hatasını önlemek için güvenli sorgu fonksiyonu."""
    try:
        with psycopg2.connect(**DB_CONFIG) as conn:
            with conn.cursor() as cur:
                # Parametre None ise boş tuple gönderiyoruz
                cur.execute(query, params or ())
                if cur.description:
                    return cur.fetchall()
                return None
    except Exception as e:
        return f"Veritabanı Hatası: {str(e)}"


# --- BÖLGE BAZLI TOOLLAR (Genel Teşhis) ---


@mcp.tool()
def get_region_metrics(region: str):
    """Bölge genelindeki tüm istasyonların özet performansını getirir."""
    sql = """
    SELECT b.cell_id, m.latency_ms, m.rsrp_dbm 
    FROM base_stations b
    JOIN network_metrics m ON b.cell_id = m.cell_id
    WHERE b.region = %s
    """
    return run_query(sql, (region,))


@mcp.tool()
def get_region_complaints(region: str):
    """Bölge bazlı müşteri şikayetlerini listeler."""
    sql = """
    SELECT c.issue, c.cell_id FROM complaints c
    JOIN base_stations b ON c.cell_id = b.cell_id
    WHERE b.region = %s
    """
    return run_query(sql, (region,))


# --- CİHAZ BAZLI TOOLLAR (Derin Analiz) ---


@mcp.tool()
def analyze_specific_cell(cell_id: str):
    sql = """
    SELECT latency_ms, packet_loss_pct, throughput_mbps
    FROM network_metrics
    WHERE cell_id = %s
      AND recorded_at >= NOW() - INTERVAL '7 days'
    """
    data = run_query(sql, (cell_id,))

    if not data or isinstance(data, str):
        return {
            "status": "UNKNOWN",
            "cell_id": cell_id,
            "message": "Yetersiz veri veya sorgu hatası.",
        }

    df = pd.DataFrame(data, columns=["lat", "loss", "speed"])
    df = df.dropna()

    if len(df) < 20:
        return {
            "status": "UNKNOWN",
            "cell_id": cell_id,
            "sample_count": int(len(df)),
            "message": "Model çalıştırmak için en az 20 örnek gerekiyor.",
        }

    scaler = StandardScaler()
    X = scaler.fit_transform(df[["lat", "loss", "speed"]])

    model = IsolationForest(contamination=0.05, random_state=42)
    df["anomaly"] = model.fit_predict(X)

    # decision_function: 0'a yakın normal, negatif değer daha anormal.
    scores = model.decision_function(X)

    anomaly_count = len(df[df["anomaly"] == -1])
    anomaly_ratio = anomaly_count / len(df)

    if anomaly_count == 0:
        return {
            "status": "NORMAL",
            "cell_id": cell_id,
            "sample_count": int(len(df)),
            "anomaly_count": 0,
            "anomaly_ratio": round(float(anomaly_ratio), 4),
            "avg_anomaly_score": None,
            "message": f"NORMAL: {cell_id} stabil.",
        }

    avg_anomaly_score = float(scores[df["anomaly"] == -1].mean())

    if avg_anomaly_score < -0.15:
        status = "CRITICAL"
        message = f"KRİTİK: {cell_id} için şiddetli anomaliler! (Skor: {avg_anomaly_score:.3f})"
    else:
        status = "WARNING"
        message = f"UYARI: {cell_id} için sapmalar var. (Skor: {avg_anomaly_score:.3f})"

    return {
        "status": status,
        "cell_id": cell_id,
        "sample_count": int(len(df)),
        "anomaly_count": int(anomaly_count),
        "anomaly_ratio": round(float(anomaly_ratio), 4),
        "avg_anomaly_score": round(avg_anomaly_score, 4),
        "message": message,
    }


@mcp.tool()
def get_station_status(status: str):
    """Belirli bir durumdaki (aktif, inaktif, bakımda) istasyonları listeler."""
    valid_statuses = ["active", "inactive", "maintenance"]
    if status not in valid_statuses:
        return {"error": f"Geçersiz durum: {status}. Geçerli durumlar: {', '.join(valid_statuses)}"}

    sql = """
    SELECT cell_id, region, status
    FROM base_stations
    WHERE status = %s
    """
    return run_query(sql, (status,))


if __name__ == "__main__":
    mcp.run()
