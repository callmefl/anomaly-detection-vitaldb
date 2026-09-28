"""Modulo per l'algoritmo multilivello di Anomaly Detection sui dati biometrici (Layer Gold).

Il modulo combina quattro diverse metodologie di detection:
1. Shock Index Clinico: Rapporto tra Frequenza Cardiaca e Pressione Sistolica (SI > 0.9).
2. Ipotensione Severa Clinica: Condizione simultanea di NIBP_MBP < 65 mmHg e SpO2 < 90%.
3. Isolation Forest (ML): Algoritmo ad alberi di decisione per partizionamento spaziale non supervisionato.
4. LSTM Autoencoder Neurale (PyTorch): Rete neurale ricorrente encoder-decoder addestrata su finestre
   temporali; individua anomalie multivariate ad alto errore di ricostruzione (MSE > 95 percentile).
"""

import sys
from pathlib import Path
import datetime
import pandas as pd
import numpy as np
from sklearn.ensemble import IsolationForest
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

# Lista centralizzata delle feature biometriche utilizzate sia nella pipeline che nella valutazione
FEATURE_COLS = [
    HR_KEY, SPO2_KEY, SBP_KEY, DBP_KEY, MBP_KEY,
    'HR_rolling_mean', 'HR_rolling_std', 'HR_delta'
]


