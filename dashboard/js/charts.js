/**
 * VITALDB CLINICAL TELEMETRY - CHART.JS CONTROLLER
 * High-performance synchronized dual waveform displays with physiological reference bands
 * Styled for the Nickelfox Healthcare Dashboard aesthetic (Gradient fills, bright colors).
 */

let chartHrSpo2 = null;
let chartNibp = null;

// Plugin Chart.js per mirino verticale sincronizzato (Synchronized Crosshair)
const synchronizedCrosshairPlugin = {
  id: 'synchronizedCrosshair',
  afterDatasetsDraw(chart) {
    if (chart.tooltip && chart.tooltip._active && chart.tooltip._active.length) {
      const activePoint = chart.tooltip._active[0];
      const ctx = chart.ctx;
      const x = activePoint.element.x;
      const topY = chart.scales.y.top;
      const bottomY = chart.scales.y.bottom;

      ctx.save();
      ctx.beginPath();
      ctx.setLineDash([4, 4]);
      ctx.moveTo(x, topY);
      ctx.lineTo(x, bottomY);
      ctx.lineWidth = 1;
      ctx.strokeStyle = chart.options.plugins.crosshairColor || 'rgba(148, 163, 184, 0.4)';
      ctx.stroke();
      ctx.restore();
    }
  }
};

Chart.register(synchronizedCrosshairPlugin);

/**
 * Creates a vertical linear gradient for area charts
 */
function createGradient(ctx, chartArea, colorStart, colorEnd) {
  if (!chartArea) return colorStart; // Fallback
  const gradient = ctx.createLinearGradient(0, chartArea.top, 0, chartArea.bottom);
  gradient.addColorStop(0, colorStart);
  gradient.addColorStop(1, colorEnd);
  return gradient;
}

/**
 * Renderizza o aggiorna i due grafici temporali
 * @param {Array} data - Serie temporale dei parametri biometrici
 * @param {Object|null} anomalyResult - Risultato dell'anomaly detection
 * @param {string|null} highlightMethod - Metodo specifico da evidenziare
 */
