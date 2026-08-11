"""Implementazione degli algoritmi per la rilevazione di anomalie nei dati."""

import pandas as pd
import numpy as np
from sklearn.ensemble import IsolationForest
from sklearn.metrics import classification_report

def load_from_gold(db, case_ids):
    """Carica i dati dalla Time Series Collection in MongoDB per l'analisi.
    
    Args:
        db: Oggetto database pymongo.
        case_ids (list): Lista di case_id da filtrare.
        
    Returns:
        pd.DataFrame: DataFrame con le serie storiche estratte.
    """
    cursor = db['vital_signals'].find(
        {"metadata.case_id": {"$in": case_ids}},
        {"_id": 0, "timestamp": 1, "metadata": 1, "metrics": 1}
    ).sort("timestamp", 1)
    
    data = []
    for doc in cursor:
        row = {"timestamp": doc["timestamp"], "case_id": doc["metadata"]["case_id"]}
        row.update(doc.get("metrics", {}))
        data.append(row)
        
    return pd.DataFrame(data)

def detect_statistical(series, z_threshold=3.0):
    """Metodo statistico basato sullo Z-score per la rilevazione di anomalie.
    
    Args:
        series (pd.Series): Serie di dati numerici.
        z_threshold (float): Soglia per il punteggio Z.
        
    Returns:
        pd.Series: Booleani, True se è un'anomalia.
    """
    mean = series.mean()
    std = series.std()
    
    if std == 0:
        return pd.Series(False, index=series.index)
        
    z_scores = np.abs((series - mean) / std)
    return z_scores > z_threshold

def detect_isolation_forest(df, contamination=0.05):
    """Usa Isolation Forest di scikit-learn per anomaly detection multivariata.
    
    Args:
        df (pd.DataFrame): DataFrame contenente solo le features numeriche.
        contamination (float): Proporzione di anomalie attese.
        
    Returns:
        np.array: Predizioni, 1 per inlier, -1 per outlier. Ritorna booleani (True=anomalia).
    """
    # Rimuovi eventuali righe con NaN temporaneamente
    df_clean = df.fillna(df.mean())
    
    clf = IsolationForest(contamination=contamination, random_state=42)
    preds = clf.fit_predict(df_clean)
    
    # Converte -1 (anomalia) e 1 (normale) in booleani (True = anomalia)
    return preds == -1

def evaluate_detections(y_true, y_pred):
    """Valuta le performance del modello usando metriche di base.
    
    Args:
        y_true (array-like): Etichette reali (True se anomalia).
        y_pred (array-like): Predizioni (True se anomalia).
    """
    print("Risultati Anomaly Detection:")
    print(classification_report(y_true, y_pred, target_names=["Normale", "Anomalia"]))

class AnomalyDetector:
    """Wrapper per l'esecuzione strutturata della detection sui dati vitali."""
    
    def __init__(self, method='isolation_forest', **kwargs):
        self.method = method
        self.kwargs = kwargs
        
    def fit_predict(self, df, feature_cols):
        if self.method == 'isolation_forest':
            contamination = self.kwargs.get('contamination', 0.05)
            return detect_isolation_forest(df[feature_cols], contamination)
        elif self.method == 'statistical':
            # Applicato per colonna, ritorna un'anomalia se almeno una feature è anomala
            z_threshold = self.kwargs.get('z_threshold', 3.0)
            anomalies = pd.DataFrame(index=df.index)
            for col in feature_cols:
                anomalies[col] = detect_statistical(df[col], z_threshold)
            return anomalies.any(axis=1)
        else:
            raise ValueError(f"Metodo {self.method} non supportato.")
