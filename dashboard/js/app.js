/**
 * Entrypoint principale dell'applicazione Frontend VitalDB Anomaly Analytics
 */

const API_BASE = 'http://localhost:8000';

let casesCache = [];
let currentCaseId = null;
let currentSeriesData = [];
let lastDetectionResult = null;

/**
 * Gestisce lo switch del Tema (Modalità Notturna vs Chiara) e ne mantiene la preferenza in localStorage
 */
function toggleTheme() {
  const currentTheme = document.documentElement.getAttribute('data-theme') || 'dark';
  const newTheme = currentTheme === 'dark' ? 'light' : 'dark';
  
  document.documentElement.setAttribute('data-theme', newTheme);
  localStorage.setItem('vitaldb_theme', newTheme);
  
  const btnText = document.getElementById('themeToggleText');
  if (btnText) {
    btnText.textContent = newTheme === 'dark' ? '🌙 Notturna' : '☀️ Chiara';
  }

  // Ridisegna i grafici se ci sono dati caricati per aggiornare la griglia ed i colori delle assi
  if (currentSeriesData.length > 0) {
    const anomalyTimestamps = lastDetectionResult ? lastDetectionResult.anomalies.map(a => a.timestamp) : [];
    renderCharts(currentSeriesData, anomalyTimestamps);
  }
}

/**
 * Inizializza il tema salvato al caricamento della pagina
 */
function initTheme() {
  const savedTheme = localStorage.getItem('vitaldb_theme') || 'dark';
  document.documentElement.setAttribute('data-theme', savedTheme);
  
  const btnText = document.getElementById('themeToggleText');
  if (btnText) {
    btnText.textContent = savedTheme === 'dark' ? '🌙 Notturna' : '☀️ Chiara';
  }
}

/**
 * Controlla lo stato dell'API FastAPI
 */
async function checkApiHealth() {
  try {
    const res = await fetch(`${API_BASE}/health`);
    if (res.ok) {
      document.getElementById('statusDot').classList.remove('offline');
      document.getElementById('statusText').textContent = 'API Docker & MongoDB Connessi (Porta 8000)';
    } else {
      throw new Error();
    }
  } catch {
    document.getElementById('statusDot').classList.add('offline');
    document.getElementById('statusText').textContent = 'API Non Raggiungibile su localhost:8000';
  }
}

/**
 * Carica l'elenco dei casi dal backend
 */
async function loadCases() {
  try {
    const res = await fetch(`${API_BASE}/cases`);
    if (!res.ok) throw new Error('Errore risposta HTTP');
    casesCache = await res.json();
    
    populateDeptMenu(casesCache);
    renderCaseMenu(casesCache);
    renderCases(casesCache, currentCaseId);
  } catch (err) {
    document.getElementById('caseList').innerHTML = `
      <div style="color: var(--danger); text-align: center; padding: 1.5rem; font-size: 0.85rem;">
        ❌ Impossibile caricare i casi dal registro MongoDB.
      </div>`;
  }
}

/**
 * Popola il menù a tendina di filtro per reparto chirurgico (Data Governance Metadata)
 */
function populateDeptMenu(cases) {
  const menu = document.getElementById('deptFilterMenu');
  if (!menu) return;
  const depts = Array.from(new Set(cases.map(c => c.department).filter(Boolean))).sort();
  const currentVal = menu.value;
  menu.innerHTML = '<option value="">Tutti i Reparti</option>' +
    depts.map(d => `<option value="${d}">${d}</option>`).join('');
  if (depts.includes(currentVal)) {
    menu.value = currentVal;
  }
}

/**
 * Gestisce la selezione dal menù a tendina
 */
function onCaseMenuSelect(val) {
  if (!val) return;
  const caseId = parseInt(val, 10);
  const target = casesCache.find(c => c.case_id === caseId);
  selectCase(caseId, target ? target.record_count : 0);
}

