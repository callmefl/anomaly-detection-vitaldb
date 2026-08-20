/**
 * Modulo Javascript per la gestione dei Grafici temporali Chart.js
 * Supporta la sincronizzazione dinamica dei temi (Modalità Notturna vs Chiara)
 */

let chartHrSpo2Instance = null;
let chartNibpInstance = null;

/**
 * Disegna i due grafici temporali Chart.js adattando dinamicamente la palette al tema attivo
 * 
 * @param {Array} data - Serie temporale dei parametri vitali
 * @param {Array} anomalyTimestamps - Array delle timestamp contrassegnate come anomale
 */
function renderCharts(data, anomalyTimestamps = []) {
  const isDark = (document.documentElement.getAttribute('data-theme') || 'dark') === 'dark';
  
  // Colori delle assi e griglie adattativi al tema
  const textColor = isDark ? '#9ca3af' : '#475569';
  const gridColor = isDark ? '#374151' : '#e2e8f0';

  const labels = data.map(d => d.timestamp);
  const anomalySet = new Set(anomalyTimestamps);

  // Overlay vettoriali sui punti anomali
  const hrAnomalyOverlay = data.map(d => anomalySet.has(d.timestamp) ? (d.Solar8000_HR ?? null) : null);
  const sbpAnomalyOverlay = data.map(d => anomalySet.has(d.timestamp) ? (d.Solar8000_NIBP_SBP ?? null) : null);

  // Distruzione delle istanze precedenti
  if (chartHrSpo2Instance) chartHrSpo2Instance.destroy();
  if (chartNibpInstance) chartNibpInstance.destroy();

  // 1. Grafico Frequenza Cardiaca & SpO2
  const ctx1 = document.getElementById('chartHrSpo2').getContext('2d');
  chartHrSpo2Instance = new Chart(ctx1, {
    type: 'line',
    data: {
      labels: labels,
      datasets: [
        {
          label: 'Frequenza Cardiaca (bpm)',
          data: data.map(d => d.Solar8000_HR ?? null),
          borderColor: isDark ? '#f43f5e' : '#dc2626',
          backgroundColor: isDark ? 'rgba(244, 63, 94, 0.08)' : 'rgba(220, 38, 38, 0.06)',
          borderWidth: 2, tension: 0.2, pointRadius: 0, fill: true
        },
        {
          label: 'Saturazione SpO₂ (%)',
          data: data.map(d => d.Solar8000_PLETH_SPO2 ?? null),
          borderColor: isDark ? '#06b6d4' : '#0284c7',
          backgroundColor: 'transparent',
          borderWidth: 2, tension: 0.2, pointRadius: 0
        },
        {
          label: '🔴 Anomalie Identificate',
          data: hrAnomalyOverlay,
          borderColor: isDark ? '#f43f5e' : '#dc2626',
          backgroundColor: isDark ? '#f43f5e' : '#dc2626',
          pointRadius: 6,
          pointHoverRadius: 9,
          showLine: false
        }
      ]
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      plugins: { legend: { labels: { color: textColor, font: { family: 'Inter', weight: '600', size: 11 } } } },
      scales: {
        x: { ticks: { color: textColor, maxTicksLimit: 10, font: { family: 'Inter', size: 10 } }, grid: { color: gridColor } },
        y: { ticks: { color: textColor, font: { family: 'JetBrains Mono', size: 10 } }, grid: { color: gridColor } }
      }
    }
  });

  // 2. Grafico Pressione Blood NIBP (SBP, DBP, MBP)
  const ctx2 = document.getElementById('chartNibp').getContext('2d');
  chartNibpInstance = new Chart(ctx2, {
    type: 'line',
    data: {
      labels: labels,
      datasets: [
        {
          label: 'Pressione Sistolica SBP (mmHg)',
          data: data.map(d => d.Solar8000_NIBP_SBP ?? null),
          borderColor: isDark ? '#f59e0b' : '#d97706',
          backgroundColor: isDark ? 'rgba(245, 158, 11, 0.08)' : 'rgba(217, 119, 6, 0.06)',
          borderWidth: 2, tension: 0.2, pointRadius: 0, fill: true
        },
        {
          label: 'Pressione Diastolica DBP (mmHg)',
          data: data.map(d => d.Solar8000_NIBP_DBP ?? null),
          borderColor: isDark ? '#10b981' : '#059669',
          borderWidth: 2, tension: 0.2, pointRadius: 0
        },
        {
          label: 'Pressione Media MBP (mmHg)',
          data: data.map(d => d.Solar8000_NIBP_MBP ?? null),
          borderColor: isDark ? '#a855f7' : '#7c3aed',
          borderWidth: 2, tension: 0.2, pointRadius: 0, borderDash: [4, 4]
        },
        {
          label: '🔴 Anomalie Pressione',
          data: sbpAnomalyOverlay,
          borderColor: isDark ? '#f43f5e' : '#dc2626',
          backgroundColor: isDark ? '#f43f5e' : '#dc2626',
          pointRadius: 6,
          pointHoverRadius: 9,
          showLine: false
        }
      ]
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      plugins: { legend: { labels: { color: textColor, font: { family: 'Inter', weight: '600', size: 11 } } } },
      scales: {
        x: { ticks: { color: textColor, maxTicksLimit: 10, font: { family: 'Inter', size: 10 } }, grid: { color: gridColor } },
        y: { ticks: { color: textColor, font: { family: 'JetBrains Mono', size: 10 } }, grid: { color: gridColor } }
      }
    }
  });
}
