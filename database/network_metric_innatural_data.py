"""
generate_metrics.py
--------------------
network_metrics tablosu için 7 günlük gerçekçi yapay veri üretir.
Çıktı: network_metrics_seed.sql (direkt PostgreSQL'e atılabilir)

SENARYOLAR:
  1. Normal günler       → sabah/akşam yoğunluğu, gece sakin
  2. Maç günü (Gün 3)    → Bornova/Konak spike (19:00-22:00)
  3. Fiber kesinti (Gün 2)→ Çiğli tüm hücreler 3 saat (10:00-13:00)
  4. Donanım arızası (Gün 5) → CELL_017 rsrp -115'e düşer
  5. Kademeli bozulma (Gün 4) → CELL_001 her saat +0.1% packet_loss
  6. Sinyal kirliliği    → CELL_023 Bayraklı rsrq çok düşük (-25 dB)
  7. Hayalet şikayet     → CELL_008 Konak metrikler normal, CRM'de şikayet
  8. Dilim darboğazı     → CELL_011 Karşıyaka URLLC latency patlıyor
"""

import random
import math
from datetime import datetime, timedelta

random.seed(42)

# ── Başlangıç zamanı: 7 gün önce, gece yarısı ──────────────────────────────
START = datetime(2026, 4, 5, 0, 0, 0)   # Gün 1
INTERVAL_MIN = 30                         # Her 30 dakikada bir ölçüm

# ── Tüm cell listesi (base_stations tablosundan) ───────────────────────────
CELLS = {
    "CELL_001": "Bornova",  "CELL_002": "Bornova",  "CELL_003": "Bornova",
    "CELL_004": "Bornova",  "CELL_005": "Bornova",
    "CELL_006": "Konak",    "CELL_007": "Konak",    "CELL_008": "Konak",
    "CELL_009": "Konak",    "CELL_010": "Konak",
    "CELL_011": "Karşıyaka","CELL_012": "Karşıyaka","CELL_013": "Karşıyaka",
    "CELL_014": "Karşıyaka",
    "CELL_015": "Buca",     "CELL_016": "Buca",     "CELL_017": "Buca",
    "CELL_018": "Buca",
    "CELL_019": "Çiğli",    "CELL_020": "Çiğli",    "CELL_021": "Çiğli",
    "CELL_022": "Çiğli",
    "CELL_023": "Bayraklı", "CELL_024": "Bayraklı", "CELL_025": "Bayraklı",
    "CELL_026": "Bayraklı",
    "CELL_027": "Gaziemir", "CELL_028": "Gaziemir", "CELL_029": "Gaziemir",
    "CELL_030": "Menemen",  "CELL_031": "Menemen",  "CELL_032": "Menemen",
    "CELL_033": "Torbalı",  "CELL_034": "Torbalı",  "CELL_035": "Torbalı",
    "CELL_036": "Kemalpaşa","CELL_037": "Kemalpaşa","CELL_038": "Kemalpaşa",
    "CELL_039": "Karabağlar","CELL_040": "Karabağlar","CELL_041": "Karabağlar",
    "CELL_042": "Urla",     "CELL_043": "Urla",
    "CELL_044": "Balçova",  "CELL_045": "Balçova",
    "CELL_046": "Narlıdere","CELL_047": "Narlıdere",
    "CELL_048": "Güzelbahçe","CELL_049": "Güzelbahçe",
    "CELL_050": "Seferihisar","CELL_051": "Seferihisar",
    "CELL_052": "Menderes", "CELL_053": "Menderes",
    "CELL_054": "Aliağa",   "CELL_055": "Aliağa",
    "CELL_056": "Çeşme",    "CELL_057": "Çeşme",
    "CELL_058": "Selçuk",   "CELL_059": "Selçuk",
    "CELL_060": "Foça",     "CELL_061": "Karaburun","CELL_062": "Tire",
    "CELL_063": "Ödemiş",   "CELL_064": "Kiraz",    "CELL_065": "Beydağ",
    "CELL_066": "Kınık",    "CELL_067": "Dikili",   "CELL_068": "Bergama",
    "CELL_069": "Bayındır",
}

# Slice ağırlıkları: çoğu hücre eMBB, bazıları URLLC/mMTC de üretir
SLICE_WEIGHTS = {"eMBB": 0.65, "URLLC": 0.25, "mMTC": 0.10}

def weighted_slice():
    return random.choices(list(SLICE_WEIGHTS.keys()),
                          weights=list(SLICE_WEIGHTS.values()))[0]