def load_from_gold(db, case_ids):
    """Estrae le serie temporali dei casi richiesti dalla Time Series Collection 'vital_signals' di MongoDB.
    
    Ordinamento deterministico per paziente e timestamp per evitare interleaving di serie temporali.

    Args:
        db: Istanza PyMongo del database.
        case_ids (list): Lista degli identificativi numerici dei casi clinici da filtrare.
        
    Returns:
        pd.DataFrame: Tabella denormalizzata con colonne `timestamp`, `case_id` e le metriche vitali.
    """
    cursor = db['vital_signals'].find(
        {"metadata.case_id": {"$in": case_ids}},
        {"_id": 0, "timestamp": 1, "metadata": 1, "metrics": 1}
    ).sort([("metadata.case_id", 1), ("timestamp", 1)])
    
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
    """Applica la regola clinica di Ipotensione Severa (MBP < 65 mmHg AND SpO2 < 90%).

    Args:
        df (pd.DataFrame): DataFrame contenente le colonne MBP_KEY ed SPO2_KEY.
        mbp_threshold (float): Soglia di pressione arteriosa media in mmHg (default: 65).
        spo2_threshold (float): Soglia di saturazione d'ossigeno in % (default: 90).

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
        """Architettura LSTM Autoencoder (nn.Module) per anomaly detection su serie temporali.

        Comprende un layer Linear di proiezione sull'output del decoder per poter ricostruire
        valori standardizzati Z-score al di fuori dell'intervallo (-1, 1) imposto dalla tanh.
        """

        def __init__(self, n_features, hidden_size=32, n_layers=1):
            super().__init__()
            # Encoder LSTM: comprime la sequenza in un vettore latente
            self.encoder = nn.LSTM(n_features, hidden_size, n_layers, batch_first=True)
            # Decoder LSTM: decodifica il vettore latente nello spazio nascosto
            self.decoder = nn.LSTM(hidden_size, hidden_size, n_layers, batch_first=True)
            # Layer di proiezione lineare: mappa l'output dello stato nascosto nello spazio continuo R^n
            self.out = nn.Linear(hidden_size, n_features)

        def forward(self, x):
            # x ha forma (batch, T, n_features)
            _, (hidden, _) = self.encoder(x)
            # Ripete il vettore latente per ogni timestep della sequenza
            context = hidden.permute(1, 0, 2).repeat(1, x.size(1), 1)
            output, _ = self.decoder(context)
            return self.out(output)  # dimensione: (batch, T, n_features)

    return _LSTMAutoencoder


# Classe concreta: è None se torch non è installato; viene istanziata in LSTMAutoencoderDetector
LSTMAutoencoder = _make_lstm_autoencoder_class()
    
    
class LSTMAutoencoderDetector:
    """Detector basato su vero LSTM Autoencoder con proiettore lineare — addestrato su finestre temporali."""
    
    def __init__(self, window_size=30, hidden_size=32, epochs=10, percentile=95.0):
        self.window_size = window_size   # N campioni consecutivi per finestra
        self.hidden_size = hidden_size   # Dimensione bottleneck
        self.epochs = epochs
        self.percentile = percentile
        self.scaler = StandardScaler()
        self.model = None

    def _make_windows_per_case(self, df, feature_cols):
        """Divide la serie in finestre scorrevoli raggruppate per paziente (senza crossover tra casi)."""
        # Imputazione locale e scalatura globale
        if 'case_id' in df.columns:
            X_df = df.groupby('case_id')[feature_cols].transform(lambda g: g.ffill().bfill()).fillna(0.0)
        else:
            X_df = df[feature_cols].ffill().bfill().fillna(0.0)

        X_scaled = self.scaler.fit_transform(X_df.values)
        df_scaled = pd.DataFrame(X_scaled, columns=feature_cols, index=df.index)

        windows_list = []
        target_indices = []

        if 'case_id' in df.columns:
            df_scaled['case_id'] = df['case_id'].values
            groups = df_scaled.groupby('case_id', sort=False)
        else:
            groups = [(0, df_scaled)]

        for _, group in groups:
            cols = [c for c in group.columns if c != 'case_id']
            vals = group[cols].values
            T = len(vals)
            if T < self.window_size:
                continue
            # sliding_window_view: creazione finestre a costo di allocazione zero (zero-copy)
            wins = np.lib.stride_tricks.sliding_window_view(vals, window_shape=(self.window_size, vals.shape[1])).squeeze(axis=1)
            windows_list.append(wins)
            # Mappa ogni finestra i all'indice del suo ultimo punto compreso (i + ws - 1)
            case_idx = group.index.values
            target_indices.extend(case_idx[self.window_size - 1 :])

        if not windows_list:
            return np.empty((0, self.window_size, len(feature_cols))), np.array([], dtype=int)

        return np.concatenate(windows_list, axis=0), np.array(target_indices, dtype=int)

    def fit_predict(self, df, feature_cols):
        if not _TORCH_AVAILABLE or LSTMAutoencoder is None:
            raise ImportError(
                "PyTorch non è installato. Aggiungere 'torch>=2.0' a requirements.txt "
                "ed eseguire 'pip install torch' per usare LSTMAutoencoderDetector."
            )
        # Fissazione deterministica dei seed per riproducibilità scientifica
        torch.manual_seed(42)
        np.random.seed(42)

        windows, target_indices = self._make_windows_per_case(df, feature_cols)
        
        if len(windows) == 0:
            self.threshold_ = 0.0
            self.reconstruction_error_ = np.zeros(len(df))
            return np.zeros(len(df), dtype=bool)

        n_features = len(feature_cols)
        self.model = _make_lstm_autoencoder_class()(n_features=n_features, hidden_size=self.hidden_size)
        optimizer = torch.optim.Adam(self.model.parameters(), lr=1e-3)
        loss_fn = nn.MSELoss()
        X_tensor = torch.tensor(windows, dtype=torch.float32)

        # Sottoinsieme rappresentativo uniforme per il training (max 15.000 finestre)
        max_train = 15000
        if len(windows) > max_train:
            indices = np.linspace(0, len(windows) - 1, max_train, dtype=int)
            train_tensor = X_tensor[indices]
            n_epochs = min(self.epochs, 5)
        else:
            train_tensor = X_tensor
            n_epochs = self.epochs

        batch_sz = min(512, max(32, len(train_tensor)))
        train_dataset = torch.utils.data.TensorDataset(train_tensor)
        dataloader = torch.utils.data.DataLoader(train_dataset, batch_size=batch_sz, shuffle=True)

        # Training rapido
        self.model.train()
        for epoch in range(n_epochs):
            for (batch_x,) in dataloader:
                optimizer.zero_grad()
                output = self.model(batch_x)
                loss = loss_fn(output, batch_x)
                loss.backward()
                optimizer.step()

        # Valutazione errore di ricostruzione su TUTTE le finestre
        self.model.eval()
        eval_dataset = torch.utils.data.TensorDataset(X_tensor)
        eval_loader = torch.utils.data.DataLoader(eval_dataset, batch_size=4096, shuffle=False)
        mse_list = []
        with torch.no_grad():
            for (batch_x,) in eval_loader:
                reconstructed = self.model(batch_x)
                batch_mse = torch.mean((batch_x - reconstructed) ** 2, dim=(1, 2))
                mse_list.append(batch_mse.numpy())
        mse_per_window = np.concatenate(mse_list)

        # Mappatura corretta: assegna l'errore di ciascuna finestra esattamente al punto target (i + ws - 1)
        mse_per_point = np.zeros(len(df))
        mse_per_point[target_indices] = mse_per_window

        threshold = float(np.percentile(mse_per_window, self.percentile))
        self.threshold_ = threshold
        self.reconstruction_error_ = mse_per_point
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


def run_detection_pipeline(db, case_ids, if_contamination=0.05, ae_percentile=95.0, **kwargs):
    """Esegue l'intera pipeline di Anomaly Detection (Regole Cliniche + ML Multivariato) su uno o più casi.

    L'architettura poggia su 4 pilastri chiari:
    1. Shock Index (Regola Clinica)
    2. Ipotensione Severa (Regola Clinica)
    3. Isolation Forest (Machine Learning Spaziale)
    4. LSTM Autoencoder (Deep Learning Sequenziale PyTorch)

    I risultati vengono aggregati e salvati automaticamente su MongoDB Gold.
    """
    df = load_from_gold(db, case_ids)
    if df.empty:
        print("⚠️ Nessun dato temporale recuperato per i casi richiesti.")
        return df
    # Calcolo feature dinamiche strettamente raggruppate per singolo paziente (evita cross-contamination tra casi)
    g = df.groupby("case_id")[HR_KEY]
    df['HR_rolling_mean'] = g.transform(lambda s: s.rolling(5, min_periods=1).mean())
    df['HR_rolling_std']  = g.transform(lambda s: s.rolling(5, min_periods=1).std()).fillna(0.0)
    df['HR_delta']        = g.diff().fillna(0.0)
    feature_cols = [c for c in FEATURE_COLS if c in df.columns]
    print(f"=== AVVIO ANOMALY DETECTION SU {len(case_ids)} CASI ({len(df)} RECORD) ===")
    # 1. Regole Cliniche (Shock Index & Ipotensione Severa)
    print("  [1/3] Calcolo Regole Cliniche (Shock Index & Ipotensione Severa)...")
    df = apply_clinical_rules(df)

    # 2. Isolation Forest ML
    print("  [2/3] Addestramento ed inferenza Isolation Forest...")
    df['isolation_forest_anomaly'] = AnomalyDetector(method='isolation_forest', contamination=if_contamination) \
        .fit_predict(df, feature_cols)

    # 3. LSTM Autoencoder Neurale ML
    print("  [3/3] Addestramento ed inferenza LSTM Autoencoder PyTorch...")
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
