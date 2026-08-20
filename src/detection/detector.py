"""Modulo per l'algoritmo multilivello di Anomaly Detection sui dati biometrici (Layer Gold).

Il modulo combina quattro diverse metodologie di detection:
1. **Shock Index Clinico**: Rapporto tra Frequenza Cardiaca e Pressione Sistolica ($SI > 0.9$).
2. **Ipotensione Severa Clinica**: Condizione simultanea di $NIBP\_MBP < 65\text{ mmHg}$ ed $SpO2 < 90\%$.
3. **Isolation Forest (ML)**: Algoritmo ad alberi di decisione per partizionamento spaziale non supervisionato degli inlier/outlier.
4. **Autoencoder Neurale (MLPRegressor)**: Rete neurale profonda addestrata a ricostruire il proprio input; individua anomalie multivariate ad alto errore di ricostruzione (MSE $> 95^\circ$ percentile).
"""

import sys
from pathlib import Path
import datetime
import pandas as pd
import numpy as np
from sklearn.ensemble import IsolationForest
from sklearn.neural_network import MLPRegressor
from sklearn.preprocessing import StandardScaler
from sklearn.metrics import classification_report

# Setup importazioni radice
sys.path.append(str(Path(__file__).resolve().parent.parent.parent))
from src import config

# Chiavi delle metriche omogeneizzate con il layer Gold di MongoDB
HR_KEY = "Solar8000_HR"
SPO2_KEY = "Solar8000_PLETH_SPO2"
SBP_KEY = "Solar8000_NIBP_SBP"
DBP_KEY = "Solar8000_NIBP_DBP"
MBP_KEY = "Solar8000_NIBP_MBP"


def load_from_gold(db, case_ids):
    """Estrae le serie temporali dei casi richiesti dalla Time Series Collection 'vital_signals' di MongoDB.
    
    Args:
        db: Istanza PyMongo del database.
        case_ids (list): Lista degli identificativi numerici dei casi clinici da filtrare.
        
    Returns:
        pd.DataFrame: Tabella denormalizzata con colonne `timestamp`, `case_id` e le metriche vitali.
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


def compute_shock_index(df, threshold=0.9):
    """Calcola lo Shock Index clinico ($SI = HR / SBP$) e contrassegna le instabilità emodinamiche.

    Args:
        df (pd.DataFrame): DataFrame contenente le colonne HR_KEY ed SBP_KEY.
        threshold (float): Soglia sopra la quale il punto è valutato come a rischio shock (default: 0.9).

    Returns:
        pd.DataFrame: Copia del DataFrame arricchita con 'shock_index' e 'shock_index_anomaly' (bool).
    """
    df = df.copy()
    if HR_KEY not in df.columns or SBP_KEY not in df.columns:
        df['shock_index'] = np.nan
        df['shock_index_anomaly'] = False
        return df

    with np.errstate(divide='ignore', invalid='ignore'):
        shock_index = df[HR_KEY] / df[SBP_KEY]

    df['shock_index'] = shock_index
    df['shock_index_anomaly'] = shock_index > threshold
    df['shock_index_anomaly'] = df['shock_index_anomaly'].fillna(False)
    return df


def compute_severe_hypotension(df, mbp_threshold=65.0, spo2_threshold=90.0):
    """Applica la regola clinica di Ipotensione Severa ($MBP < 65\text{ mmHg} \land SpO2 < 90\%$).

    Args:
        df (pd.DataFrame): DataFrame contenente le colonne MBP_KEY ed SPO2_KEY.
        mbp_threshold (float): Soglia di pressione arteriosa media in mmHg.
        spo2_threshold (float): Soglia di saturazione d'ossigeno in %.

    Returns:
        pd.DataFrame: Copia del DataFrame arricchita con la colonna 'severe_hypotension_anomaly' (bool).
    """
    df = df.copy()
    if MBP_KEY not in df.columns or SPO2_KEY not in df.columns:
        df['severe_hypotension_anomaly'] = False
        return df

    low_mbp = df[MBP_KEY] < mbp_threshold
    low_spo2 = df[SPO2_KEY] < spo2_threshold
    df['severe_hypotension_anomaly'] = (low_mbp & low_spo2).fillna(False)
    return df


def apply_clinical_rules(df):
    """Applica in sequenza tutte le regole cliniche basate sulla conoscenza del dominio medico."""
    df = compute_shock_index(df)
    df = compute_severe_hypotension(df)
    return df


def detect_statistical(series, z_threshold=3.0):
    """Identifica outlier statistici univariati basati sul punteggio z ($|Z| > 3.0$)."""
    mean = series.mean()
    std = series.std()
    
    if std == 0 or pd.isna(std):
        return pd.Series(False, index=series.index)
        
    z_scores = np.abs((series - mean) / std)
    return z_scores > z_threshold


def detect_isolation_forest(df, contamination=0.05):
    """Applica l'algoritmo non supervisionato Isolation Forest per identificare anomalie multivariate.

    Args:
        df (pd.DataFrame): Matrice delle feature numeriche dei parametri vitali.
        contamination (float): Proporzione stimata di punti anomali nello spazio campionario.

    Returns:
        np.array: Array booleano (True = anomalia rilevata).
    """
    df_clean = df.fillna(df.mean())
    
    clf = IsolationForest(contamination=contamination, random_state=42)
    preds = clf.fit_predict(df_clean)
    
    # Converte l'output di scikit-learn (-1 per outlier, 1 per inlier) in booleani
    return preds == -1


class AutoencoderDetector:
    """Modello di Anomaly Detection basato su Rete Neurale Deep Autoencoder (MLPRegressor).

    La rete apprende l'identità del segnale fisiologico normale comprimendo il vettore di input
    attraverso un livello nascosto a collo di bottiglia (*bottleneck*). I punti anomali generano
    un errore di ricostruzione (MSE) significativamente elevato oltre il 95° percentile.
    """

    def __init__(self, hidden_layer_sizes=(8,), percentile=95.0, max_iter=500, random_state=42, **kwargs):
        self.percentile = percentile
        self.scaler = StandardScaler()
        self.model = MLPRegressor(
            hidden_layer_sizes=hidden_layer_sizes,
            max_iter=max_iter,
            random_state=random_state,
            **kwargs,
        )
        self.threshold_ = None
        self.reconstruction_error_ = None

    def fit_predict(self, df, feature_cols):
        """Addestra l'autoencoder neurale e calcola la soglia del percentile per identificare le anomalie."""
        X = df[feature_cols].fillna(df[feature_cols].mean())
        X_scaled = self.scaler.fit_transform(X)

        # Addestramento non supervisionato: target = input standardizzato
        self.model.fit(X_scaled, X_scaled)
        reconstructed = self.model.predict(X_scaled)

        # Calcolo Mean Squared Error (MSE) per ciascun punto temporale
        mse = np.mean((X_scaled - reconstructed) ** 2, axis=1)
        self.reconstruction_error_ = mse
        self.threshold_ = np.percentile(mse, self.percentile)

        return mse > self.threshold_