# ── Saatlik yük profili (0-23) ─────────────────────────────────────────────
def base_load(hour: int) -> float:
    """Saate göre baz yük yüzdesi (0-1)"""
    profile = {
        0: 0.12, 1: 0.10, 2: 0.09, 3: 0.08, 4: 0.08, 5: 0.10,
        6: 0.25, 7: 0.55, 8: 0.65, 9: 0.50, 10: 0.45, 11: 0.50,
        12: 0.68, 13: 0.72, 14: 0.55, 15: 0.52, 16: 0.58, 17: 0.72,
        18: 0.80, 19: 0.85, 20: 0.88, 21: 0.75, 22: 0.55, 23: 0.35,
    }
    return profile[hour]

def jitter(val, pct=0.08):
    """Değere ±pct oranında rastgele gürültü ekle"""
    return val * (1 + random.uniform(-pct, pct))

# ── Normal metrik üretici ──────────────────────────────────────────────────
def normal_metrics(load: float, slice_type: str) -> dict:
    """
    load: 0.0 - 1.0 arası yük yüzdesi
    Tüm metrikler yükle orantılı olarak değişir.
    """
    load_pct      = jitter(load * 100, 0.05)
    connected     = int(jitter(load * 200, 0.10))

    # Latency: düşük yükte 10-20ms, yüksek yükte 40-80ms
    latency       = jitter(10 + load * 70, 0.10)

    # Packet loss: yük %70 altında 0-1%, üstünde lineer artış
    if load < 0.70:
        packet_loss = jitter(load * 1.2, 0.15)
    else:
        packet_loss = jitter(1.2 + (load - 0.70) * 18, 0.12)

    # Throughput: yükle ters orantılı (kanal dolunca hız düşer)
    throughput    = jitter(150 - load * 100, 0.08)

    # Sinyal: sabit band, hafif varyasyon
    rsrp          = jitter(-85, 0.04)       # -75 ile -95 arası
    rsrq          = jitter(-10, 0.08)       # -8 ile -14 arası

    # URLLC slice: latency toleransı çok düşük, normal < 10ms
    if slice_type == "URLLC":
        latency   = jitter(5 + load * 20, 0.10)

    return {
        "load_pct":        round(max(5,  min(100, load_pct)),    2),
        "connected_users": max(0, connected),
        "latency_ms":      round(max(5,  latency),               2),
        "packet_loss_pct": round(max(0,  min(25, packet_loss)),  3),
        "throughput_mbps": round(max(5,  throughput),            2),
        "rsrp_dbm":        round(rsrp,                           2),
        "rsrq_db":         round(rsrq,                           2),
    }

# ═══════════════════════════════════════════════════════════════════════════
# SENARYO FONKSİYONLARI
# Her fonksiyon normal metrikler sözlüğünü alır, üzerine senaryo etkisi uygular
# ═══════════════════════════════════════════════════════════════════════════

def scenario_mac_gunu(m: dict) -> dict:
    """Senaryo 2 — Maç günü: yük %92-98, latency 200ms+, packet_loss %8+"""
    m["load_pct"]        = round(random.uniform(92, 98), 2)
    m["latency_ms"]      = round(random.uniform(180, 350), 2)
    m["packet_loss_pct"] = round(random.uniform(8, 18), 3)
    m["throughput_mbps"] = round(random.uniform(8, 25), 2)
    m["connected_users"] = random.randint(350, 500)
    return m

def scenario_fiber_kesinti(m: dict) -> dict:
    """Senaryo 3 — Fiber kesinti: packet_loss %15+, throughput 5 Mbps'e düşer"""
    m["packet_loss_pct"] = round(random.uniform(15, 22), 3)
    m["throughput_mbps"] = round(random.uniform(2, 8), 2)
    m["latency_ms"]      = round(random.uniform(300, 600), 2)
    m["load_pct"]        = round(random.uniform(20, 40), 2)   # bağlanamayanlar düştü
    return m

def scenario_donanim_arizasi(m: dict) -> dict:
    """Senaryo 4 — Donanım arızası: rsrp -115'e düşer, throughput çöker"""
    m["rsrp_dbm"]        = round(random.uniform(-118, -112), 2)
    m["rsrq_db"]         = round(random.uniform(-22, -18), 2)
    m["throughput_mbps"] = round(random.uniform(2, 12), 2)
    m["latency_ms"]      = round(random.uniform(150, 400), 2)
    m["packet_loss_pct"] = round(random.uniform(10, 20), 3)
    return m

