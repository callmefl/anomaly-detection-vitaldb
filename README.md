# Anomaly Detection su Dati Biometrici (VitalDB)

Progetto universitario per il corso di **New Generation Databases**. L'obiettivo è l'estrazione, la pulizia, la governance e l'archiviazione di dati biometrici dal database fisiologico **VitalDB**, applicando una Medallion Architecture (Bronze $\rightarrow$ Silver $\rightarrow$ Gold su MongoDB 8.0 Time Series) ed algoritmi multilivello di Anomaly Detection (Regole Cliniche + Machine Learning non supervisionato).

---

## 🚀 Avvio Rapido con Docker

### Prerequisiti
- [Docker Desktop](https://www.docker.com/products/docker-desktop/) installato ed avviato.

### 1. Avviare l'intero stack containerizzato

```bash
docker compose up --build -d
```

Questo comando avvia ed orchestra automaticamente:
- **`vitaldb_mongo`**: Istanza di **MongoDB 8.0** avviata come Replica Set su porta `27017`.
- **`vitaldb_api`**: REST API **FastAPI** su porta `8000` con il modulo di Anomaly Detection ed i file della Dashboard.

### 2. Accesso all'Applicazione Web & API

* 📊 **Dashboard Web Interattiva**: [http://localhost:8000/dashboard/](http://localhost:8000/dashboard/)
* 📚 **Documentazione Swagger API**: [http://localhost:8000/docs](http://localhost:8000/docs)
* 🗄️ **MongoDB Connection String**: `mongodb://localhost:27017`

---

## 🧪 Esecuzione della Suite di Test (`pytest`)

È stata integrata una test suite completa (12 test unitari ed integrativi) che copre la configurazione, il data cleaning del layer Silver, l'anomaly detection e tutte le rotte REST dell'API FastAPI.

Per eseguire i test all'interno del container Docker:

```bash
docker exec vitaldb_api python -m pytest tests/ -v
```

Risultato atteso: `12 passed in ~3.9s (100% Success Rate)`.

---

## 📊 Risultati Empirici della Data Pipeline (50 Casi - 311.173 Record)

| Layer Architetturale | Formato / Storage | Occupazione Disco | Riduzione Spazio | Latenza Media Query |
| :--- | :--- | :--- | :--- | :--- |
| **BRONZE (Grezzo)** | Parquet Monolitico | 3.88 MB | 0 % (Ref) | 652.2 ms (Parquet Scan) |
| **SILVER (Pulito)** | Parquet Partizionato | 2.24 MB | -42.3 % | 380.5 ms |
| **GOLD (MongoDB Time Series)** | Collection BSON Bucket | **0.27 MB** | **-93.0 %** | **4.2 ms (>150x più veloce)** |

### Metriche Modelli Machine Learning (vs Pseudo-Ground Truth Clinico)
* **Isolation Forest**: Accuratezza Globale **92%**, Weighted F1-Score **0.92**.
* **Autoencoder Neurale (MLPRegressor)**: Accuratezza Globale **90%**, Weighted F1-Score **0.90**.

---

## 📁 Struttura del Repository

```
anomaly-detection-vitaldb/
│
├── api/                   # Backend REST API (FastAPI) & static mount
│   └── main.py
├── dashboard/             # Frontend Web Modulare (Clean Architecture)
│   ├── css/style.css      # Design System (Theme Toggle Light/Dark)
│   ├── js/charts.js       # Modulo grafico Chart.js
│   ├── js/components.js   # Modulo componenti UI & Modali Cliniche
│   ├── js/app.js          # Entrypoint JS & API calls
│   └── index.html         # Markup principale
├── data/                  # Directory dei dati (Bronze/Silver Parquet)
├── mongo/                 # Script mongosh di inizializzazione replica set
├── relazione/             # Relazione Accademica LaTeX (16 pagine, main.pdf)
├── src/                   # Codice sorgente Python
│   ├── bronze/            # Ingestione dati grezzi da VitalDB
│   ├── silver/            # Cleaning, interpolazione e partizionamento
│   ├── gold/              # Ingestion su MongoDB Time Series & registry catalog
│   ├── detection/         # Modulo Anomaly Detection (Clinica + ML)
│   └── analysis/          # Benchmark ETL e valutazione quantitativa ML
├── tests/                 # Suite di test unitari ed integrativi (pytest)
│   ├── test_config.py
│   ├── test_etl.py
│   ├── test_detection.py
│   └── test_api.py
├── docker-compose.yml     # Orchestrazione Docker
├── Dockerfile             # Container API Python
├── requirements.txt       # Dipendenze Python
└── README.md
```
