"""
anomaly_detector.py
────────────────────
network_metrics tablosunu okur,
Isolation Forest + Z-Score çalıştırır,
sonuçları anomaly_results tablosuna yazar.

KULLANIM:
    # Tüm veriyi tara (ilk kurulum)
    python anomaly_detector.py --mode full

    # Sadece son 1 saati tara (periyodik çalıştırma)
    python anomaly_detector.py --mode incremental --hours 1

    # Belirli bölgeyi tara
    python anomaly_detector.py --mode full --region Bornova

BAĞLANTI:
    DB ayarlarını DB_CONFIG sözlüğünden değiştir.
"""

import argparse
import json
import logging
from datetime import datetime, timedelta

import numpy as np
import pandas as pd
import psycopg2
import psycopg2.extras
from sklearn.ensemble import IsolationForest
from sklearn.preprocessing import StandardScaler
from config import DB_CONFIG

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger(__name__)

# ── Veritabanı bağlantı ayarları ──────────────────────────────────────────
# ── Model parametreleri ────────────────────────────────────────────────────
IF_CONTAMINATION  = 0.05   # Isolation Forest: verinin ~%5'i anomali bekleniyor
IF_N_ESTIMATORS   = 100    # ağaç sayısı
IF_RANDOM_STATE   = 42

# Z-Score eşikleri — dokümanındaki normal aralıklardan türetildi
Z_THRESHOLDS = {
    "latency_ms":       3.0,   # 3 sigma üstü anomali
    "packet_loss_pct":  3.0,
    "load_pct":         2.5,   # yük daha hassas
    "throughput_mbps":  3.0,   # düşük throughput da anomali (ters yön)
    "rsrp_dbm":         2.5,   # sinyal gücü
    "rsrq_db":          2.5,   # sinyal kalitesi
}

# Anomali severity kuralları — hangi metrik ne kadar sapıyorsa
SEVERITY_RULES = [
    # (koşul fonksiyonu, severity)
    (lambda r: r["packet_loss_pct"] > 15 or r["latency_ms"] > 300, "CRITICAL"),
    (lambda r: r["packet_loss_pct"] > 8  or r["latency_ms"] > 200
               or r["load_pct"] > 92,                               "MAJOR"),
    (lambda r: r["packet_loss_pct"] > 4  or r["latency_ms"] > 100
               or r["rsrp_dbm"] < -110,                             "MINOR"),
    (lambda r: True,                                                 "WARNING"),
]

# Kök neden kuralları — tetikleyen metriğe göre açıklama üret
ROOT_CAUSE_RULES = [
    (lambda r: r.get("packet_loss_pct", 0) > 15 and r.get("throughput_mbps", 999) < 10,
     "Fiber hat kesintisi veya upstream bağlantı sorunu"),
    (lambda r: r.get("rsrp_dbm", 0) < -110,
     "Radyo modülü arızası veya donanım hatası — sinyal çok zayıf"),
    (lambda r: r.get("rsrq_db", 0) < -20 and r.get("rsrp_dbm", -90) > -105,
     "Frekans müdahalesi (sinyal güçlü ama kalitesi düşük)"),
    (lambda r: r.get("load_pct", 0) > 90 and r.get("latency_ms", 0) > 150,
     "Kapasite aşımı — yoğun kullanım veya etkinlik trafiği"),
    (lambda r: r.get("packet_loss_pct", 0) > 4 and r.get("load_pct", 0) < 70,
     "Kademeli donanım bozulması — yük düşük ama kayıp yüksek"),
    (lambda r: r.get("latency_ms", 0) > 100 and r.get("load_pct", 0) < 60,
     "Dilim bazlı darboğaz veya yönlendirme sorunu"),
    (lambda r: True,
     "Çoklu metrik sapması — detaylı inceleme gerekiyor"),
]

FEATURE_COLS = [
    "latency_ms", "packet_loss_pct", "load_pct",
    "throughput_mbps", "rsrp_dbm", "rsrq_db",
]


# ═══════════════════════════════════════════════════════════════════════════
# VERİTABANI
# ═══════════════════════════════════════════════════════════════════════════

def get_conn():
    return psycopg2.connect(**DB_CONFIG)


