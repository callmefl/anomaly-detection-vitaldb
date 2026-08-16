"""Implementazione degli algoritmi per la rilevazione di anomalie nei dati."""

import sys
from pathlib import Path
import datetime
import pandas as pd
import numpy as np
from sklearn.ensemble import IsolationForest
from sklearn.neural_network import MLPRegressor
from sklearn.preprocessing import StandardScaler
from sklearn.metrics import classification_report

sys.path.append(str(Path(__file__).resolve().parent.parent.parent))
from src import config

# Chiavi metrica coerenti con src/gold/load_mongo.py (VITAL_TRACKS con '/' -> '_')
HR_KEY = "Solar8000_HR"
SPO2_KEY = "Solar8000_PLETH_SPO2"
SBP_KEY = "Solar8000_NIBP_SBP"
DBP_KEY = "Solar8000_NIBP_DBP"
MBP_KEY = "Solar8000_NIBP_MBP"

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

def compute_shock_index(df, threshold=0.9):
    """Calcola lo Shock Index (HR / pressione sistolica) e la relativa anomalia clinica.

    Lo Shock Index è un indice clinico semplice ma consolidato in letteratura:
    valori sopra soglia (tipicamente 0.9) sono associati a instabilità
    emodinamica/rischio di shock.

    $$\\text{SI} = \\frac{\\text{HR}}{\\text{NIBP\\_SBP}}$$

    Args:
        df (pd.DataFrame): DataFrame con le colonne HR_KEY e SBP_KEY.
        threshold (float): Soglia sopra la quale il punto è marcato come anomalia.

    Returns:
        pd.DataFrame: Copia di df con le colonne aggiuntive 'shock_index'
            e 'shock_index_anomaly' (bool).
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
    """Applica la regola clinica di Ipotensione Severa.

    Un punto è marcato come anomalia clinica se **entrambe** le condizioni
    sono verificate contemporaneamente:

    $$\\text{NIBP\\_MBP} < 65 \\text{ mmHg} \\quad \\text{E} \\quad \\text{SpO2} < 90\\%$$

    Args:
        df (pd.DataFrame): DataFrame con le colonne MBP_KEY e SPO2_KEY.
        mbp_threshold (float): Soglia di pressione media (mmHg).
        spo2_threshold (float): Soglia di saturazione O2 (%).

    Returns:
        pd.DataFrame: Copia di df con la colonna 'severe_hypotension_anomaly' (bool).
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
    """Applica in sequenza tutte le regole cliniche disponibili (Shock Index,
    Ipotensione Severa) su un DataFrame di serie vitali.

    Args:
        df (pd.DataFrame): DataFrame con le colonne delle metriche vitali.

    Returns:
        pd.DataFrame: DataFrame con le colonne di anomalia clinica aggiunte.
    """
    df = compute_shock_index(df)
    df = compute_severe_hypotension(df)
    return df


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

class AutoencoderDetector:
    """Anomaly detection non supervisionata basata sull'errore di ricostruzione.

    Usa un `MLPRegressor` come autoencoder "povero ma efficace": la rete viene
    addestrata a ricostruire il proprio input (target = input standardizzato).
    I punti con errore di ricostruzione (MSE) elevato, sopra il percentile
    scelto (default: 95°), vengono marcati come anomalie, sull'assunzione che
    pattern multivariati rari siano più difficili da ricostruire per la rete.
    """

    def __init__(self, hidden_layer_sizes=(8,), percentile=95.0, max_iter=500,
                 random_state=42, **kwargs):
        """Inizializza il detector.

        Args:
            hidden_layer_sizes (tuple): Dimensione del collo di bottiglia (bottleneck)
                dell'autoencoder, passata a MLPRegressor.
            percentile (float): Percentile dell'errore di ricostruzione sopra il
                quale un punto è considerato anomalo.
            max_iter (int): Numero massimo di iterazioni di addestramento.
            random_state (int): Seed per la riproducibilità.
        """
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
        """Addestra l'autoencoder e restituisce i punti anomali.

        Args:
            df (pd.DataFrame): DataFrame contenente le feature numeriche.
            feature_cols (list): Colonne da usare come feature.

        Returns:
            np.array: Booleani, True se il punto è un'anomalia.
        """
        X = df[feature_cols].fillna(df[feature_cols].mean())
        X_scaled = self.scaler.fit_transform(X)

        # Autoencoder "artigianale": la rete impara a ricostruire il proprio input
        self.model.fit(X_scaled, X_scaled)
        reconstructed = self.model.predict(X_scaled)

        mse = np.mean((X_scaled - reconstructed) ** 2, axis=1)
        self.reconstruction_error_ = mse
        self.threshold_ = np.percentile(mse, self.percentile)

        return mse > self.threshold_


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
        elif self.method == 'autoencoder':
            percentile = self.kwargs.get('percentile', 95.0)
            self._autoencoder = AutoencoderDetector(percentile=percentile)
            return self._autoencoder.fit_predict(df, feature_cols)
        else:
            raise ValueError(f"Metodo {self.method} non supportato.")