def scenario_kademeli_bozulma(m: dict, hour_offset: int) -> dict:
    """
    Senaryo 5 — Kademeli bozulma: Gün 4 boyunca her saat +0.1% packet_loss
    hour_offset: 0-47 (günün kaçıncı 30-dakika dilimine denk geliyor)
    """
    # Her tam saat +0.1 eklenir → günün 48 slotunda 0'dan 4.8'e kadar tırmanır
    degradation = (hour_offset // 2) * 0.10
    m["packet_loss_pct"] = round(m["packet_loss_pct"] + degradation, 3)
    # Hafif latency artışı da ekle (gerçekçi)
    m["latency_ms"]      = round(m["latency_ms"] + degradation * 3, 2)
    return m

def scenario_sinyal_kirliligi(m: dict) -> dict:
    """
    Senaryo 6 — Sinyal kirliliği: rsrp normal ama rsrq çok kötü (-25 dB)
    Throughput düşer ama latency nispeten normal kalır.
    """
    # rsrp değişmez (sinyal güçlü)
    m["rsrq_db"]         = round(random.uniform(-28, -22), 2)  # normalize -8 / -20 → anomali
    m["throughput_mbps"] = round(random.uniform(8, 25), 2)     # hız düştü
    # latency biraz artar ama patlamaz (bu senaryonun özü)
    m["latency_ms"]      = round(m["latency_ms"] * 1.4, 2)
    return m

def scenario_hayalet_sikayet(m: dict) -> dict:
    """
    Senaryo 7 — Hayalet şikayet (Zombi hücre):
    Metrikler kağıt üzerinde normal kalır, hiçbir şeye dokunmuyoruz.
    Anomali sadece complaints tablosunda görünecek.
    Bu fonksiyon identity'dir — kaydı tutmak için buraya alındı.
    """
    return m  # metrikler değişmiyor, bu senaryonun püf noktası

def scenario_dilim_darbogazı(m: dict, slice_type: str) -> dict:
    """
    Senaryo 8 — Dilim darboğazı:
    eMBB (video) normal, URLLC latency 100ms+, packet_loss artar.
    """
    if slice_type == "URLLC":
        m["latency_ms"]      = round(random.uniform(100, 220), 2)
        m["packet_loss_pct"] = round(random.uniform(5, 12), 3)
        m["throughput_mbps"] = round(random.uniform(10, 30), 2)
    # eMBB/mMTC değişmez
    return m

# ═══════════════════════════════════════════════════════════════════════════
# ANA ÜRETİCİ
# ═══════════════════════════════════════════════════════════════════════════

def generate():
    rows = []

    total_slots = (7 * 24 * 60) // INTERVAL_MIN   # 336 zaman dilimi / 7 gün
    cell_list   = list(CELLS.keys())

    for slot in range(total_slots):
        ts   = START + timedelta(minutes=slot * INTERVAL_MIN)
        day  = slot // (48)          # 0-6 (Gün 1 = 0)
        hour = ts.hour
        # günün kaçıncı 30-dakika dilimi (kademeli bozulma için)
        slot_in_day = slot % 48

        load = base_load(hour)

        for cell_id in cell_list:
            region     = CELLS[cell_id]
            slice_type = weighted_slice()
            m          = normal_metrics(load, slice_type)

            # ── Senaryo 2: Maç günü — Gün 3 (day==2), 19:00-22:00, Bornova+Konak ──
            if day == 2 and 19 <= hour < 22 and region in ("Bornova", "Konak"):
                m = scenario_mac_gunu(m)

            # ── Senaryo 3: Fiber kesinti — Gün 2 (day==1), 10:00-13:00, Çiğli ──
            elif day == 1 and 10 <= hour < 13 and region == "Çiğli":
                m = scenario_fiber_kesinti(m)

            # ── Senaryo 4: Donanım arızası — Gün 5 (day==4), 06:00+, CELL_017 ──
            elif day == 4 and hour >= 6 and cell_id == "CELL_017":
                m = scenario_donanim_arizasi(m)

            # ── Senaryo 5: Kademeli bozulma — Gün 4 (day==3), CELL_001 ──
            elif day == 3 and cell_id == "CELL_001":
                m = scenario_kademeli_bozulma(m, slot_in_day)

            # ── Senaryo 6: Sinyal kirliliği — Gün 6 (day==5), 08:00-20:00, CELL_023 ──
            elif day == 5 and 8 <= hour < 20 and cell_id == "CELL_023":
                m = scenario_sinyal_kirliligi(m)

            # ── Senaryo 7: Hayalet şikayet — Gün 7 (day==6), tüm gün, CELL_008 ──
            elif day == 6 and cell_id == "CELL_008":
                m = scenario_hayalet_sikayet(m)   # metrikler normal kalır

            # ── Senaryo 8: Dilim darboğazı — Gün 7 (day==6), 17:00-23:00, CELL_011 ──
            elif day == 6 and 17 <= hour < 23 and cell_id == "CELL_011":
                m = scenario_dilim_darbogazı(m, slice_type)

            rows.append((
                cell_id,
                slice_type,
                m["rsrp_dbm"],
                m["rsrq_db"],
                m["throughput_mbps"],
                m["latency_ms"],
                m["packet_loss_pct"],
                m["connected_users"],
                m["load_pct"],
                ts.strftime("%Y-%m-%d %H:%M:%S"),
            ))

    return rows

# ═══════════════════════════════════════════════════════════════════════════
# SQL ÇIKTI YAZICI
# ═══════════════════════════════════════════════════════════════════════════

def write_sql(rows, path="network_metrics_seed.sql"):
    header = """-- ============================================================
-- network_metrics seed verisi
-- Üretildi: generate_metrics.py
-- Toplam satır: {count}
-- Kapsanan süre: 7 gün (2026-04-05 → 2026-04-11)
-- Senaryolar: 8 adet (maç, fiber kesinti, donanım arızası,
--             kademeli bozulma, sinyal kirliliği,
--             hayalet şikayet, dilim darboğazı + normal)
-- ============================================================

BEGIN;

INSERT INTO network_metrics
    (cell_id, slice_type, rsrp_dbm, rsrq_db,
     throughput_mbps, latency_ms, packet_loss_pct,
     connected_users, load_pct, recorded_at)
VALUES
""".format(count=len(rows))

    with open(path, "w", encoding="utf-8") as f:
        f.write(header)
        for i, row in enumerate(rows):
            (cell_id, slice_type, rsrp, rsrq,
             tput, lat, ploss, users, load, ts) = row

            line = (
                f"  ('{cell_id}', '{slice_type}', "
                f"{rsrp}, {rsrq}, "
                f"{tput}, {lat}, {ploss}, "
                f"{users}, {load}, "
                f"'{ts}')"
            )
            if i < len(rows) - 1:
                line += ","
            else:
                line += ";"
            f.write(line + "\n")

        f.write("\nCOMMIT;\n")

    print(f"✅  {len(rows):,} satır yazıldı → {path}")

# ── Senaryo özeti yazdır ───────────────────────────────────────────────────
def print_summary(rows):
    print("\n📊 Senaryo Özeti")
    print("─" * 60)
    scenarios = {
        "Maç günü (Bornova/Konak, Gün3 19-22h)": 0,
        "Fiber kesinti (Çiğli, Gün2 10-13h)":    0,
        "Donanım arızası (CELL_017, Gün5 06h+)": 0,
        "Kademeli bozulma (CELL_001, Gün4)":      0,
        "Sinyal kirliliği (CELL_023, Gün6 8-20h)":0,
        "Hayalet şikayet (CELL_008, Gün7)":       0,
        "Dilim darboğazı (CELL_011, Gün7 17-23h)":0,
        "Normal":                                  0,
    }
    from datetime import datetime
    for row in rows:
        cell_id, slice_type, rsrp, rsrq, tput, lat, ploss, users, load, ts = row
        t    = datetime.strptime(ts, "%Y-%m-%d %H:%M:%S")
        day  = (t - START).days
        hour = t.hour
        region = CELLS[cell_id]

        if day == 2 and 19 <= hour < 22 and region in ("Bornova","Konak"):
            scenarios["Maç günü (Bornova/Konak, Gün3 19-22h)"] += 1
        elif day == 1 and 10 <= hour < 13 and region == "Çiğli":
            scenarios["Fiber kesinti (Çiğli, Gün2 10-13h)"] += 1
        elif day == 4 and hour >= 6 and cell_id == "CELL_017":
            scenarios["Donanım arızası (CELL_017, Gün5 06h+)"] += 1
        elif day == 3 and cell_id == "CELL_001":
            scenarios["Kademeli bozulma (CELL_001, Gün4)"] += 1
        elif day == 5 and 8 <= hour < 20 and cell_id == "CELL_023":
            scenarios["Sinyal kirliliği (CELL_023, Gün6 8-20h)"] += 1
        elif day == 6 and cell_id == "CELL_008":
            scenarios["Hayalet şikayet (CELL_008, Gün7)"] += 1
        elif day == 6 and 17 <= hour < 23 and cell_id == "CELL_011":
            scenarios["Dilim darboğazı (CELL_011, Gün7 17-23h)"] += 1
        else:
            scenarios["Normal"] += 1

    for name, count in scenarios.items():
        bar = "█" * (count // 50)
        print(f"  {name:<45} {count:>6} satır  {bar}")
    print(f"\n  Toplam: {len(rows):,} satır")

if __name__ == "__main__":
    print("⏳ Veri üretiliyor...")
    rows = generate()
    print_summary(rows)
    write_sql(rows, "network_metrics_seed.sql")