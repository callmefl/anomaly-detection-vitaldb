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
# Nota: 'nibp_age_s' (staleness NIBP in secondi, calcolata nel Silver) è deliberatamente esclusa:
# è un metadato di governance per auditing della qualità del dato pressorio, non una feature ML.
FEATURE_COLS = [
    HR_KEY, SPO2_KEY, SBP_KEY, DBP_KEY, MBP_KEY,
    'HR_rolling_mean', 'HR_rolling_std', 'HR_delta'
]


# Forza il line-buffering su stdout anche quando eseguito via 'docker exec' senza TTY (-t)
if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(line_buffering=True)
    except Exception:
        pass


def _fetch_gold_batch(db, batch_case_ids, outlier_metric_map):
    """Estrae e converte in DataFrame un singolo blocco di case_id da MongoDB Gold."""
    cursor = db['vital_signals'].find(
        {"metadata.case_id": {"$in": batch_case_ids}},
        {"_id": 0, "timestamp": 1, "metadata": 1, "metrics": 1, "quality_flags": 1}
    ).sort([("metadata.case_id", 1), ("timestamp", 1)])

    data = []
    for doc in cursor:
        row = {"timestamp": doc["timestamp"], "case_id": doc["metadata"]["case_id"]}
        row.update(doc.get("metrics", {}))
        qf = doc.get("quality_flags", {})
        if "nibp_age_s" in qf:
            row["nibp_age_s"] = qf["nibp_age_s"]
        for k, v in qf.items():
            if k.endswith("_outlier") or k.endswith("_imputed"):
                row[k] = v
        data.append(row)

    df_batch = pd.DataFrame(data)
    del data
    if df_batch.empty:
        return df_batch

    for out_flag, metric_col in outlier_metric_map.items():
        if out_flag in df_batch.columns and metric_col in df_batch.columns:
            df_batch.loc[df_batch[out_flag] == True, metric_col] = np.nan

    return df_batch


def load_from_gold(db, case_ids):
    """Estrae le serie temporali dei casi richiesti dalla Time Series Collection 'vital_signals' di MongoDB.
    
    Ordinamento deterministico per paziente e timestamp per evitare interleaving di serie temporali.
    Proietta quality_flags e nibp_age_s, mascherando a NaN le metriche contrassegnate come outlier fisiologici
    prima dell'applicazione di regole cliniche e modelli di machine learning.
    Per dataset ampi (> 25 casi), carica a blocchi per evitare picchi di RAM dovuti a milioni di dict Python.

    Args:
        db: Istanza PyMongo del database.
        case_ids (list): Lista degli identificativi numerici dei casi clinici da filtrare.
        
    Returns:
        pd.DataFrame: Tabella denormalizzata con colonne `timestamp`, `case_id`, metriche vitali e flag di qualità.
    """
    outlier_metric_map = {
        "HR_outlier": HR_KEY,
        "SPO2_outlier": SPO2_KEY,
        "SBP_outlier": SBP_KEY,
        "DBP_outlier": DBP_KEY,
        "MBP_outlier": MBP_KEY,
    }

    if len(case_ids) <= 25:
        return _fetch_gold_batch(db, case_ids, outlier_metric_map)

    sorted_ids = sorted(case_ids)
    batch_size = 25
    chunks = []
    total = len(sorted_ids)
    print(f"⏳ Estrazione serie temporali da MongoDB Gold per {total} casi...", flush=True)

    for i in range(0, total, batch_size):
        batch_ids = sorted_ids[i : i + batch_size]
        df_chunk = _fetch_gold_batch(db, batch_ids, outlier_metric_map)
        if not df_chunk.empty:
            chunks.append(df_chunk)
        done = min(i + batch_size, total)
        if done % 50 == 0 or done == total:
            print(f"  -> Caricati {done}/{total} casi da MongoDB Gold...", flush=True)

    if not chunks:
        return pd.DataFrame()

    return pd.concat(chunks, ignore_index=True)