def save_anomalies_to_mongo(db, df_anomalies):
    """Scrive i punti anomali identificati nella collezione MongoDB `anomalies_detected`.

    Args:
        db: Oggetto database pymongo di destinazione.
        df_anomalies (pd.DataFrame): DataFrame con almeno le colonne 'case_id',
            'timestamp' e una o più colonne booleane di anomalia (es.
            'shock_index_anomaly', 'severe_hypotension_anomaly',
            'statistical_anomaly', 'isolation_forest_anomaly',
            'autoencoder_anomaly'). Vengono scritti solo i punti in cui
            almeno una colonna di anomalia è True.

    Returns:
        int: Numero di documenti inseriti in 'anomalies_detected'.
    """
    flag_cols = [c for c in df_anomalies.columns if c.endswith('_anomaly')]
    if not flag_cols:
        print("Nessuna colonna di anomalia trovata (suffisso '_anomaly'), nulla da salvare.")
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


def run_detection_pipeline(db, case_ids, statistical_z=3.0, if_contamination=0.05,
                            ae_percentile=95.0):
    """Esegue l'intera pipeline di detection su uno o più casi e ne salva i risultati.

    Combina regole cliniche (Shock Index, Ipotensione Severa) e metodi
    statistici/ML (Z-score, Isolation Forest, Autoencoder), poi persiste i
    punti anomali in MongoDB tramite `save_anomalies_to_mongo`.

    Args:
        db: Oggetto database pymongo.
        case_ids (list): Lista di case_id su cui eseguire la detection.
        statistical_z (float): Soglia Z-score per il metodo statistico.
        if_contamination (float): Contaminazione stimata per Isolation Forest.
        ae_percentile (float): Percentile di soglia per l'autoencoder.

    Returns:
        pd.DataFrame: DataFrame con tutte le colonne di anomalia calcolate,
            utile per ispezione/valutazione oltre al salvataggio su Mongo.
    """
    df = load_from_gold(db, case_ids)
    if df.empty:
        print("Nessun dato trovato in 'vital_signals' per i case_id richiesti.")
        return df

    feature_cols = [c for c in [HR_KEY, SPO2_KEY, SBP_KEY, DBP_KEY, MBP_KEY] if c in df.columns]

    df = apply_clinical_rules(df)
    df['statistical_anomaly'] = AnomalyDetector(method='statistical', z_threshold=statistical_z) \
        .fit_predict(df, feature_cols)
    df['isolation_forest_anomaly'] = AnomalyDetector(method='isolation_forest', contamination=if_contamination) \
        .fit_predict(df, feature_cols)
    df['autoencoder_anomaly'] = AnomalyDetector(method='autoencoder', percentile=ae_percentile) \
        .fit_predict(df, feature_cols)

    saved = save_anomalies_to_mongo(db, df)
    print(f"Anomalie salvate in 'anomalies_detected': {saved}")
    return df


if __name__ == '__main__':
    from pymongo import MongoClient

    client = MongoClient(config.MONGO_URI)
    db = client[config.DB_NAME]

    all_cases = [doc["case_id"] for doc in db['registry'].find({}, {"case_id": 1})]
    if not all_cases:
        print("Nessun caso presente nel registry: eseguire prima la pipeline Bronze/Silver/Gold.")
    else:
        run_detection_pipeline(db, all_cases)