def fetch_metrics(conn, region=None, hours=None) -> pd.DataFrame:
    """
    network_metrics tablosundan veri çeker.
    region veya hours filtresi opsiyonel.
    """
    where_clauses = ["nm.latency_ms IS NOT NULL"]
    params = []

    if region:
        where_clauses.append("bs.region = %s")
        params.append(region)

    if hours:
        cutoff = datetime.now() - timedelta(hours=hours)
        where_clauses.append("nm.recorded_at >= %s")
        params.append(cutoff)

    where = "WHERE " + " AND ".join(where_clauses)

    query = f"""
        SELECT
            nm.id,
            nm.cell_id,
            bs.region,
            nm.slice_type,
            nm.latency_ms,
            nm.packet_loss_pct,
            nm.load_pct,
            nm.throughput_mbps,
            nm.rsrp_dbm,
            nm.rsrq_db,
            nm.recorded_at
        FROM network_metrics nm
        JOIN base_stations bs ON nm.cell_id = bs.cell_id
        {where}
        ORDER BY nm.recorded_at
    """
    df = pd.read_sql(query, conn, params=params if params else None)
    log.info(f"Çekilen satır: {len(df):,}  (region={region}, hours={hours})")
    return df


def insert_results(conn, results: list[dict]):
    """anomaly_results tablosuna toplu yazma"""
    if not results:
        return

    sql = """
        INSERT INTO anomaly_results
            (cell_id, metric_id, algorithm, is_anomaly, anomaly_score,
             triggered_by, severity, root_cause, metric_recorded_at)
        VALUES
            (%(cell_id)s, %(metric_id)s, %(algorithm)s, %(is_anomaly)s,
             %(anomaly_score)s, %(triggered_by)s, %(severity)s,
             %(root_cause)s, %(metric_recorded_at)s)
        ON CONFLICT (metric_id, algorithm)
        DO UPDATE SET
            cell_id = EXCLUDED.cell_id,
            is_anomaly = EXCLUDED.is_anomaly,
            anomaly_score = EXCLUDED.anomaly_score,
            triggered_by = EXCLUDED.triggered_by,
            severity = EXCLUDED.severity,
            root_cause = EXCLUDED.root_cause,
            metric_recorded_at = EXCLUDED.metric_recorded_at
    """
    with conn.cursor() as cur:
        psycopg2.extras.execute_batch(cur, sql, results, page_size=500)
    conn.commit()
    log.info(f"  → {len(results):,} satır anomaly_results'a yazıldı")


# ═══════════════════════════════════════════════════════════════════════════
# Z-SCORE MODELİ
# ═══════════════════════════════════════════════════════════════════════════

def run_zscore(df: pd.DataFrame) -> pd.DataFrame:
    """
    Her metrik için Z-Score hesaplar.
    Herhangi bir metrikte eşik aşılırsa is_anomaly=True.
    
    throughput için ters yön: düşük değer anomali (z_score negatif → abs alınır)
    """
    result_rows = []

    # Her cell_id için ayrı istatistik (hücreler arası fark normalleştirilir)
    for cell_id, group in df.groupby("cell_id"):
        stats = {}
        for col in Z_THRESHOLDS:
            stats[col] = {
                "mean": group[col].mean(),
                "std":  group[col].std() if group[col].std() > 0 else 1e-9,
            }

        for _, row in group.iterrows():
            triggered = {}
            max_z = 0.0

            for col, threshold in Z_THRESHOLDS.items():
                z = (row[col] - stats[col]["mean"]) / stats[col]["std"]
                # throughput düşükse anomali (negatif z → abs)
                if col == "throughput_mbps":
                    z = abs(z) if z < 0 else 0
                else:
                    z = abs(z)

                if z > threshold:
                    triggered[col] = round(float(row[col]), 3)
                if z > max_z:
                    max_z = z

            is_anomaly = len(triggered) > 0

            result_rows.append({
                "metric_id":           int(row["id"]),
                "cell_id":             row["cell_id"],
                "algorithm":           "z_score",
                "is_anomaly":          is_anomaly,
                "anomaly_score":       round(max_z, 4),
                "triggered_by":        triggered,
                "metric_recorded_at":  row["recorded_at"],
                "raw":                 row,          # severity/root_cause için
            })

    return pd.DataFrame(result_rows)


# ═══════════════════════════════════════════════════════════════════════════
# ISOLATION FOREST MODELİ
# ═══════════════════════════════════════════════════════════════════════════