function renderCharts(data, anomalyResult = null, highlightMethod = null) {
  if (!data || data.length === 0) return;

  const isDark = (document.documentElement.getAttribute('data-theme') || 'dark') === 'dark';
  
  // Nickelfox Healthcare Palette mapping
  const textColor = isDark ? '#94A3B8' : '#64748B';
  const gridColor = isDark ? 'rgba(255, 255, 255, 0.05)' : 'rgba(15, 23, 42, 0.04)';
  const crosshairColor = isDark ? 'rgba(34, 211, 238, 0.35)' : 'rgba(15, 173, 190, 0.35)';
  const fontBody = "'Space Grotesk', sans-serif";
  const fontMono = "'JetBrains Mono', monospace";

  const labels = data.map(d => d.timestamp);

  // Mappa delle anomalie per rapido lookup
  const anomalyMap = new Map();
  if (anomalyResult && anomalyResult.anomalies) {
    for (const anom of anomalyResult.anomalies) {
      if (!highlightMethod || anom.methods.includes(highlightMethod)) {
        anomalyMap.set(anom.timestamp, anom);
      }
    }
  }

  // Punti sovrapposti per anomalie
  const hrAnomalyPoints = data.map(d => anomalyMap.has(d.timestamp) ? (d.Solar8000_HR ?? null) : null);
  const sbpAnomalyPoints = data.map(d => anomalyMap.has(d.timestamp) ? (d.Solar8000_NIBP_SBP ?? null) : null);

  if (chartHrSpo2) chartHrSpo2.destroy();
  if (chartNibp) chartNibp.destroy();

  // 1. GRAFICO 1: Frequenza Cardiaca (HR) & Saturazione Ossigeno (SpO2)
  const canvas1 = document.getElementById('chartHrSpo2');
  if (canvas1) {
    const ctx1 = canvas1.getContext('2d');
    chartHrSpo2 = new Chart(ctx1, {
      type: 'line',
      data: {
        labels: labels,
        datasets: [
          {
            label: 'Frequenza Cardiaca (HR)',
            data: data.map(d => d.Solar8000_HR ?? null),
            borderColor: isDark ? '#F87171' : '#EF4444', // Red
            backgroundColor: (context) => {
              const chart = context.chart;
              const {ctx, chartArea} = chart;
              if (!chartArea) return null;
              return createGradient(ctx, chartArea, 
                isDark ? 'rgba(248, 113, 113, 0.2)' : 'rgba(239, 68, 68, 0.15)',
                isDark ? 'rgba(248, 113, 113, 0)' : 'rgba(239, 68, 68, 0)'
              );
            },
            borderWidth: 2,
            tension: 0.4, // Smoother curve for Nickelfox style
            pointRadius: 0,
            pointHoverRadius: 4,
            fill: true,
            yAxisID: 'y'
          },
          {
            label: 'Saturazione Ossigeno (SpO₂)',
            data: data.map(d => d.Solar8000_PLETH_SPO2 ?? null),
            borderColor: isDark ? '#22D3EE' : '#0FADBE', // Teal
            backgroundColor: 'transparent',
            borderWidth: 2,
            tension: 0.4,
            pointRadius: 0,
            pointHoverRadius: 4,
            yAxisID: 'y1'
          },
          {
            label: 'Allarme Anomalia',
            data: hrAnomalyPoints,
            borderColor: isDark ? '#FBBF24' : '#F59E0B',
            backgroundColor: isDark ? '#FBBF24' : '#F59E0B',
            pointRadius: (ctx) => {
              const val = ctx.raw;
              return val !== null ? 5 : 0;
            },
            pointHoverRadius: 8,
            showLine: false,
            yAxisID: 'y'
          }
        ]
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        animation: { duration: 500, easing: 'easeOutQuart' },
        interaction: { mode: 'index', intersect: false },
        plugins: {
          crosshairColor: crosshairColor,
          legend: { display: false },
          tooltip: {
            backgroundColor: isDark ? 'rgba(15, 23, 42, 0.95)' : 'rgba(255, 255, 255, 0.95)',
            titleColor: isDark ? '#F8FAFC' : '#1E293B',
            bodyColor: isDark ? '#CBD5E1' : '#64748B',
            borderColor: isDark ? 'rgba(255, 255, 255, 0.1)' : 'rgba(0, 0, 0, 0.05)',
            borderWidth: 1,
            padding: 12,
            boxPadding: 6,
            titleFont: { family: fontMono, size: 11, weight: '600' },
            bodyFont: { family: fontBody, size: 12 },
            callbacks: {
              afterBody: (context) => {
                const ts = context[0].label;
                const anom = anomalyMap.get(ts);
                if (anom) {
                  return `\n[!] ANOMALIA RILEVATA:\n- Metodi: ${anom.methods.join(', ')}\n${anom.shock_index ? `- Shock Index: ${anom.shock_index}` : ''}`;
                }
                return '';
              }
            }
          }
        },
        scales: {
          x: {
            ticks: { color: textColor, maxTicksLimit: 8, font: { family: fontMono, size: 10 } },
            grid: { color: gridColor, drawBorder: false }
          },
          y: {
            position: 'left',
            min: 40,
            max: 160,
            title: { display: true, text: 'HR (bpm)', color: isDark ? '#F87171' : '#EF4444', font: { family: fontMono, size: 10, weight: '600' } },
            ticks: { color: textColor, font: { family: fontMono, size: 10 } },
            grid: { color: gridColor, drawBorder: false }
          },
          y1: {
            position: 'right',
            min: 80,
            max: 100,
            title: { display: true, text: 'SpO₂ (%)', color: isDark ? '#22D3EE' : '#0FADBE', font: { family: fontMono, size: 10, weight: '600' } },
            ticks: { color: textColor, font: { family: fontMono, size: 10 } },
            grid: { drawOnChartArea: false, drawBorder: false }
          }
        }
      }
    });
  }

  // 2. GRAFICO 2: Pressione Arteriosa (NIBP: SBP, DBP, MBP)
  const canvas2 = document.getElementById('chartNibp');
  if (canvas2) {
    const ctx2 = canvas2.getContext('2d');
    chartNibp = new Chart(ctx2, {
      type: 'line',
      data: {
        labels: labels,
        datasets: [
          {
            label: 'Pressione Sistolica (SBP)',
            data: data.map(d => d.Solar8000_NIBP_SBP ?? null),
            borderColor: isDark ? '#FBBF24' : '#F59E0B', // Orange
            backgroundColor: (context) => {
              const chart = context.chart;
              const {ctx, chartArea} = chart;
              if (!chartArea) return null;
              return createGradient(ctx, chartArea, 
                isDark ? 'rgba(251, 191, 36, 0.2)' : 'rgba(245, 158, 11, 0.15)',
                isDark ? 'rgba(251, 191, 36, 0)' : 'rgba(245, 158, 11, 0)'
              );
            },
            borderWidth: 2,
            tension: 0.4,
            pointRadius: 0,
            fill: true
          },
          {
            label: 'Pressione Diastolica (DBP)',
            data: data.map(d => d.Solar8000_NIBP_DBP ?? null),
            borderColor: isDark ? '#34D399' : '#10B981', // Green
            backgroundColor: 'transparent',
            borderWidth: 2,
            tension: 0.4,
            pointRadius: 0
          },
          {
            label: 'Pressione Media (MBP)',
            data: data.map(d => d.Solar8000_NIBP_MBP ?? null),
            borderColor: isDark ? '#A78BFA' : '#8B5CF6', // Purple
            backgroundColor: 'transparent',
            borderWidth: 2,
            tension: 0.4,
            pointRadius: 0,
            borderDash: [5, 5]
          },
          {
            label: 'Allarme Anomalia Pressoria',
            data: sbpAnomalyPoints,
            borderColor: isDark ? '#F87171' : '#EF4444',
            backgroundColor: isDark ? '#F87171' : '#EF4444',
            pointRadius: (ctx) => {
              const val = ctx.raw;
              return val !== null ? 5 : 0;
            },
            pointHoverRadius: 8,
            showLine: false
          }
        ]
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        animation: { duration: 500, easing: 'easeOutQuart' },
        interaction: { mode: 'index', intersect: false },
        plugins: {
          crosshairColor: crosshairColor,
          legend: { display: false },
          tooltip: {
            backgroundColor: isDark ? 'rgba(15, 23, 42, 0.95)' : 'rgba(255, 255, 255, 0.95)',
            titleColor: isDark ? '#F8FAFC' : '#1E293B',
            bodyColor: isDark ? '#CBD5E1' : '#64748B',
            borderColor: isDark ? 'rgba(255, 255, 255, 0.1)' : 'rgba(0, 0, 0, 0.05)',
            borderWidth: 1,
            padding: 12,
            titleFont: { family: fontMono, size: 11, weight: '600' },
            bodyFont: { family: fontBody, size: 12 }
          }
        },
        scales: {
          x: {
            ticks: { color: textColor, maxTicksLimit: 8, font: { family: fontMono, size: 10 } },
            grid: { color: gridColor, drawBorder: false }
          },
          y: {
            min: 20,
            max: 220,
            title: { display: true, text: 'Pressione (mmHg)', color: textColor, font: { family: fontMono, size: 10 } },
            ticks: { color: textColor, font: { family: fontMono, size: 10 } },
            grid: { color: gridColor, drawBorder: false }
          }
        }
      }
    });
  }
}
