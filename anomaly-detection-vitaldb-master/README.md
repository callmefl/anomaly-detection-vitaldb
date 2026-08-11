# Anomaly Detection su Dati Biometrici (VitalDB)

Progetto universitario per il corso di New Generation Databases. L'obiettivo è l'estrazione, la pulizia, l'archiviazione e l'analisi di dati biometrici dal database VitalDB, applicando tecniche di Anomaly Detection.

## Architettura

La pipeline dei dati si divide nei seguenti layer:
- **Bronze**: Dati grezzi estratti da VitalDB, mantenuti nel loro formato originale senza trasformazioni e salvati in formato Parquet.
- **Silver**: Dati puliti, interpolati e partizionati in modo efficiente. Filtraggio di outlier fisiologici base.
- **Gold**: I dati di qualità Silver vengono caricati su collezioni Time Series all'interno di MongoDB.
- **Detection**: Moduli di Anomaly Detection per trovare pattern anomali sui dati serie storiche archiviati in MongoDB.

## Prerequisiti

- Python 3.12
- MongoDB 8.0
- Git

## Configurazione

1. Clonare la repository
2. Creare un virtual environment:
   ```bash
   python -m venv .venv
   .venv\Scripts\activate
   ```
3. Installare le dipendenze:
   ```bash
   pip install -r requirements.txt
   ```
4. Configurare il file `.env` basato sui propri parametri:
   ```env
   MONGO_URI=mongodb://localhost:27017
   DB_NAME=vitaldb_project
   ```
5. Inizializzare MongoDB tramite gli script in `mongo/` (ad es. usando `mongosh`).

## Struttura del Progetto

```
Progettox/
│
├── data/                  # Directory dei dati (ignorata da git)
│   ├── bronze/
│   ├── raw/
│   └── silver/
├── mongo/                 # Script mongosh per DB setup
├── notebooks/             # Jupyter Notebooks per EDA
├── src/                   # Codice sorgente Python
│   ├── bronze/
│   ├── silver/
│   ├── gold/
│   └── detection/
├── tests/                 # Test unitari
├── .env                   # Variabili ambiente
├── .gitignore
├── README.md
└── requirements.txt
```

## Autori
(Placeholder)

## Licenza
(Placeholder)
