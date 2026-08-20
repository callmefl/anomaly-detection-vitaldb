# Anomaly Detection su Dati Biometrici (VitalDB)

Progetto universitario per il corso di New Generation Databases. L'obiettivo è l'estrazione, la pulizia, l'archiviazione e l'analisi di dati biometrici dal database VitalDB, applicando tecniche di Anomaly Detection.

## Architettura

La pipeline dei dati si divide nei seguenti layer:
- **Bronze**: Dati grezzi estratti da VitalDB, mantenuti nel loro formato originale senza trasformazioni e salvati in formato Parquet.
- **Silver**: Dati puliti, interpolati e partizionati per reparto chirurgico. Filtraggio di outlier fisiologici base.
- **Gold**: I dati di qualità Silver vengono caricati su collezioni Time Series all'interno di MongoDB.
- **Detection**: Moduli di Anomaly Detection (Isolation Forest, Autoencoder, regole cliniche) per trovare pattern anomali sui dati serie storiche archiviati in MongoDB.

## Avvio Rapido con Docker

### Prerequisiti
- [Docker Desktop](https://www.docker.com/products/docker-desktop/)
- [MongoDB Compass](https://www.mongodb.com/products/tools/compass) (opzionale, per esplorare il database via GUI)

### 1. Avviare i container

```bash
docker compose up --build -d
```

Questo comando avvia automaticamente:
- **MongoDB 8.0** con Replica Set configurato (porta `27017`)
- **API FastAPI** con tutte le dipendenze Python (porta `8000`)

### 2. Popolare il database

```bash
# Download dati grezzi da VitalDB (Layer Bronze)
docker exec vitaldb_api python src/bronze/download.py

# Pulizia e partizionamento (Layer Silver)
docker exec vitaldb_api python src/silver/clean.py

# Caricamento su MongoDB Time Series (Layer Gold)
docker exec vitaldb_api python src/gold/load_mongo.py
```

### 3. Utilizzare l'applicazione

- **Dashboard Web**: Aprire `dashboard/index.html` nel browser
- **API Swagger**: http://localhost:8000/docs
- **MongoDB Compass**: Connettersi a `mongodb://localhost:27017`

### 4. Gestione dei container

```bash
# Vedere lo stato dei container
docker ps

# Leggere i log dell'API
docker logs -f vitaldb_api

# Stoppare tutto
docker compose down

# Stoppare e rimuovere anche i dati del database
docker compose down -v
```


## Struttura del Progetto

```
anomaly-detection-vitaldb/
│
├── api/                   # REST API (FastAPI)
│   └── main.py
├── dashboard/             # Frontend web (grafici interattivi)
│   └── index.html
├── data/                  # Directory dei dati (ignorata da git)
│   ├── bronze/
│   └── silver/
├── mongo/                 # Script mongosh per DB setup
├── relazione/             # Relazione accademica LaTeX (main.tex e 5 capitoli)
├── src/                   # Codice sorgente Python
│   ├── analysis/          # Query e aggregazioni MongoDB
│   ├── bronze/            # Download dati grezzi
│   ├── silver/            # Pulizia e partizionamento
│   ├── gold/              # Caricamento su MongoDB
│   └── detection/         # Algoritmi di anomaly detection
├── tests/                 # Test unitari
├── docker-compose.yml     # Orchestrazione container
├── Dockerfile             # Immagine API Python
├── requirements.txt       # Dipendenze Python
└── README.md
```

## Autori
(Placeholder)

## Licenza
(Placeholder)