def evaluate_detections(y_true, y_pred):
    """Stampa a schermo il report di classificazione per la valutazione dei modelli."""
    print("=== REPORT DI CLASSIFICAZIONE ANOMALY DETECTION ===")
    print(classification_report(y_true, y_pred, target_names=["Normale", "Anomalia"]))


class AnomalyDetector:
    """Classe wrapper unificata per eseguire selettivamente uno dei metodi di detection supportati."""
    
    def __init__(self, method='isolation_forest', **kwargs):
        self.method = method
        self.kwargs = kwargs
        
    def fit_predict(self, df, feature_cols):
        if self.method == 'isolation_forest':
            contamination = self.kwargs.get('contamination', 0.05)
            return detect_isolation_forest(df[feature_cols], contamination)
        elif self.method == 'statistical':
            z_threshold = self.kwargs.get('z_threshold', 3.0)
            anomalies = pd.DataFrame(index=df.index)
            for col in feature_cols:
                anomalies[col] = detect_statistical(df[col], z_threshold)
            return anomalies.any(axis=1)
        elif self.method == 'autoencoder':
            percentile = self.kwargs.get('percentile', 95.0)
            self._autoencoder = AutoencoderDetector(percentile=percentile)
            return self._autoencoder.fit_predict(df, feature_cols)
        else:
            raise ValueError(f"Metodo '{self.method}' non supportato.")


def save_anomalies_to_mongo(db, df_anomalies):
    """Persiste i punti anomali identificati all'interno della collezione MongoDB `anomalies_detected`.

    Args:
        db: Istanza PyMongo del database.
        df_anomalies (pd.DataFrame): DataFrame contenente le colonne di anomalia calcolate.

    Returns:
        int: Numero di documenti scritti nella collezione `anomalies_detected`.
    """
    flag_cols = [c for c in df_anomalies.columns if c.endswith('_anomaly')]
    if not flag_cols:
        return 0

    any_anomaly = df_anomalies[flag_cols].any(axis=1)
    rows = df_anomalies[any_anomaly]
    if rows.empty:
        return 0

    documents = []
    now = datetime.datetime.now(datetime.timezone.utc)
    for _, row in rows.iterrows():
        methods = [c.replace('_anomaly', '') for c in flag_cols if bool(row[c])]
        documents.append({
            "case_id": int(row["case_id"]),
            "timestamp": row["timestamp"],
            "methods": methods,
            "detected_at": now,
        })

    if documents:
        db['anomalies_detected'].insert_many(documents)
    return len(documents)


def run_detection_pipeline(db, case_ids, statistical_z=3.0, if_contamination=0.05, ae_percentile=95.0):
    """Esegue l'intera pipeline di Anomaly Detection (Regole Cliniche + Statistica + ML) su uno o più casi.

    I risultati vengono aggregati e salvati automaticamente su MongoDB Gold.
    """
    df = load_from_gold(db, case_ids)
    if df.empty:
        print("⚠️ Nessun dato temporale recuperato per i casi richiesti.")
        return df

    feature_cols = [c for c in [HR_KEY, SPO2_KEY, SBP_KEY, DBP_KEY, MBP_KEY] if c in df.columns]

    # 1. Regole Cliniche
    df = apply_clinical_rules(df)
    
    # 2. Metodo Statistico Z-Score
    df['statistical_anomaly'] = AnomalyDetector(method='statistical', z_threshold=statistical_z) \
        .fit_predict(df, feature_cols)
        
    # 3. Isolation Forest ML
    df['isolation_forest_anomaly'] = AnomalyDetector(method='isolation_forest', contamination=if_contamination) \
        .fit_predict(df, feature_cols)
        
    # 4. Autoencoder Neurale ML
    df['autoencoder_anomaly'] = AnomalyDetector(method='autoencoder', percentile=ae_percentile) \
        .fit_predict(df, feature_cols)

    # Persistenza risultati su MongoDB
    saved = save_anomalies_to_mongo(db, df)
    print(f"✓ {saved} punti anomali registrati nella collezione 'anomalies_detected'.")
    return df


if __name__ == '__main__':
    from pymongo import MongoClient

    client = MongoClient(config.MONGO_URI)
    db = client[config.DB_NAME]

    all_cases = [doc["case_id"] for doc in db['registry'].find({}, {"case_id": 1})]
    if not all_cases:
        print("⚠️ Nessun caso nel registry. Eseguire prima il caricamento dei casi.")
    else:
        run_detection_pipeline(db, all_cases)
