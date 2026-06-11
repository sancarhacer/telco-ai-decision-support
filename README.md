# MCP Based AI Powered Telecommunications Network Analysis and Decision Support System

Bu proje, telekom NOC senaryolari icin:
- mock veri uretimi,
- anomali tespiti,
- MCP tool katmani,
- FastAPI servisleri,
- LLM destekli chat (tool-calling),
- basit frontend
sunar.

## 1) Mimari Ozeti

- Veri kaynaklari: `network_metrics`, `faults`, `complaints`, `base_stations`
- Anomali ciktilari: `anomaly_results`
- `services.py`: tum sorgu/servis mantigi
- `main.py`: MCP server ve tool tanimlari
- `api.py`: FastAPI endpointleri + LLM tool-calling chat
- `frontend/`: chat arayuzu (`index.html`, `app.js`, `style.css`)

## 2) Proje Yapisi

- `api.py`
  - `GET /health`, `GET /metrics`, `GET /faults`, ...
  - `POST /chat` (LLM tool-calling)
  - Scheduler: mock data ve anomali job'lari
- `services.py`
  - Atomic servisler (`get_*_atomic_service`)
  - Klasik servisler (`get_*_service`)
- `jobs.py`
  - periyodik mock veri ve anomali job fonksiyonlari
- `mock_data_generator.py`
- `anomaly_detector.py`
- `main.py` (MCP tools)

## 3) Kurulum

```bash
pip install -r requirements.txt
```

## 4) Ortam Degiskenleri (.env)

`.env.example` dosyasini `.env` yapip doldurun.

### Zorunlu (DB)

```env
DB_HOST=localhost
DB_PORT=5432
DB_NAME=network_mcp
DB_USER=postgres
DB_PASSWORD=your_password
```

### LLM (Groq/OpenAI uyumlu)

Groq kullaniyorsaniz:

```env
GROQ_API_KEY=gsk_...
GROQ_BASE_URL=https://api.groq.com/openai/v1
GROQ_MODEL=llama-3.3-70b-versatile
```

Not:
- `GROQ_API_KEY` yoksa sistem `OPENAI_API_KEY` de dener.
- Anahtar yoksa `/chat` endpointi `500` doner.

## 5) Calistirma

### A) MCP Server

```bash
python main.py
```

Inspector ile test:

```bash
npx @modelcontextprotocol/inspector python main.py
```

### B) FastAPI Server

```bash
uvicorn api:app --host 127.0.0.1 --port 8000 --reload
```

Kontrol:
- `http://127.0.0.1:8000/`
- `http://127.0.0.1:8000/health`
- `http://127.0.0.1:8000/docs`

### C) Frontend

```bash
cd frontend
python -m http.server 5500
```

Tarayici:
- `http://127.0.0.1:5500`

Frontend chat, backend'deki `POST /chat` endpointine gider ve LLM cevabini render eder.

## 6) `/chat` Tool-Calling Akisi

`api.py` icindeki LLM loop, modele su tool'lari tanitir:

- `get_faults` -> `get_faults_atomic_service`
- `get_complaints` -> `get_complaints_atomic_service`
- `get_anomalies` -> `get_anomalies_atomic_service`
- `get_metrics` -> `get_metrics_atomic_service`
- `get_stations` -> `get_stations_atomic_service`

Model, soruya gore uygun tool'u cagirir; backend sonucu modele geri verir; model final JSON uretir.

## 7) `/chat` Request/Response

### Request

```json
{
  "message": "Son 1 saatte Buca'da kritik fault var mi?",
  "limit": 20
}
```

### Response (ornek)

```json
{
  "summary": "Buca bolgesinde kritik fault kayitlari bulundu.",
  "evidence": [
    { "cell_id": "CELL_012", "severity": "CRITICAL" }
  ],
  "root_cause": "Muhtemel backhaul/fiber kaynakli kesinti",
  "recommended_actions": [
    "Acil saha ekibi yonlendir",
    "Ilgili hucrelerde trafik yeniden dagitimi yap"
  ],
  "confidence": 0.84
}
```

## 8) Scheduler ve Mock Veri

`api.py` lifespan icinde:
- `job_generate_mock_data`: her 30 saniye
- `job_run_anomaly_detection`: her 120 saniye

Bu sayede demo ortami canli kalir ve `/chat` sorgularinda veri bulunmasi kolaylasir.

## 9) MCP Tool Listesi

1. `get_metrics(...)`
2. `get_anomalies(...)`
3. `get_faults(...)`
4. `get_complaints(...)`
5. `get_station(...)`

## 10) Sik Hatalar ve Cozum

- `Missing credentials` / `GROQ_API_KEY tanimli degil`
  - `.env` icine `GROQ_API_KEY` ekleyin
  - Uvicorn'u yeniden baslatin
- Tool schema validation (`expected integer, got string`)
  - `api.py` icinde tool arguman coercion zaten eklidir (`window_min`, `limit`, `only_anomalies`)
- `/chat` 500
  - DB baglantisini, `.env` degerlerini ve Groq key'ini kontrol edin
- Frontend cevap gormuyor
  - frontend'in dogru backend URL'sine (`http://127.0.0.1:8000`) gittigini kontrol edin

## 11) Guvenlik Notlari

- Gercek sifreleri kodda tutmayin.
- `.env` dosyasini git'e eklemeyin.
- Anahtar sizarsa hemen rotate edin.