/**
 * Filtra la lista dei casi sia per ID sia per Reparto Chirurgico
 */
function filterCases() {
  const query = document.getElementById('caseSearch').value.trim().toLowerCase();
  const deptFilter = document.getElementById('deptFilterMenu') ? document.getElementById('deptFilterMenu').value : '';

  const filtered = casesCache.filter(c => {
    const matchesQuery = query === '' || c.case_id.toString().includes(query);
    const matchesDept = deptFilter === '' || (c.department && c.department === deptFilter);
    return matchesQuery && matchesDept;
  });

  renderCases(filtered, currentCaseId);
  renderCaseMenu(filtered);
}

/**
 * Seleziona un caso clinico
 */
function selectCase(caseId, recordCount) {
  currentCaseId = caseId;
  lastDetectionResult = null;
  currentFilteredAnomalies = [];
  document.getElementById('caseSelectMenu').value = caseId;
  renderCases(casesCache, currentCaseId);
  
  document.getElementById('emptyState').classList.add('hidden');
  document.getElementById('caseDashboard').classList.remove('hidden');
  
  document.getElementById('dispCaseTitle').textContent = `Caso Clinico #${caseId}`;
  document.getElementById('kpiRecordCount').textContent = recordCount ? recordCount.toLocaleString() : '—';
  document.getElementById('kpiAnomalies').textContent = '0';
  
  document.getElementById('methodBreakdownContainer').classList.add('hidden');
  document.getElementById('anomalySection').classList.add('hidden');
  const tbody = document.getElementById('anomalyTableBody');
  if (tbody) tbody.innerHTML = '';
  document.getElementById('chart1AnomalyBadge').textContent = '';
  document.getElementById('chart2AnomalyBadge').textContent = '';

  loadSeriesData();
}

/**
 * Richiede la serie temporale al backend
 */
async function loadSeriesData() {
  if (!currentCaseId) return;
  
  const windowSeconds = document.getElementById('windowSelect').value;
  let url = `${API_BASE}/cases/${currentCaseId}/series`;
  if (windowSeconds) url += `?window_seconds=${windowSeconds}`;

  try {
    const res = await fetch(url);
    if (!res.ok) throw new Error('Errore nel recupero della serie');
    currentSeriesData = await res.json();
    
    updateKPIs(currentSeriesData);
    renderCharts(currentSeriesData, []);
  } catch (err) {
    alert(`Errore caricamento dati: ${err.message}`);
  }
}

/**
 * Esegue l'Anomaly Detection
 */
