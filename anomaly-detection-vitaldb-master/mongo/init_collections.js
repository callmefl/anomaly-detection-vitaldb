// Script di inizializzazione per MongoDB mongosh
// Utilizzo: mongosh mongodb://localhost:27017 init_collections.js

db = db.getSiblingDB('vitaldb_project');

// Creazione Time Series Collection
if (!db.getCollectionNames().includes("vital_signals")) {
    db.createCollection(
        "vital_signals",
        {
            timeseries: {
                timeField: "timestamp",
                metaField: "metadata",
                granularity: "seconds"
            }
        }
    );
    print("✓ Collezione time-series 'vital_signals' creata con successo.");
} else {
    print("ℹ Collezione 'vital_signals' già esistente.");
}

// Creazione indici utili sulla Time Series
db.vital_signals.createIndex({ "metadata.case_id": 1, "timestamp": 1 });
print("✓ Indici su 'vital_signals' creati.");

// Creazione Registry per tracking ingestione
if (!db.getCollectionNames().includes("registry")) {
    db.createCollection("registry");
    print("✓ Collezione 'registry' creata.");
} else {
    print("ℹ Collezione 'registry' già esistente.");
}
db.registry.createIndex({ "case_id": 1 }, { unique: true });
print("✓ Indice univoco su 'registry.case_id' creato.");
