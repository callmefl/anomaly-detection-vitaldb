// Definizione Schema per la collezione registry
// Utilizzo: mongosh mongodb://localhost:27017 registry_schema.js

db = db.getSiblingDB('vitaldb_project');

db.runCommand({
    collMod: "registry",
    validator: {
        $jsonSchema: {
            bsonType: "object",
            required: ["case_id", "schema_version", "provenance"],
            properties: {
                case_id: {
                    bsonType: "int",
                    description: "ID del caso VitalDB, richiesto e di tipo intero"
                },
                schema_version: {
                    bsonType: "string",
                    description: "Versione dello schema, richiesto e di tipo stringa"
                },
                record_count: {
                    bsonType: "int",
                    description: "Numero di record caricati per questo caso"
                },
                provenance: {
                    bsonType: "object",
                    required: ["step", "timestamp"],
                    properties: {
                        step: { bsonType: "string" },
                        timestamp: { bsonType: "date" }
                    }
                }
            }
        }
    },
    validationLevel: "strict",
    validationAction: "error"
});

print("✓ Schema validation aggiunto alla collezione 'registry'.");

// Inserimento tracce metadati in una collezione separata track_metadata per documentazione
if (!db.getCollectionNames().includes("track_metadata")) {
    db.createCollection("track_metadata");
}

const initialMetadata = [
    {
        sensor_name: "Solar8000",
        track_name: "HR",
        schema_version: "1.0",
        unit_of_measure: "bpm",
        expected_range: { min: 20, max: 250 }
    },
    {
        sensor_name: "Solar8000",
        track_name: "PLETH_SPO2",
        schema_version: "1.0",
        unit_of_measure: "%",
        expected_range: { min: 50, max: 100 }
    },
    {
        sensor_name: "Solar8000",
        track_name: "NIBP_SBP",
        schema_version: "1.0",
        unit_of_measure: "mmHg",
        expected_range: { min: 40, max: 250 }
    },
    {
        sensor_name: "Solar8000",
        track_name: "NIBP_DBP",
        schema_version: "1.0",
        unit_of_measure: "mmHg",
        expected_range: { min: 10, max: 200 }
    },
    {
        sensor_name: "Solar8000",
        track_name: "NIBP_MBP",
        schema_version: "1.0",
        unit_of_measure: "mmHg",
        expected_range: { min: 20, max: 220 }
    }
];

// Inserisce o aggiorna metadati delle tracce
initialMetadata.forEach(meta => {
    db.track_metadata.updateOne(
        { track_name: meta.track_name },
        { $set: meta },
        { upsert: true }
    );
});
print("✓ Metadati tracce iniziali caricati in 'track_metadata'.");