def run_isolation_forest(df: pd.DataFrame) -> pd.DataFrame:
    """
    Tüm feature'ları birlikte değerlendiren Isolation Forest.
    Her hücre için ayrı model eğitilir (hücreler arası fark gürültüye dönüşmez).
    
    score_samples() çıktısı: negatif → anomali, sıfıra yakın → normal
    normalize edip 0-1 aralığına çekiyoruz (1 = kesin anomali)
    """
    result_rows = []

    for cell_id, group in df.groupby("cell_id"):
        if len(group) < 10:
            # Çok az veri varsa model güvenilmez, atla
            log.debug(f"  {cell_id}: az veri ({len(group)} satır), atlandı")
            continue

        X = group[FEATURE_COLS].fillna(group[FEATURE_COLS].median())

        scaler = StandardScaler()
        X_scaled = scaler.fit_transform(X)

        model = IsolationForest(
            contamination=IF_CONTAMINATION,
            n_estimators=IF_N_ESTIMATORS,
            random_state=IF_RANDOM_STATE,
        )
        model.fit(X_scaled)

        preds  = model.predict(X_scaled)         # -1 anomali, +1 normal
        scores = model.score_samples(X_scaled)   # negatif → anomali

        # Score normalize et: 0 (normal) → 1 (kesin anomali)
        s_min, s_max = scores.min(), scores.max()
        if s_max > s_min:
            norm_scores = 1 - (scores - s_min) / (s_max - s_min)
        else:
            norm_scores = np.zeros(len(scores))

        for i, (_, row) in enumerate(group.iterrows()):
            is_anomaly = preds[i] == -1

            # Hangi feature en çok saptı? (triggered_by için)
            triggered = {}
            if is_anomaly:
                feat_vals = X.iloc[i]
                feat_means = X.mean()
                feat_stds  = X.std().replace(0, 1e-9)
                for col in FEATURE_COLS:
                    z = abs((feat_vals[col] - feat_means[col]) / feat_stds[col])
                    if z > 1.5:   # 1.5 sigma üstündeyse "katkıda bulundu" say
                        triggered[col] = round(float(feat_vals[col]), 3)

            result_rows.append({
                "metric_id":           int(row["id"]),
                "cell_id":             row["cell_id"],
                "algorithm":           "isolation_forest",
                "is_anomaly":          is_anomaly,
                "anomaly_score":       round(float(norm_scores[i]), 4),
                "triggered_by":        triggered,
                "metric_recorded_at":  row["recorded_at"],
                "raw":                 row,
            })

    return pd.DataFrame(result_rows)


# ═══════════════════════════════════════════════════════════════════════════
# COMBINED: İKİ MODELİ BİRLEŞTİR
# ═══════════════════════════════════════════════════════════════════════════

def combine_results(df_if: pd.DataFrame, df_zs: pd.DataFrame) -> pd.DataFrame:
    """
    Her metric_id için IF ve Z-Score sonuçlarını birleştirir.
    
    Karar mantığı:
      - İkisi de anomali diyorsa → kesin anomali (combined)
      - Sadece biri diyorsa    → şüpheli (yine anomali, ama score düşük)
      - İkisi de normal        → normal
    """
    merged = pd.merge(
        df_if[["metric_id", "cell_id", "is_anomaly", "anomaly_score",
               "triggered_by", "metric_recorded_at", "raw"]],
        df_zs[["metric_id", "is_anomaly", "anomaly_score", "triggered_by"]],
        on="metric_id",
        suffixes=("_if", "_zs"),
    )

    rows = []
    for _, r in merged.iterrows():
        both   = r["is_anomaly_if"] and r["is_anomaly_zs"]
        either = r["is_anomaly_if"] or  r["is_anomaly_zs"]

        # Birleşik skor: IF ağırlığı %60, Z-Score %40
        combined_score = round(
            0.6 * r["anomaly_score_if"] + 0.4 * r["anomaly_score_zs"], 4
        )

        # Triggered_by: iki modelin bulduklarını birleştir
        trig = {**r["triggered_by_if"], **r["triggered_by_zs"]}

        rows.append({
            "metric_id":          r["metric_id"],
            "cell_id":            r["cell_id"],
            "algorithm":          "combined",
            "is_anomaly":         either,
            "anomaly_score":      combined_score,
            "triggered_by":       trig,
            "metric_recorded_at": r["metric_recorded_at"],
            "raw":                r["raw"],
            "both_agree":         both,
        })

    return pd.DataFrame(rows)


# ═══════════════════════════════════════════════════════════════════════════
# SEVERITY + KÖK NEDEN
# ═══════════════════════════════════════════════════════════════════════════

def assign_severity(raw_row) -> str | None:
    if not hasattr(raw_row, "__getitem__"):
        return None
    for condition, severity in SEVERITY_RULES:
        try:
            if condition(raw_row):
                return severity
        except Exception:
            continue
    return "WARNING"


def assign_root_cause(triggered: dict, raw_row) -> str:
    for condition, cause in ROOT_CAUSE_RULES:
        try:
            if condition(raw_row):
                return cause
        except Exception:
            continue
    return "Bilinmeyen anomali kaynağı"


