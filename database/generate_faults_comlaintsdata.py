"""
generate_faults_complaints.py
──────────────────────────────
faults ve complaints tabloları için DDL + seed veri üretir.
Çıktılar:
  • faults_table.sql          → CREATE TABLE + indeksler
  • complaints_table.sql      → CREATE TABLE + indeksler
  • faults_seed.sql           → 7 günlük arıza kayıtları
  • complaints_seed.sql       → 7 günlük müşteri şikayetleri

SENARYO → TABLO BAĞLANTISI
  Senaryo 2  Maç günü           → faults (HIGH_LOAD)        + complaints (yavaş internet)
  Senaryo 3  Fiber kesinti      → faults (FIBER_CUT)        + complaints (bağlanamıyorum)
  Senaryo 4  Donanım arızası    → faults (HW_FAILURE)       + complaints (sinyal yok)
  Senaryo 5  Kademeli bozulma   → faults (DEGRADATION)      + complaints (yavaş internet, geç saatlerde artar)
  Senaryo 6  Sinyal kirliliği   → faults (INTERFERENCE)     + complaints (video takılıyor)
  Senaryo 7  Hayalet şikayet    → faults YOK (metrikler OK) + complaints (bağlanamıyorum) ← AI testi
  Senaryo 8  Dilim darboğazı    → faults (SLICE_CONGESTION) + complaints (oyun/uygulama lag)
  Normal     Arka plan          → faults az/rastgele        + complaints az/rastgele
"""

import random
from datetime import datetime, timedelta

random.seed(99)

START = datetime(2026, 4, 5, 0, 0, 0)

# ── Hücre → bölge haritası (network_metrics ile aynı) ─────────────────────
CELLS = {
    "CELL_001": "Bornova",   "CELL_002": "Bornova",   "CELL_003": "Bornova",
    "CELL_004": "Bornova",   "CELL_005": "Bornova",
    "CELL_006": "Konak",     "CELL_007": "Konak",     "CELL_008": "Konak",
    "CELL_009": "Konak",     "CELL_010": "Konak",
    "CELL_011": "Karşıyaka", "CELL_012": "Karşıyaka", "CELL_013": "Karşıyaka",
    "CELL_014": "Karşıyaka",
    "CELL_015": "Buca",      "CELL_016": "Buca",      "CELL_017": "Buca",
    "CELL_018": "Buca",
    "CELL_019": "Çiğli",     "CELL_020": "Çiğli",     "CELL_021": "Çiğli",
    "CELL_022": "Çiğli",
    "CELL_023": "Bayraklı",  "CELL_024": "Bayraklı",  "CELL_025": "Bayraklı",
    "CELL_026": "Bayraklı",
    "CELL_027": "Gaziemir",  "CELL_028": "Gaziemir",  "CELL_029": "Gaziemir",
    "CELL_030": "Menemen",   "CELL_031": "Menemen",   "CELL_032": "Menemen",
    "CELL_033": "Torbalı",   "CELL_034": "Torbalı",   "CELL_035": "Torbalı",
    "CELL_036": "Kemalpaşa", "CELL_037": "Kemalpaşa", "CELL_038": "Kemalpaşa",
    "CELL_039": "Karabağlar","CELL_040": "Karabağlar","CELL_041": "Karabağlar",
    "CELL_042": "Urla",      "CELL_043": "Urla",
    "CELL_044": "Balçova",   "CELL_045": "Balçova",
    "CELL_046": "Narlıdere", "CELL_047": "Narlıdere",
    "CELL_048": "Güzelbahçe","CELL_049": "Güzelbahçe",
    "CELL_050": "Seferihisar","CELL_051": "Seferihisar",
    "CELL_052": "Menderes",  "CELL_053": "Menderes",
    "CELL_054": "Aliağa",    "CELL_055": "Aliağa",
    "CELL_056": "Çeşme",     "CELL_057": "Çeşme",
    "CELL_058": "Selçuk",    "CELL_059": "Selçuk",
    "CELL_060": "Foça",      "CELL_061": "Karaburun", "CELL_062": "Tire",
    "CELL_063": "Ödemiş",    "CELL_064": "Kiraz",     "CELL_065": "Beydağ",
    "CELL_066": "Kınık",     "CELL_067": "Dikili",    "CELL_068": "Bergama",
    "CELL_069": "Bayındır",
}

