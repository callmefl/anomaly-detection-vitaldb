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
 * Gestisce la selezione dal menù a tendina
 */
function onCaseMenuSelect(val) {
  if (!val) return;
  const caseId = parseInt(val, 10);
  const target = casesCache.find(c => c.case_id === caseId);
  selectCase(caseId, target ? target.record_count : 0);
}

/**
 * Filtra la lista dei casi
 */
function filterCases() {
  const query = document.getElementById('caseSearch').value.trim().toLowerCase();
  const filtered = casesCache.filter(c => c.case_id.toString().includes(query));
  renderCases(filtered, currentCaseId);
}

/**
 * Seleziona un caso clinico
 */
function selectCase(caseId, recordCount) {
  currentCaseId = caseId;
  document.getElementById('caseSelectMenu').value = caseId;
  renderCases(casesCache, currentCaseId);
  
  document.getElementById('emptyState').classList.add('hidden');
  document.getElementById('caseDashboard').classList.remove('hidden');
  
  document.getElementById('dispCaseTitle').textContent = `Caso Clinico #${caseId}`;
  document.getElementById('kpiRecordCount').textContent = recordCount ? recordCount.toLocaleString() : '—';
  document.getElementById('kpiAnomalies').textContent = '0';
  
  document.getElementById('methodBreakdownContainer').classList.add('hidden');
  document.getElementById('anomalySection').classList.add('hidden');
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
  }
}

// Inizializzazione dell'applicazione al caricamento del DOM
document.addEventListener('DOMContentLoaded', () => {
  initTheme();
  checkApiHealth();
  loadCases();
});