def enrich_results(df_results: pd.DataFrame) -> list[dict]:
    """
    DataFrame'i DB insert formatına çevirir,
    severity ve root_cause ekler.
    """
    records = []
    for _, r in df_results.iterrows():
        raw = r["raw"]

        severity   = assign_severity(raw) if r["is_anomaly"] else None
        root_cause = assign_root_cause(r["triggered_by"], raw) if r["is_anomaly"] else None

        records.append({
            "cell_id":            r["cell_id"],
            "metric_id":          r["metric_id"],
            "algorithm":          r["algorithm"],
            "is_anomaly":         bool(r["is_anomaly"]),
            "anomaly_score":      float(r["anomaly_score"]),
            "triggered_by":       json.dumps(r["triggered_by"], ensure_ascii=False),
            "severity":           severity,
            "root_cause":         root_cause,
            "metric_recorded_at": r["metric_recorded_at"],
        })
    return records


# ═══════════════════════════════════════════════════════════════════════════
# ANA AKIŞ
# ═══════════════════════════════════════════════════════════════════════════

def run(mode="full", region=None, hours=None):
    log.info(f"Anomali tespiti başlıyor  (mode={mode}, region={region}, hours={hours})")

    conn = get_conn()

    # 1. Veri çek
    df = fetch_metrics(conn, region=region, hours=hours if mode == "incremental" else None)

    if df.empty:
        log.warning("Veri bulunamadı, çıkılıyor.")
        conn.close()
        return

    # 2. Eksik değerleri doldur (çok nadir ama güvenlik için)
    df[FEATURE_COLS] = df[FEATURE_COLS].fillna(df[FEATURE_COLS].median())

    # 3. Isolation Forest
    log.info("Isolation Forest çalışıyor...")
    df_if = run_isolation_forest(df)
    anomaly_count_if = df_if["is_anomaly"].sum()
    log.info(f"  IF anomali: {anomaly_count_if:,} / {len(df_if):,}")

    # 4. Z-Score
    log.info("Z-Score çalışıyor...")
    df_zs = run_zscore(df)
    anomaly_count_zs = df_zs["is_anomaly"].sum()
    log.info(f"  ZS anomali: {anomaly_count_zs:,} / {len(df_zs):,}")

    # 5. Combined
    log.info("Sonuçlar birleştiriliyor...")
    df_combined = combine_results(df_if, df_zs)
    anomaly_count_cb = df_combined["is_anomaly"].sum()
    log.info(f"  Combined anomali: {anomaly_count_cb:,} / {len(df_combined):,}")

    # 6. Enrich (severity + root_cause)
    # records_if  = enrich_results(df_if)
    # records_zs  = enrich_results(df_zs)
    records_cb  = enrich_results(df_combined)

    # 7. DB'ye yaz
    log.info("Veritabanına yazılıyor...")
    # insert_results(conn, records_if)
    # insert_results(conn, records_zs)
    insert_results(conn, records_cb)

    conn.close()

    # 8. Özet
    print_summary(df_combined)



def run_incremental(hours: int = 1, region: str | None = None):
    """Service-friendly incremental anomaly run for scheduler/jobs."""
    return run(mode="incremental", region=region, hours=hours)


def run_full(region: str | None = None):
    """Service-friendly full anomaly run for manual/bootstrap usage."""
    return run(mode="full", region=region, hours=None)

def print_summary(df: pd.DataFrame):
    anomalies = df[df["is_anomaly"] == True]
    print("\n" + "═" * 60)
    print("  ANOMALİ TESPİT ÖZETI")
    print("═" * 60)
    print(f"  Toplam ölçüm   : {len(df):,}")
    print(f"  Anomali sayısı : {len(anomalies):,}  "
          f"(%{100*len(anomalies)/len(df):.1f})")

    if len(anomalies) == 0:
        print("  Anomali bulunamadı.")
        return

    print("\n  En çok anomali çıkan hücreler:")
    top = (anomalies.groupby("cell_id")
                    .size()
                    .sort_values(ascending=False)
                    .head(10))
    for cell_id, cnt in top.items():
        print(f"    {cell_id:<12} {cnt:>5} anomali")

    print("\n  Triggered_by metrik dağılımı:")
    metric_hits = {}
    for _, r in anomalies.iterrows():
        for col in r["triggered_by"]:
            metric_hits[col] = metric_hits.get(col, 0) + 1
    for col, cnt in sorted(metric_hits.items(), key=lambda x: -x[1]):
        print(f"    {col:<25} {cnt:>5}")
    print("═" * 60)


# ═══════════════════════════════════════════════════════════════════════════
# CLI
# ═══════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Telekom Anomali Dedektörü")
    parser.add_argument(
        "--mode", choices=["full", "incremental"], default="full",
        help="full: tüm veri | incremental: son N saat"
    )
    parser.add_argument(
        "--region", default=None,
        help="Sadece belirli bölgeyi tara (örn: Bornova)"
    )
    parser.add_argument(
        "--hours", type=int, default=1,
        help="Incremental modda kaç saate bakılsın (varsayılan: 1)"
    )
    args = parser.parse_args()
    run(mode=args.mode, region=args.region, hours=args.hours)