# Bölge → o bölgedeki müşteri ID havuzu (gerçekçi CRM verisi için)
def region_customers(region, n=80):
    """Her bölge için sahte müşteri ID'leri üret"""
    prefix = region[:3].upper().replace("Ç","C").replace("Ş","S").replace("İ","I")
    return [f"CUST_{prefix}_{1000 + i}" for i in range(n)]

# ─────────────────────────────────────────────────────────────────────────
# YARDIMCI FONKSİYONLAR
# ─────────────────────────────────────────────────────────────────────────

def ts_str(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%d %H:%M:%S")

def rand_minutes(lo=2, hi=30):
    return timedelta(minutes=random.randint(lo, hi))

# ─────────────────────────────────────────────────────────────────────────
# FAULT ÜRETME FONKSİYONLARI
# ─────────────────────────────────────────────────────────────────────────
#
# Her fault kaydı:
#   cell_id | severity | fault_type | message | resolved | created_at | resolved_at (opsiyonel)
#
# severity sıralaması: CRITICAL > MAJOR > MINOR > WARNING
# resolved = False → hâlâ açık arıza

def make_fault(cell_id, severity, fault_type, message, created_at,
               resolved=True, resolve_after_min=None):
    resolved_at = None
    if resolved and resolve_after_min:
        resolved_at = created_at + timedelta(minutes=resolve_after_min)
    return {
        "cell_id":     cell_id,
        "severity":    severity,
        "fault_type":  fault_type,
        "message":     message,
        "resolved":    resolved,
        "created_at":  ts_str(created_at),
        "resolved_at": ts_str(resolved_at) if resolved_at else "NULL",
    }

def generate_faults():
    faults = []

    # ── S2: Maç günü — Gün 3, 19:00, Bornova + Konak ─────────────────────
    mac_start = START + timedelta(days=2, hours=19)
    mac_cells = [c for c, r in CELLS.items() if r in ("Bornova", "Konak")]
    for cell_id in mac_cells:
        offset = rand_minutes(0, 20)
        faults.append(make_fault(
            cell_id, "MAJOR", "HIGH_LOAD",
            f"Kapasite aşımı: yük >%92, paket kaybı >%8. "
            f"Bölgede yoğun etkinlik trafiği (maç saati).",
            mac_start + offset,
            resolved=True, resolve_after_min=random.randint(150, 200)
        ))

    # ── S3: Fiber kesinti — Gün 2, 10:00, Çiğli (4 hücre) ────────────────
    fiber_start = START + timedelta(days=1, hours=10)
    cigli_cells = [c for c, r in CELLS.items() if r == "Çiğli"]
    # İlk hücre CRITICAL (trunk), diğerleri MAJOR (etkilenen)
    for i, cell_id in enumerate(cigli_cells):
        sev = "CRITICAL" if i == 0 else "MAJOR"
        msg = (
            "Fiber hat kesintisi tespit edildi. Tüm Çiğli hücreleri etkilendi. "
            "Throughput <8 Mbps, paket kaybı >%15."
            if i == 0 else
            f"Upstream fiber kesintisinden etkilendi. "
            f"Bağlantı degraded durumda."
        )
        faults.append(make_fault(
            cell_id, sev, "FIBER_CUT", msg,
            fiber_start + rand_minutes(0, 5),
            resolved=True, resolve_after_min=random.randint(170, 200)
        ))

    # ── S4: Donanım arızası — Gün 5, 06:00, CELL_017 ─────────────────────
    hw_start = START + timedelta(days=4, hours=6)
    faults.append(make_fault(
        "CELL_017", "CRITICAL", "HW_FAILURE",
        "RSRP -115 dBm seviyesine düştü. Radyo modülü arızası şüphesi. "
        "Throughput <12 Mbps, latency >150ms. Saha ekibi çağrıldı.",
        hw_start + rand_minutes(0, 10),
        resolved=True, resolve_after_min=random.randint(300, 420)
    ))
    # Buca komşu hücreler MINOR uyarı (handover yükü arttı)
    for cell_id in ["CELL_015", "CELL_016", "CELL_018"]:
        faults.append(make_fault(
            cell_id, "MINOR", "HANDOVER_LOAD",
            "Komşu CELL_017 arızası nedeniyle handover yükü arttı.",
            hw_start + rand_minutes(15, 40),
            resolved=True, resolve_after_min=random.randint(280, 400)
        ))

    # ── S5: Kademeli bozulma — Gün 4, CELL_001 ───────────────────────────
    # Sabah WARNING → öğlen MINOR → akşam MAJOR (tırmanma)
    deg_day = START + timedelta(days=3)
    faults.append(make_fault(
        "CELL_001", "WARNING", "DEGRADATION",
        "Paket kaybı yavaş artış trendi: 08:00'dan itibaren her saat ~+0.1%. "
        "Proaktif izleme başlatıldı.",
        deg_day + timedelta(hours=8),
        resolved=False   # gün boyunca açık kalıyor
    ))
    faults.append(make_fault(
        "CELL_001", "MINOR", "DEGRADATION",
        "Paket kaybı %1.5 seviyesini aştı. Donanım sağlık kontrolü planlandı.",
        deg_day + timedelta(hours=14),
        resolved=False
    ))
    faults.append(make_fault(
        "CELL_001", "MAJOR", "DEGRADATION",
        "Paket kaybı %3.2 — eşik aşıldı. Otomatik ticket açıldı. "
        "Saha kontrolü bekleniyor.",
        deg_day + timedelta(hours=20),
        resolved=False
    ))

    # ── S6: Sinyal kirliliği — Gün 6, 08:00, CELL_023 ────────────────────
    interference_start = START + timedelta(days=5, hours=8)
    faults.append(make_fault(
        "CELL_023", "MAJOR", "INTERFERENCE",
        "RSRQ -25 dB seviyesine düştü (normalize: -8/-20). "
        "RSRP normal ama throughput <25 Mbps. Frekans müdahalesi şüphesi.",
        interference_start + rand_minutes(0, 15),
        resolved=True, resolve_after_min=random.randint(680, 730)
    ))

    # ── S7: Hayalet şikayet — Gün 7, CELL_008 ───────────────────────────
    # Metrikler normal → fault YOK (bu senaryonun özü: AI sadece CRM'e bakarak bulacak)
    # Arka plan için CELL_008'e küçük bir WARNING bile koymuyoruz.

    # ── S8: Dilim darboğazı — Gün 7, 17:00, CELL_011 ────────────────────
    slice_start = START + timedelta(days=6, hours=17)
    faults.append(make_fault(
        "CELL_011", "MAJOR", "SLICE_CONGESTION",
        "URLLC diliminde latency >100ms (SLA eşiği: <10ms). "
        "eMBB normal. Slice kaynak tahsisi inceleniyor.",
        slice_start + rand_minutes(0, 10),
        resolved=False
    ))

    # ── Arka plan: rastgele MINOR/WARNING faultlar ────────────────────────
    bg_cells  = random.sample(list(CELLS.keys()), 12)
    bg_types  = [
        ("WARNING", "HIGH_LATENCY",  "Anlık latency spike tespit edildi. Otomatik izleme."),
        ("MINOR",   "LOW_THROUGHPUT","Throughput geçici olarak <40 Mbps'e düştü."),
        ("WARNING", "HIGH_LOAD",     "Yük >%80, kapasite izleme devrede."),
        ("MINOR",   "SIGNAL_DROP",   "RSRP geçici düşüş: -105 dBm. 10 dakika izlendi."),
    ]
    for cell_id in bg_cells:
        day_offset = random.randint(0, 6)
        hour_offset = random.randint(7, 22)
        t = START + timedelta(days=day_offset, hours=hour_offset,
                              minutes=random.randint(0, 59))
        sev, ftype, msg = random.choice(bg_types)
        faults.append(make_fault(
            cell_id, sev, ftype, msg, t,
            resolved=True, resolve_after_min=random.randint(20, 90)
        ))

    return faults


# ─────────────────────────────────────────────────────────────────────────
# COMPLAINT ÜRETME FONKSİYONLARI
# ─────────────────────────────────────────────────────────────────────────
#
# Her complaint kaydı:
#   customer_id | region | issue | cell_id (nullable) | created_at

def make_complaint(customer_id, region, issue, created_at, cell_id=None):
    return {
        "customer_id": customer_id,
        "region":      region,
        "issue":       issue,
        "cell_id":     cell_id if cell_id else "NULL",
        "created_at":  ts_str(created_at),
    }

# Şikayet metinleri — senaryoya göre havuzlar
COMPLAINTS = {
    "yavaş":       [
        "İnternet çok yavaş, sayfalar açılmıyor.",
        "Videoları izleyemiyorum, sürekli takılıyor.",
        "Akşam saatlerinde internet kullanılamaz hale geliyor.",
        "Maç izlerken bağlantım koptu, çok kötü.",
        "Akış hızım normalde 50 Mbps ama şu an 2 Mbps.",
    ],
    "bag_yok":     [
        "İnternete bağlanamıyorum hiç.",
        "Telefon şebeke arıyor ama internet gelmiyor.",
        "4G simgesi var ama veri çekmiyor.",
        "Modemi yeniden başlattım olmadı, arıyorum.",
        "Sabahtan beri internet yok, iş yapamıyorum.",
    ],
    "sinyal":      [
        "Sinyal çubuğu tam ama internet yavaş, anlamadım.",
        "4-5 çubuk gösteriyor ama video donuyor.",
        "Sinyalim iyi görünüyor ama YouTube açılmıyor.",
        "Telefon tam sinyal diyor ama WhatsApp çalışmıyor.",
    ],
    "oyun_lag":    [
        "Oyun oynayamıyorum, ping çok yüksek.",
        "Mobil oyunda lag var, ping 200ms üstü.",
        "Online oyunda bağlantı kopuyor.",
        "Zoom toplantılarımda ses ve görüntü donuyor.",
        "Uzaktan çalışıyorum, video konferans bağlanamıyor.",
    ],
    "kademeli":    [
        "Sabah normale yakındı ama akşama doğru yavaşladı.",
        "Gün içinde giderek kötüleşiyor internet.",
        "Her gün biraz daha yavaş oluyor galiba.",
    ],
}

def generate_complaints():
    complaints = []

    # ── S2: Maç günü — Gün 3, 19:00-22:00, Bornova + Konak ──────────────
    mac_start = START + timedelta(days=2, hours=19)
    mac_cells_bornova = [c for c, r in CELLS.items() if r == "Bornova"]
    mac_cells_konak   = [c for c, r in CELLS.items() if r == "Konak"]

    for region, cells in [("Bornova", mac_cells_bornova), ("Konak", mac_cells_konak)]:
        customers = region_customers(region)
        # 3 saatte 40-60 şikayet (dakikaya yayılmış)
        for _ in range(random.randint(40, 60)):
            t = mac_start + timedelta(minutes=random.randint(0, 180))
            complaints.append(make_complaint(
                random.choice(customers), region,
                random.choice(COMPLAINTS["yavaş"]), t,
                cell_id=random.choice(cells)
            ))

    # ── S3: Fiber kesinti — Gün 2, 10:00-13:00, Çiğli ───────────────────
    fiber_start = START + timedelta(days=1, hours=10)
    cigli_cells = [c for c, r in CELLS.items() if r == "Çiğli"]
    customers   = region_customers("Çiğli")
    for _ in range(random.randint(50, 70)):
        t = fiber_start + timedelta(minutes=random.randint(0, 180))
        complaints.append(make_complaint(
            random.choice(customers), "Çiğli",
            random.choice(COMPLAINTS["bag_yok"]), t,
            cell_id=random.choice(cigli_cells)
        ))

    # ── S4: Donanım arızası — Gün 5, 06:00+, Buca ────────────────────────
    hw_start  = START + timedelta(days=4, hours=6)
    buca_cells = [c for c, r in CELLS.items() if r == "Buca"]
    customers  = region_customers("Buca")
    for _ in range(random.randint(30, 45)):
        t = hw_start + timedelta(minutes=random.randint(0, 300))
        complaints.append(make_complaint(
            random.choice(customers), "Buca",
            random.choice(COMPLAINTS["bag_yok"] + COMPLAINTS["sinyal"]), t,
            cell_id="CELL_017"   # arızalı hücreye sabitlendi
        ))

    # ── S5: Kademeli bozulma — Gün 4, tüm gün, Bornova ──────────────────
    # Sabah az şikayet, akşama doğru artar (kademeli bozulmayı yansıtır)
    deg_day   = START + timedelta(days=3)
    customers = region_customers("Bornova")
    # Saatlik şikayet sayısı artıyor: sabah 1-2, akşam 5-8
    for hour in range(8, 24):
        count = max(1, int((hour - 7) * 0.4))   # lineer artış
        for _ in range(count):
            t = deg_day + timedelta(hours=hour, minutes=random.randint(0, 59))
            complaints.append(make_complaint(
                random.choice(customers), "Bornova",
                random.choice(COMPLAINTS["kademeli"] + COMPLAINTS["yavaş"]), t,
                cell_id="CELL_001"
            ))

    # ── S6: Sinyal kirliliği — Gün 6, 08:00-20:00, Bayraklı ─────────────
    interference_start = START + timedelta(days=5, hours=8)
    bayraki_cells = [c for c, r in CELLS.items() if r == "Bayraklı"]
    customers     = region_customers("Bayraklı")
    for _ in range(random.randint(20, 30)):
        t = interference_start + timedelta(minutes=random.randint(0, 720))
        complaints.append(make_complaint(
            random.choice(customers), "Bayraklı",
            random.choice(COMPLAINTS["sinyal"]), t,
            cell_id="CELL_023"
        ))

    # ── S7: Hayalet şikayet — Gün 7, tüm gün, Konak / CELL_008 ──────────
    # Metrikler normal ama şikayetler var → AI sadece CRM'e bakarak bulmalı
    ghost_day = START + timedelta(days=6)
    customers = region_customers("Konak")
    for _ in range(random.randint(35, 50)):
        t = ghost_day + timedelta(hours=random.randint(8, 22),
                                   minutes=random.randint(0, 59))
        complaints.append(make_complaint(
            random.choice(customers), "Konak",
            random.choice(COMPLAINTS["bag_yok"]), t,
            cell_id="CELL_008"    # cell_id mevcut ama fault yok
        ))

    # ── S8: Dilim darboğazı — Gün 7, 17:00-23:00, Karşıyaka ─────────────
    slice_start = START + timedelta(days=6, hours=17)
    karsiyaka_cells = [c for c, r in CELLS.items() if r == "Karşıyaka"]
    customers       = region_customers("Karşıyaka")
    for _ in range(random.randint(20, 30)):
        t = slice_start + timedelta(minutes=random.randint(0, 360))
        complaints.append(make_complaint(
            random.choice(customers), "Karşıyaka",
            random.choice(COMPLAINTS["oyun_lag"]), t,
            cell_id="CELL_011"
        ))

    # ── Arka plan: 7 gün boyunca dağınık şikayetler ──────────────────────
    all_regions = list(set(CELLS.values()))
    for _ in range(80):
        region = random.choice(all_regions)
        cells  = [c for c, r in CELLS.items() if r == region]
        t = START + timedelta(
            days=random.randint(0, 6),
            hours=random.randint(8, 23),
            minutes=random.randint(0, 59)
        )
        issue_pool = random.choice(list(COMPLAINTS.values()))
        complaints.append(make_complaint(
            random.choice(region_customers(region)), region,
            random.choice(issue_pool), t,
            cell_id=random.choice(cells) if random.random() > 0.3 else None
        ))

    return complaints


# ─────────────────────────────────────────────────────────────────────────
# DDL YAZICI
# ─────────────────────────────────────────────────────────────────────────

FAULTS_DDL = """-- ============================================================
-- faults tablosu  — Arıza ve Alarm Kayıtları
-- ============================================================

CREATE TABLE faults (
    id           SERIAL        PRIMARY KEY,
    cell_id      VARCHAR(20)   NOT NULL
                     REFERENCES base_stations(cell_id),
    severity     VARCHAR(20)   NOT NULL
                     CHECK (severity IN ('CRITICAL','MAJOR','MINOR','WARNING')),
    fault_type   VARCHAR(50)   NOT NULL,
    message      TEXT,
    resolved     BOOLEAN       NOT NULL DEFAULT FALSE,
    created_at   TIMESTAMP     NOT NULL DEFAULT NOW(),
    resolved_at  TIMESTAMP
);

CREATE INDEX idx_faults_cell      ON faults (cell_id);
CREATE INDEX idx_faults_severity  ON faults (severity);
CREATE INDEX idx_faults_time      ON faults (created_at DESC);
CREATE INDEX idx_faults_open      ON faults (resolved) WHERE resolved = FALSE;
"""

COMPLAINTS_DDL = """-- ============================================================
-- complaints tablosu  — Müşteri Şikayetleri (CRM)
-- ============================================================

CREATE TABLE complaints (
    id           SERIAL        PRIMARY KEY,
    customer_id  VARCHAR(30)   NOT NULL,
    region       VARCHAR(50)   NOT NULL,
    issue        TEXT          NOT NULL,
    cell_id      VARCHAR(20)   REFERENCES base_stations(cell_id),
    created_at   TIMESTAMP     NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_complaints_region  ON complaints (region);
CREATE INDEX idx_complaints_cell    ON complaints (cell_id);
CREATE INDEX idx_complaints_time    ON complaints (created_at DESC);
CREATE INDEX idx_complaints_cust    ON complaints (customer_id);
"""


# ─────────────────────────────────────────────────────────────────────────
# SQL YAZICI
# ─────────────────────────────────────────────────────────────────────────

def escape(s):
    return s.replace("'", "''")

def write_ddl(path_faults, path_complaints):
    with open(path_faults, "w", encoding="utf-8") as f:
        f.write(FAULTS_DDL)
    with open(path_complaints, "w", encoding="utf-8") as f:
        f.write(COMPLAINTS_DDL)
    print(f"✅  DDL yazıldı → {path_faults}")
    print(f"✅  DDL yazıldı → {path_complaints}")

def write_faults_seed(faults, path):
    header = f"""-- ============================================================
-- faults seed verisi  ({len(faults)} kayıt)
-- Kapsanan süre: 2026-04-05 → 2026-04-11
-- ============================================================

BEGIN;

INSERT INTO faults
    (cell_id, severity, fault_type, message, resolved, created_at, resolved_at)
VALUES
"""
    with open(path, "w", encoding="utf-8") as f:
        f.write(header)
        for i, row in enumerate(faults):
            resolved_at = f"'{row['resolved_at']}'" if row["resolved_at"] != "NULL" else "NULL"
            line = (
                f"  ('{row['cell_id']}', '{row['severity']}', '{row['fault_type']}', "
                f"'{escape(row['message'])}', {str(row['resolved']).upper()}, "
                f"'{row['created_at']}', {resolved_at})"
            )
            f.write(line + ("," if i < len(faults) - 1 else ";") + "\n")
        f.write("\nCOMMIT;\n")
    print(f"✅  {len(faults)} fault kaydı → {path}")

def write_complaints_seed(complaints, path):
    header = f"""-- ============================================================
-- complaints seed verisi  ({len(complaints)} kayıt)
-- Kapsanan süre: 2026-04-05 → 2026-04-11
-- ============================================================

BEGIN;

INSERT INTO complaints
    (customer_id, region, issue, cell_id, created_at)
VALUES
"""
    with open(path, "w", encoding="utf-8") as f:
        f.write(header)
        for i, row in enumerate(complaints):
            cell_val = f"'{row['cell_id']}'" if row["cell_id"] != "NULL" else "NULL"
            line = (
                f"  ('{row['customer_id']}', '{escape(row['region'])}', "
                f"'{escape(row['issue'])}', {cell_val}, "
                f"'{row['created_at']}')"
            )
            f.write(line + ("," if i < len(complaints) - 1 else ";") + "\n")
        f.write("\nCOMMIT;\n")
    print(f"✅  {len(complaints)} complaint kaydı → {path}")

# ─────────────────────────────────────────────────────────────────────────
# ÖZET
# ─────────────────────────────────────────────────────────────────────────

def print_summary(faults, complaints):
    print("\n📊 Fault Özeti")
    print("─" * 55)
    sev_count = {}
    type_count = {}
    for f in faults:
        sev_count[f["severity"]]   = sev_count.get(f["severity"], 0) + 1
        type_count[f["fault_type"]] = type_count.get(f["fault_type"], 0) + 1
    for sev in ["CRITICAL","MAJOR","MINOR","WARNING"]:
        print(f"  {sev:<12} {sev_count.get(sev,0):>4} kayıt")
    print()
    for ft, cnt in sorted(type_count.items(), key=lambda x: -x[1]):
        print(f"  {ft:<25} {cnt:>4} kayıt")

    print("\n📊 Complaint Özeti")
    print("─" * 55)
    region_count = {}
    for c in complaints:
        region_count[c["region"]] = region_count.get(c["region"], 0) + 1
    for region, cnt in sorted(region_count.items(), key=lambda x: -x[1]):
        bar = "█" * (cnt // 5)
        print(f"  {region:<15} {cnt:>4}  {bar}")
    print(f"\n  Toplam fault:      {len(faults)}")
    print(f"  Toplam complaint:  {len(complaints)}")


# ─────────────────────────────────────────────────────────────────────────
# MAIN
# ─────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    print("⏳ Faults ve Complaints üretiliyor...\n")

    write_ddl("faults_table.sql", "complaints_table.sql")

    faults     = generate_faults()
    complaints = generate_complaints()

    write_faults_seed(faults,         "faults_seed.sql")
    write_complaints_seed(complaints,  "complaints_seed.sql")

    print_summary(faults, complaints)