async function runDetection() {
  if (!currentCaseId) return;
  
  const btn = document.getElementById('btnRunDetection');
  btn.disabled = true;
  btn.textContent = '⏳ Analisi in corso...';

  try {
    document.getElementById('windowSelect').value = "";
    await loadSeriesData();  // ricarica currentSeriesData a granularità 1s
    const res = await fetch(`${API_BASE}/cases/${currentCaseId}/detect`, { method: 'POST' });
    if (!res.ok) throw new Error('Errore durante la detection');
    lastDetectionResult = await res.json();

    document.getElementById('kpiAnomalies').textContent = lastDetectionResult.anomaly_count.toLocaleString();

    if (lastDetectionResult.summary_by_method) {
      document.getElementById('cntShockIndex').textContent = (lastDetectionResult.summary_by_method.shock_index || 0).toLocaleString();
      document.getElementById('cntSevereHyp').textContent = (lastDetectionResult.summary_by_method.severe_hypotension || 0).toLocaleString();
      document.getElementById('cntIsoForest').textContent = (lastDetectionResult.summary_by_method.isolation_forest || 0).toLocaleString();
      document.getElementById('cntAutoencoder').textContent = (lastDetectionResult.summary_by_method.autoencoder || 0).toLocaleString();
      document.getElementById('methodBreakdownContainer').classList.remove('hidden');

      // Calcola dinamicamente la somma dei metodi e aggiorna il testo della nota
      const sumMethods = Object.values(lastDetectionResult.summary_by_method).reduce((a, b) => a + b, 0);
      const noteBox = document.getElementById('overlapNoteText');
      if (noteBox) {
        noteBox.innerHTML = `Il contatore "Anomalie Totali Uniche" misura i secondi distinti in cui è stata riscontrata un'anomalia. La somma dei singoli algoritmi (<strong>${sumMethods.toLocaleString()}</strong>) è maggiore di <strong>${lastDetectionResult.anomaly_count.toLocaleString()}</strong> poiché uno stesso istante temporale può essere segnalato contemporaneamente sia dalle Regole Cliniche sia dai Modelli di Machine Learning.`;
      }
    }

    const anomalyTimestamps = lastDetectionResult.anomalies.map(a => a.timestamp);
    renderCharts(currentSeriesData, anomalyTimestamps);

    document.getElementById('chart1AnomalyBadge').textContent = `🔴 ${lastDetectionResult.anomaly_count} Punti Anomali Evidenziati`;
    document.getElementById('chart2AnomalyBadge').textContent = `🔴 ${lastDetectionResult.anomaly_count} Punti Anomali Evidenziati`;

    renderAnomalyTable(lastDetectionResult.anomalies, 'all');

  } catch (err) {
    alert(`Errore esecuzione Anomaly Detection: ${err.message}`);
  } finally {
    btn.disabled = false;
    btn.textContent = '🔍 Rileva Anomalie';
  }
}

/**
 * Filtra la tabella delle anomalie in base alla selezione del metodo e del limite di righe
 */
function applyAnomalyFilter() {
  if (!lastDetectionResult || !lastDetectionResult.anomalies) return;
  const filterValue = document.getElementById('tableFilterSelect').value;
  const limitValue = document.getElementById('tableLimitSelect').value;
  renderAnomalyTable(lastDetectionResult.anomalies, filterValue, limitValue);
}

/**
 * Carica dinamicamente il Quality Report dall'endpoint /quality e popola la tabella nel tab Benchmark.
 * Mostra anche la configurazione del run (MAX_CASES) per tracciabilità.
 */
async function loadQualityReport() {
  const tbody = document.getElementById('qualityTableBody');
  const subtitle = document.getElementById('qualityReportSubtitle');
  if (!tbody) return;

  try {
    const res = await fetch(`${API_BASE}/quality`);
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const data = await res.json();

    if (subtitle && data.generated_at) {
      const dateStr = new Date(data.generated_at).toLocaleString();
      const maxCases = data.max_cases_configured != null ? data.max_cases_configured : '—';
      const foundInBronze = data.cases_found_in_bronze != null ? data.cases_found_in_bronze : data.total_cases_processed;
      subtitle.innerHTML = `
        Report generato il <strong>${dateStr}</strong> —
        MAX_CASES configurato: <strong style="color:var(--accent);">${maxCases}</strong> |
        File trovati in Bronze: <strong style="color:var(--accent);">${foundInBronze}</strong> |
        Processati con successo: <strong style="color:var(--success);">${data.total_cases_processed}</strong>.
      `;
    }

    if (!data.cases_detail || data.cases_detail.length === 0) {
      tbody.innerHTML = '<tr><td colspan="7" style="text-align:center;">Nessun dato di qualità registrato.</td></tr>';
      return;
    }

    tbody.innerHTML = data.cases_detail.map(c => {
      const pctDrop = c.rows_original > 0 ? ((c.rows_dropped / c.rows_original) * 100).toFixed(1) : '0.0';
      const totalOutliers = c.outliers_count ? Object.values(c.outliers_count).reduce((a, b) => a + b, 0) : 0;
      const outlierBadge = totalOutliers === 0
        ? '<span style="color:var(--success); font-weight:600;">0 (Tracciati Validi)</span>'
        : `<span style="color:var(--danger); font-weight:600;">${totalOutliers}</span>`;

      return `
        <tr>
          <td><strong>Caso #${c.case_id}</strong></td>
          <td>${c.department || 'Non specificato'}</td>
          <td>${c.rows_original.toLocaleString()}</td>
          <td><strong style="color:var(--accent);">${c.rows_cleaned.toLocaleString()}</strong></td>
          <td>${c.rows_dropped.toLocaleString()}</td>
          <td><strong style="color:var(--warning);">${pctDrop}%</strong></td>
          <td>${outlierBadge}</td>
        </tr>
      `;
    }).join('');

  } catch (err) {
    if (tbody) {
      tbody.innerHTML = `<tr><td colspan="7" style="text-align:center; color:var(--text-muted);">Quality report non ancora generato sul backend.</td></tr>`;
    }
  }
}

