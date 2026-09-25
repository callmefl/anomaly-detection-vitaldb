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
try:
    import torch
    import torch.nn as nn
    _TORCH_AVAILABLE = True
except ImportError:
    _TORCH_AVAILABLE = False

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


def _make_lstm_autoencoder_class():
    """Costruisce la classe LSTMAutoencoder come nn.Module solo se PyTorch è disponibile."""
    if not _TORCH_AVAILABLE:
        return None

    class _LSTMAutoencoder(nn.Module):
        """Architettura LSTM Autoencoder (nn.Module) per anomaly detection su serie temporali."""

        def __init__(self, n_features, hidden_size=32, n_layers=1):
            super().__init__()
            # Encoder LSTM: comprime la sequenza in un vettore latente
            self.encoder = nn.LSTM(n_features, hidden_size, n_layers, batch_first=True)
            # Decoder LSTM: ricostruisce la sequenza originale dal vettore latente
            self.decoder = nn.LSTM(hidden_size, n_features, n_layers, batch_first=True)

        def forward(self, x):
            # x ha forma (batch, T, n_features)
            _, (hidden, _) = self.encoder(x)
            # Ripete il vettore latente per ogni timestep della sequenza
            context = hidden.permute(1, 0, 2).repeat(1, x.size(1), 1)
            output, _ = self.decoder(context)
            return output  # stessa forma di x

    return _LSTMAutoencoder


# Classe concreta: è None se torch non è installato; viene istanziata in LSTMAutoencoderDetector
LSTMAutoencoder = _make_lstm_autoencoder_class()
    
    
class LSTMAutoencoderDetector:
    """Detector basato su vero LSTM Autoencoder — addestrato su finestre temporali."""
    
    def __init__(self, window_size=30, hidden_size=32, epochs=20, percentile=95.0):
        self.window_size = window_size   # N campioni consecutivi per finestra
        self.hidden_size = hidden_size   # Dimensione bottleneck
        self.epochs = epochs
        self.percentile = percentile
        self.scaler = StandardScaler()
        self.model = None
    def _make_windows(self, X_scaled):
        """Divide la serie in finestre scorrevoli di dimensione window_size."""
        T = len(X_scaled)
        windows = []
        for i in range(T - self.window_size):
            windows.append(X_scaled[i : i + self.window_size])
        return np.array(windows)  # (N_windows, window_size, n_features)
    def fit_predict(self, df, feature_cols):
        if not _TORCH_AVAILABLE or LSTMAutoencoder is None:
            raise ImportError(
                "PyTorch non è installato. Aggiungere 'torch>=2.0' a requirements.txt "
                "ed eseguire 'pip install torch' per usare LSTMAutoencoderDetector."
            )
        X = df[feature_cols].fillna(df[feature_cols].mean()).values
        X_scaled = self.scaler.fit_transform(X)
        windows = self._make_windows(X_scaled)
        n_features = len(feature_cols)
        self.model = LSTMAutoencoder(n_features=n_features, hidden_size=self.hidden_size)
        optimizer = torch.optim.Adam(self.model.parameters(), lr=1e-3)
        loss_fn = nn.MSELoss()
        X_tensor = torch.tensor(windows, dtype=torch.float32)
        # Training
        self.model.train()
        for epoch in range(self.epochs):
            optimizer.zero_grad()
            output = self.model(X_tensor)
            loss = loss_fn(output, X_tensor)
            loss.backward()
            optimizer.step()
        # Calcolo errore di ricostruzione per ogni finestra
        self.model.eval()
        with torch.no_grad():
            reconstructed = self.model(X_tensor).numpy()
        mse_per_window = np.mean((windows - reconstructed) ** 2, axis=(1, 2))
        # Mappa l'errore da finestre → punti temporali originali
        mse_per_point = np.full(len(df), 0.0)
        for i, err in enumerate(mse_per_window):
            mse_per_point[i + self.window_size] = max(mse_per_point[i + self.window_size], err)
        threshold = np.percentile(mse_per_window, self.percentile)
        return mse_per_point > threshold


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
        elif self.method in ('lstm_autoencoder', 'autoencoder'):
            percentile = self.kwargs.get('percentile', 95.0)
            self._autoencoder = LSTMAutoencoderDetector(percentile=percentile)
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
        # Idempotenza multi-caso: rimuove TUTTE le anomalie dei casi coinvolti prima di riscrivere
        affected_cases = list({d["case_id"] for d in documents})
        db['anomalies_detected'].delete_many({"case_id": {"$in": affected_cases}})
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
    df['HR_rolling_mean'] = df[HR_KEY].rolling(5).mean()
    df['HR_rolling_std']  = df[HR_KEY].rolling(5).std()
    df['HR_delta']        = df[HR_KEY].diff()
    feature_cols = [c for c in [HR_KEY, SPO2_KEY, SBP_KEY, DBP_KEY, MBP_KEY,'HR_rolling_mean', 'HR_rolling_std', 'HR_delta']
                    if c in df.columns]
    # 1. Regole Cliniche
    df = apply_clinical_rules(df)
    
    # 2. Metodo Statistico Z-Score
    df['statistical_anomaly'] = AnomalyDetector(method='statistical', z_threshold=statistical_z) \
        .fit_predict(df, feature_cols)
        
    # 3. Isolation Forest ML
    df['isolation_forest_anomaly'] = AnomalyDetector(method='isolation_forest', contamination=if_contamination) \
        .fit_predict(df, feature_cols)
        
    # 4. LSTM Autoencoder Neurale ML
    df['autoencoder_anomaly'] = AnomalyDetector(method='lstm_autoencoder', percentile=ae_percentile) \
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