def compute_shock_index(df, threshold=0.9, max_nibp_age_s=None):
    """Calcola lo Shock Index clinico ($SI = HR / SBP$) e contrassegna le instabilità emodinamiche.

    Se la colonna 'nibp_age_s' è presente, verifica che la misura pressoria sia sufficientemente
    recente (<= max_nibp_age_s) per evitare che un singolo valore propagato per LOCF
    generi falsi allarmi prolungati su misure obsolete.

    Args:
        df (pd.DataFrame): DataFrame contenente le colonne HR_KEY ed SBP_KEY.
        threshold (float): Soglia sopra la quale il punto è valutato come a rischio shock (default: 0.9).
        max_nibp_age_s (float, optional): Età massima in secondi della lettura NIBP valida.

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
    is_anomaly = (shock_index > threshold).fillna(False)

    if 'nibp_age_s' in df.columns:
        max_age = max_nibp_age_s if max_nibp_age_s is not None else getattr(config, "NIBP_MAX_CLINICAL_AGE_S", 120.0)
        is_fresh = (df['nibp_age_s'] <= max_age).fillna(False)
        is_anomaly = is_anomaly & is_fresh

    df['shock_index_anomaly'] = is_anomaly
    return df


def compute_severe_hypotension(df, mbp_threshold=65.0, spo2_threshold=90.0, max_nibp_age_s=None):
    """Applica la regola clinica di Ipotensione Severa (MBP < 65 mmHg AND SpO2 < 90%).

    Se 'nibp_age_s' è presente nel DataFrame, richiede che la misura pressoria non superi
    la soglia di freschezza clinica `max_nibp_age_s`.

    Args:
        df (pd.DataFrame): DataFrame contenente le colonne MBP_KEY ed SPO2_KEY.
        mbp_threshold (float): Soglia di pressione arteriosa media in mmHg (default: 65).
        spo2_threshold (float): Soglia di saturazione d'ossigeno in % (default: 90).
        max_nibp_age_s (float, optional): Età massima in secondi della lettura NIBP valida.

    Returns:
        pd.DataFrame: Copia del DataFrame arricchita con la colonna 'severe_hypotension_anomaly' (bool).
    """
    df = df.copy()
    if MBP_KEY not in df.columns or SPO2_KEY not in df.columns:
        df['severe_hypotension_anomaly'] = False
        return df

    low_mbp = df[MBP_KEY] < mbp_threshold
    low_spo2 = df[SPO2_KEY] < spo2_threshold
    is_anomaly = (low_mbp & low_spo2).fillna(False)

    if 'nibp_age_s' in df.columns:
        max_age = max_nibp_age_s if max_nibp_age_s is not None else getattr(config, "NIBP_MAX_CLINICAL_AGE_S", 120.0)
        is_fresh = (df['nibp_age_s'] <= max_age).fillna(False)
        is_anomaly = is_anomaly & is_fresh

    df['severe_hypotension_anomaly'] = is_anomaly
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

    Esegue l'imputazione locale strettamente per caso (se case_id è fornito) per evitare
    che valori di pazienti diversi si propaghino attraverso i confini dei casi.

    Args:
        df (pd.DataFrame): Matrice delle feature numeriche dei parametri vitali (opzionalmente con 'case_id').
        contamination (float): Proporzione stimata di punti anomali nello spazio campionario.

    Returns:
        np.array: Array booleano (True = anomalia rilevata).
    """
    if 'case_id' in df.columns:
        feat_cols = [c for c in df.columns if c != 'case_id']
        X = (
            df.groupby('case_id', sort=False)[feat_cols]
            .ffill()
            .groupby(df['case_id'], sort=False)
            .bfill()
            .fillna(0.0)
        )
    else:
        X = df.ffill().bfill().fillna(0.0)
    
    clf = IsolationForest(contamination=contamination, random_state=42)
    preds = clf.fit_predict(X)
    
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

    def _make_window_views_per_case(self, df, feature_cols):
        """Crea viste zero-copy (sliding_window_view) per ogni paziente senza concatenare gigabyte in RAM."""
        if 'case_id' in df.columns:
            X_df = (
                df.groupby('case_id', sort=False)[feature_cols]
                .ffill()
                .groupby(df['case_id'], sort=False)
                .bfill()
                .fillna(0.0)
            )
        else:
            X_df = df[feature_cols].ffill().bfill().fillna(0.0)

        X_scaled = self.scaler.fit_transform(X_df.values).astype(np.float32)
        del X_df
        df_scaled = pd.DataFrame(X_scaled, columns=feature_cols, index=df.index)

        windows_list = []
        target_indices = []

        if 'case_id' in df.columns:
            groups = df_scaled.groupby(df['case_id'], sort=False)
        else:
            groups = [(0, df_scaled)]

        for _, group in groups:
            vals = group.values
            T = len(vals)
            if T < self.window_size:
                continue
            # sliding_window_view: creazione finestre a costo di allocazione zero (zero-copy)
            wins = np.lib.stride_tricks.sliding_window_view(
                vals, window_shape=(self.window_size, vals.shape[1])
            ).squeeze(axis=1)
            windows_list.append(wins)
            # Mappa ogni finestra i all'indice del suo ultimo punto compreso (i + ws - 1)
            case_idx = group.index.values
            target_indices.append(case_idx[self.window_size - 1 :])

        if not windows_list:
            return [], np.array([], dtype=int)

        return windows_list, np.concatenate(target_indices)

    def _make_windows_per_case(self, df, feature_cols):
        """Metodo di compatibilità che restituisce le finestre concatenate."""
        windows_list, target_indices = self._make_window_views_per_case(df, feature_cols)
        if not windows_list:
            return np.empty((0, self.window_size, len(feature_cols)), dtype=np.float32), target_indices
        return np.concatenate(windows_list, axis=0), target_indices

    def fit_predict(self, df, feature_cols):
        if not _TORCH_AVAILABLE or LSTMAutoencoder is None:
            raise ImportError(
                "PyTorch non è installato. Aggiungere 'torch>=2.0' a requirements.txt "
                "ed eseguire 'pip install torch' per usare LSTMAutoencoderDetector."
            )
        # Fissazione deterministica dei seed per riproducibilità scientifica
        torch.manual_seed(42)
        np.random.seed(42)

        windows_list, target_indices = self._make_window_views_per_case(df, feature_cols)
        counts = np.array([len(w) for w in windows_list], dtype=int)
        total_windows = int(counts.sum()) if len(counts) > 0 else 0
        
        if total_windows == 0:
            self.threshold_ = 0.0
            self.reconstruction_error_ = np.zeros(len(df))
            return np.zeros(len(df), dtype=bool)

        n_features = len(feature_cols)
        self.model = _make_lstm_autoencoder_class()(n_features=n_features, hidden_size=self.hidden_size)
        optimizer = torch.optim.Adam(self.model.parameters(), lr=1e-3)
        loss_fn = nn.MSELoss()

        # Sottoinsieme rappresentativo uniforme per il training (max 15.000 finestre)
        # Estratto direttamente dalle viste zero-copy senza allocare l'intero tensore da 3.3 GB
        max_train = 15000
        if total_windows > max_train:
            indices = np.linspace(0, total_windows - 1, max_train, dtype=int)
            cum_counts = np.cumsum(counts)
            group_ids = np.searchsorted(cum_counts, indices, side='right')
            starts = np.concatenate(([0], cum_counts[:-1]))
            local_ids = indices - starts[group_ids]
            train_np = np.empty((max_train, self.window_size, n_features), dtype=np.float32)
            for k, (g_idx, l_idx) in enumerate(zip(group_ids, local_ids)):
                train_np[k] = windows_list[g_idx][l_idx]
            train_tensor = torch.from_numpy(train_np)
            n_epochs = min(self.epochs, 5)
        else:
            train_np = np.ascontiguousarray(np.concatenate(windows_list, axis=0), dtype=np.float32)
            train_tensor = torch.from_numpy(train_np)
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

        # Valutazione errore di ricostruzione su TUTTE le finestre a blocchi dalle viste zero-copy
        self.model.eval()
        eval_batch_size = 4096
        mse_list = []
        with torch.no_grad():
            for wins in windows_list:
                for start_idx in range(0, len(wins), eval_batch_size):
                    batch_np = np.ascontiguousarray(wins[start_idx : start_idx + eval_batch_size], dtype=np.float32)
                    batch_x = torch.from_numpy(batch_np)
                    reconstructed = self.model(batch_x)
                    # Calcola l'errore quadratico per ogni punto: (batch, T, features)
                    sq_err = (batch_x - reconstructed) ** 2
                    
                    # Media temporale per ogni feature
                    mean_time_err = torch.mean(sq_err, dim=1) # (batch, features)
                    
                    # Per evitare la diluizione causata da feature mancanti (che essendo costanti
                    # tramite ffill avrebbero errore 0), calcoliamo l'errore della finestra 
                    # come il MASSIMO errore tra tutte le feature, non la media.
                    batch_mse, _ = torch.max(mean_time_err, dim=1)
                    
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
            # Includi case_id se presente per consentire l'imputazione isolata per paziente
            cols = list(feature_cols)
            if 'case_id' in df.columns and 'case_id' not in cols:
                cols.append('case_id')
            return detect_isolation_forest(df[cols], contamination)
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

    Garantisce idempotenza sicura:
    1. Prepara e inserisce prima i nuovi record marcati con il timestamp corrente (detected_at = now).
    2. Solo ad inserimento avvenuto con successo, rimuove le anomalie obsolete dei casi esaminati (detected_at != now).
    In questo modo, se l'inserimento dovesse fallire a causa di un'eccezione o crash del database,
    lo stato precedente non viene cancellato alla cieca.

    Args:
        db: Istanza PyMongo del database.
        df_anomalies (pd.DataFrame): DataFrame contenente le colonne di anomalia calcolate.

    Returns:
        int: Numero di documenti scritti nella collezione `anomalies_detected`.
    """
    flag_cols = [c for c in df_anomalies.columns if c.endswith('_anomaly')]
    if not flag_cols:
        return 0

    # Ricava tutti i case_id elaborati in questa esecuzione
    if 'case_id' in df_anomalies.columns:
        analyzed_cases = [int(cid) for cid in df_anomalies['case_id'].dropna().unique()]
    else:
        analyzed_cases = []

    now = datetime.datetime.now(datetime.timezone.utc)
    any_anomaly = df_anomalies[flag_cols].any(axis=1)
    rows = df_anomalies[any_anomaly]

    method_names = [c.replace('_anomaly', '') for c in flag_cols]
    flag_matrix = rows[flag_cols].to_numpy(dtype=bool)
    case_ids_arr = rows["case_id"].to_numpy(dtype=int)
    timestamps_list = rows["timestamp"].tolist()

    documents = [
        {
            "case_id": int(cid),
            "timestamp": ts,
            "methods": [method_names[j] for j, is_active in enumerate(flags) if is_active],
            "detected_at": now,
        }
        for cid, ts, flags in zip(case_ids_arr, timestamps_list, flag_matrix)
    ]

    # 1. Inserisce prima i nuovi documenti (a blocchi da 20.000 se il payload è molto grande)
    if documents:
        if len(documents) <= 20000:
            db['anomalies_detected'].insert_many(documents)
        else:
            for i in range(0, len(documents), 20000):
                db['anomalies_detected'].insert_many(documents[i : i + 20000])

    # 2. Rimuove le vecchie anomalie (detected_at != now) per i casi esaminati
    # Se un caso è tornato a 0 anomalie, i suoi vecchi record vengono comunque ripuliti
    if analyzed_cases:
        db['anomalies_detected'].delete_many({
            "case_id": {"$in": analyzed_cases},
            "detected_at": {"$ne": now}
        })

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
    print(f"=== AVVIO ANOMALY DETECTION SU {len(case_ids)} CASI ===", flush=True)
    df = load_from_gold(db, case_ids)
    if df.empty:
        print("⚠️ Nessun dato temporale recuperato per i casi richiesti.", flush=True)
        return df

    print(f"✓ Caricati {len(df)} record totali. Calcolo feature dinamiche...", flush=True)
    # Calcolo feature dinamiche strettamente raggruppate per singolo paziente (Cython nativo, veloce)
    g = df.groupby("case_id", sort=False)[HR_KEY]
    df['HR_rolling_mean'] = g.rolling(5, min_periods=1).mean().reset_index(level=0, drop=True)
    df['HR_rolling_std']  = g.rolling(5, min_periods=1).std().reset_index(level=0, drop=True).fillna(0.0)
    df['HR_delta']        = g.diff().fillna(0.0)
    feature_cols = [c for c in FEATURE_COLS if c in df.columns]

    # 1. Regole Cliniche (Shock Index & Ipotensione Severa)
    print("  [1/3] Calcolo Regole Cliniche (Shock Index & Ipotensione Severa)...", flush=True)
    df = apply_clinical_rules(df)

    # 2. Isolation Forest ML
    print("  [2/3] Addestramento ed inferenza Isolation Forest...", flush=True)
    df['isolation_forest_anomaly'] = AnomalyDetector(method='isolation_forest', contamination=if_contamination) \
        .fit_predict(df, feature_cols)

    # 3. LSTM Autoencoder Neurale ML
    print("  [3/3] Addestramento ed inferenza LSTM Autoencoder PyTorch...", flush=True)
    df['autoencoder_anomaly'] = AnomalyDetector(method='lstm_autoencoder', percentile=ae_percentile) \
        .fit_predict(df, feature_cols)

    # Persistenza risultati su MongoDB
    print("  [4/4] Salvataggio anomalie su MongoDB Gold...", flush=True)
    saved = save_anomalies_to_mongo(db, df)
    print(f"✓ {saved} punti anomali registrati nella collezione 'anomalies_detected'.", flush=True)
    return df


if __name__ == '__main__':
    from pymongo import MongoClient

    client = MongoClient(config.MONGO_URI)
    db = client[config.DB_NAME]

    all_cases = [doc["case_id"] for doc in db['registry'].find(
        {"$or": [{"status": "committed"}, {"status": {"$exists": False}}]},
        {"case_id": 1}
    )]
    if not all_cases:
        print("⚠️ Nessun caso committed nel registry. Eseguire prima il caricamento dei casi.", flush=True)
    else:
        run_detection_pipeline(db, all_cases)