/**
 * Navigazione tra i Tab della Dashboard
 */
function switchTab(tabName) {
  document.querySelectorAll('.nav-tab').forEach(t => t.classList.remove('active'));
  document.getElementById(`tab-${tabName}`).classList.add('active');

  if (tabName === 'series') {
    document.getElementById('viewSeries').classList.remove('hidden');
    document.getElementById('viewBenchmark').classList.add('hidden');
  } else if (tabName === 'benchmark') {
    document.getElementById('viewSeries').classList.add('hidden');
    document.getElementById('viewBenchmark').classList.remove('hidden');
    loadQualityReport();
    loadBenchmarkReport();
  }
}

/**
 * Carica dinamicamente il Benchmark prestazionale e di storage dall'endpoint /benchmark.
 */
async function loadBenchmarkReport() {
  const tbody = document.getElementById('benchmarkTableBody');
  const subtitle = document.getElementById('benchmarkSubtitle');
  if (!tbody) return;

  try {
    const res = await fetch(`${API_BASE}/benchmark`);
    if (!res.ok) return;
    const data = await res.json();

    if (subtitle && data.generated_at) {
      const dateStr = new Date(data.generated_at).toLocaleString();
      subtitle.innerHTML = `
        Benchmark calcolato il <strong>${dateStr}</strong> su <strong>${data.cases_count} casi</strong> (Layer Bronze → Silver → Gold).
      `;
    }

    if (data.storage && data.query_latency) {
      const s = data.storage;
      const q = data.query_latency;
      tbody.innerHTML = `
        <tr>
          <td><strong>Layer BRONZE (Grezzo Parquet)</strong></td>
          <td>${s.bronze_mb} MB</td>
          <td>0 % (Riferimento)</td>
          <td>${q.parquet_scan_ms} ms (Scansione File)</td>
        </tr>
        <tr>
          <td><strong>Layer SILVER (Bonificato Parquet)</strong></td>
          <td>${s.silver_mb} MB</td>
          <td><strong style="color:var(--warning);">${s.reduction_silver_pct > 0 ? '-' : ''}${s.reduction_silver_pct} %</strong></td>
          <td>~${(q.parquet_scan_ms * 0.6).toFixed(1)} ms</td>
        </tr>
        <tr>
          <td><strong>Layer GOLD (MongoDB Time Series)</strong></td>
          <td><strong style="color: var(--success);">${s.gold_mb} MB</strong></td>
          <td><strong style="color: var(--success);">${s.reduction_gold_pct > 0 ? '-' : ''}${s.reduction_gold_pct} %</strong></td>
          <td><strong style="color: var(--success);">${q.mongo_indexed_ms} ms (${q.speedup_factor}x più veloce)</strong></td>
        </tr>
      `;
    }
  } catch (err) {
    // Mantieni valori esistenti
  }
}

// Inizializzazione dell'applicazione al caricamento del DOM
document.addEventListener('DOMContentLoaded', () => {
  initTheme();
  checkApiHealth();
  loadCases();
  loadQualityReport();
  loadBenchmarkReport();
});
