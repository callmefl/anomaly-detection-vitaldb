// Schema Validation per la Time Series Collection 'vital_signals'
// Questo script viene eseguito da Docker nella fase di init (initdb.d)
// oppure manualmente: mongosh mongodb://localhost:27017 vital_signals_schema.js
//
// NOTA ARCHITETTURALE: MongoDB applica la validazione JSON Schema ai documenti
// *inseriti* nella Time Series Collection, non ai bucket compressi interni.
// validationLevel: "moderate" è scelto intenzionalmente per non interferire
// con la gestione interna dei bucket da parte del motore Time Series.

db = db.getSiblingDB('vitaldb_project');

db.runCommand({
    collMod: "vital_signals",
    validator: {
        $jsonSchema: {
            bsonType: "object",
            required: ["timestamp", "metadata", "metrics"],
            properties: {
                timestamp: {
                    bsonType: "date",
                    description: "Timestamp dell'istante di misurazione (timeField della Time Series Collection)"
                },
                metadata: {
                    bsonType: "object",
                    required: ["case_id", "sensor_name"],
                    description: "metaField: dati strutturati del paziente e del sensore per query pushdown sui bucket",
                    properties: {
                        case_id: {
                            bsonType: ["int", "long"],
                            description: "ID univoco del caso clinico VitalDB"
                        },
                        sensor_name: {
                            bsonType: "string",
                            description: "Nome del monitor sorgente (es. Solar8000)"
                        },
                        department: {
                            bsonType: ["string", "null"],
                            description: "Reparto chirurgico estratto dai dati clinici"
                        },
                        age: {
                            bsonType: ["int", "double", "null"],
                            description: "Età del paziente in anni"
                        },
                        sex: {
                            bsonType: ["string", "null"],
                            description: "Sesso del paziente (M/F)"
                        }
                    }
                },
                metrics: {
                    bsonType: "object",
                    description: "Valori numerici dei parametri vitali (chiavi sanitizzate con _ al posto di /)"
                },
                quality_flags: {
                    bsonType: "object",
                    description: "Flag booleani di Data Quality ereditati dal layer Silver (outlier fisiologici)"
                }
            }
        }
    },
    // moderate: valida solo i nuovi inserimenti, non tocca i documenti
    // già esistenti nei bucket compressi — scelta conservativa per TS Collection
    validationLevel: "moderate",
    validationAction: "error"
});

print("✓ Schema validation (moderate) aggiunto alla Time Series Collection 'vital_signals'.");
print("  Campi required: timestamp, metadata (con case_id + sensor_name), metrics.");
print("  quality_flags opzionale ma tipizzato per coerenza documentale.");
