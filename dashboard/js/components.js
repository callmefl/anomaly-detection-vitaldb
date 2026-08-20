/**
 * Modulo di rendering dei componenti dell'interfaccia utente (UI Components)
 */

let currentFilteredAnomalies = [];

/**
 * Renderizza la lista dei casi nella sidebar con il reparto chirurgico
 */
function renderCases(cases, currentCaseId) {
  const container = document.getElementById('caseList');
  if (cases.length === 0) {
    container.innerHTML = '<div style="text-align:center; color:var(--text-dim); padding:1rem;">Nessun caso trovato.</div>';
    return;
  }

  container.innerHTML = cases.map(c => `
    <div class="case-card ${c.case_id === currentCaseId ? 'active' : ''}" onclick="selectCase(${c.case_id}, ${c.record_count})">
      <div>
        <div class="case-card-title">Caso Clinico #${c.case_id}</div>
        <div class="case-card-sub">${c.department || 'Chirurgia Generale'} · ${(c.record_count || 0).toLocaleString()} p.ti</div>
      </div>
      <div class="case-badge">Gold</div>
    </div>
  `).join('');
}

/**
 * Popola il menù a tendina dropdown
 */
function renderCaseMenu(cases) {
  const menu = document.getElementById('caseSelectMenu');
  menu.innerHTML = '<option value="">-- Scegli Caso dal Menù --</option>' +
    cases.map(c => `<option value="${c.case_id}">Caso #${c.case_id} (${c.department || 'Chirurgia'}) — ${(c.record_count || 0).toLocaleString()} p.ti</option>`).join('');
}

/**
 * Aggiorna i valori nei cartelli KPI ed i metadati del paziente
 */
function updateKPIs(data) {
  if (!data || data.length === 0) return;

  const validHR = data.map(d => d.Solar8000_HR).filter(v => v !== null && v !== undefined);
  const validSpO2 = data.map(d => d.Solar8000_PLETH_SPO2).filter(v => v !== null && v !== undefined);

  const avgHR = validHR.length ? (validHR.reduce((a, b) => a + b, 0) / validHR.length).toFixed(1) : '—';
  const avgSpO2 = validSpO2.length ? (validSpO2.reduce((a, b) => a + b, 0) / validSpO2.length).toFixed(1) : '—';

  document.getElementById('kpiAvgHR').textContent = `${avgHR} bpm`;
  document.getElementById('kpiAvgSpO2').textContent = `${avgSpO2} %`;
}

/**
 * Renderizza la tabella delle anomalie con supporto ai filtri ed al numero personalizzabile di righe visibili
 */
function renderAnomalyTable(anomalies, filterMethod = 'all', limitSize = 'all') {
  const section = document.getElementById('anomalySection');
  const tbody = document.getElementById('anomalyTableBody');

  if (!anomalies || anomalies.length === 0) {
    section.classList.add('hidden');
    return;
  }

  let filtered = anomalies;
  if (filterMethod === 'high_severity') {
    filtered = anomalies.filter(a => a.methods.length >= 3);
  } else if (filterMethod !== 'all') {
    filtered = anomalies.filter(a => a.methods.includes(filterMethod));
  }

  currentFilteredAnomalies = filtered;

  let displayRows = filtered;
  if (limitSize !== 'all') {
    const maxRows = parseInt(limitSize, 10);
    displayRows = filtered.slice(0, maxRows);
  }

  document.getElementById('anomalyTableSubtitle').textContent = 
    `Mostrando ${displayRows.length} eventi anomali su ${filtered.length} filtrati (${anomalies.length} totali nel caso) — Clicca su una riga per la spiegazione medica`;

  tbody.innerHTML = displayRows.map((item, idx) => {
    const methodCount = item.methods.length;
    let severityBadge = '';
    if (methodCount >= 3) {
      severityBadge = '<span class="badge-severity sev-high">Alta Confidenza (3+ Metodi)</span>';
    } else if (methodCount === 2) {
      severityBadge = '<span class="badge-severity sev-med">Media Confidenza (2 Metodi)</span>';
    } else {
      severityBadge = '<span class="badge-severity sev-low">Moderata (1 Metodo)</span>';
    }

    const tags = item.methods.map(m => {
      if (m === 'shock_index') return '<span class="tag-method tag-shock">Shock Index</span>';
      if (m === 'severe_hypotension') return '<span class="tag-method tag-hyp">Ipotensione Severa</span>';
      if (m === 'isolation_forest') return '<span class="tag-method tag-iso">Isolation Forest</span>';
      if (m === 'autoencoder') return '<span class="tag-method tag-ae">Autoencoder</span>';
      return `<span class="tag-method">${m}</span>`;
    }).join('');

    const hrStr = item.hr !== null ? `${item.hr} bpm` : '—';
    const spo2Str = item.spo2 !== null ? `${item.spo2} %` : '—';
    
    let nibpStr = '—';
    if (item.sbp !== null && item.dbp !== null && item.mbp !== null) {
      nibpStr = `${item.sbp}/${item.dbp} (${item.mbp})`;
    }

    const siClass = (item.shock_index !== null && item.shock_index > 0.9) ? 'val-critical' : '';
    const siStr = item.shock_index !== null ? `<span class="${siClass}">${item.shock_index}</span>` : '—';

    return `
      <tr onclick="openRowExplanationModal(${idx})">
        <td style="color: var(--text-dim);">${idx + 1}</td>
        <td>${item.timestamp}</td>
        <td>${severityBadge}</td>
        <td>${hrStr}</td>
        <td>${spo2Str}</td>
        <td>${nibpStr}</td>
        <td>${siStr}</td>
        <td>${tags}</td>
      </tr>
    `;
  }).join('');

  section.classList.remove('hidden');
}

/**
 * Apre la modale di spiegazione medica per uno specifico metodo di Anomaly Detection
 */
function openMethodExplanationModal(methodKey) {
  const modal = document.getElementById('explanationModal');
  const title = document.getElementById('modalTitle');
  const body = document.getElementById('modalBody');

  const explanations = {
    shock_index: {
      title: "Spiegazione Clinica: Shock Index (SI)",
      formula: "Shock Index (SI) = Frequenza Cardiaca (HR) / Pressione Sistolica (SBP) > 0.9",
      desc: "Lo Shock Index è un indicatore clinico essenziale nella medicina d'urgenza e nella cardioanestesia. Misura il rapporto tra la frequenza cardiaca ed la pressione sistolica.",
      meaning: "Un valore superiore a 0.9 indica un compenso emodinamico insufficiente ed un rischio imminente di shock ipovolemico o cardiogeno, prima che la sola pressione scenda sotto i limiti clinici normali.",
      action: "Monitoraggio invasivo della portata cardiaca, controllo dell'assestamento dei volumi ematici (fluidoterapia), somministrazione di inotropi/vasopressori."
    },
    severe_hypotension: {
      title: "Spiegazione Clinica: Ipotensione Severa",
      formula: "Pressione Media (MBP) < 65 mmHg  E  Saturazione (SpO2) < 90%",
      desc: "Questa regola combinata identifica la sofferenza perfusiva e tissutale globale durante l'anestesia generale o gli interventi di chirurgia complessa.",
      meaning: "La combinazione di ipotensione arteriosa media e desaturazione periferica compromette la perfusione d'organo (reni, cervello, miocardio), aumentando il rischio di insufficienza multiorgano intraoperatoria.",
      action: "Regolazione immediata della frazione inspirata d'ossigeno (FiO2), riduzione dei dosaggi di anestetico volatile, somministrazione rapida di vasopressori (es. Efedrina o Noradrenalina)."
    },
    isolation_forest: {
      title: "Spiegazione Algoritmica: Isolation Forest (Machine Learning)",
      formula: "Score di Isolamento Spaziale nello Spazio Vettoriale 5D (HR, SpO2, SBP, DBP, MBP)",
      desc: "L'Isolation Forest è un algoritmo di Machine Learning non supervisionato che isola le osservazioni costruendo in modo casuale alberi di decisione.",
      meaning: "Rileva anomalie multivariate complesse (es. una combinazione di battito accelerato e pressione diastolica insolitamente bassa) che non supererebbero mai i limiti fisse univariati tradizionali ma rappresentano stati fisiologici rari e sospetti.",
      action: "Valutazione complessiva del trend temporale e confronto con le tendenze storiche del paziente."
    },
    autoencoder: {
      title: "Spiegazione Algoritmica: Autoencoder Neurale (Deep Learning)",
      formula: "Reconstruction Error MSE = Mean((X_input - X_reconstructed)^2) > 95° Percentile",
      desc: "L'Autoencoder Neurale (MLPRegressor) impara la rappresentazione compressa del segnale biometrico fisiologico normale del paziente durante la fase pre-operatoria.",
      meaning: "Quando il segnale biometrico devia dal pattern fisiologico appreso, la rete neurale non riesce a ricostruire l'input in modo accurato, generando una 'coda lunga' nell'errore quadratico medio (MSE).",
      action: "Analisi della forma d'onda del segnale sensoristico per escludere artefatti da movimento o verificare l'insorgenza di aritmie/instabilità."
    }
  };

  const exp = explanations[methodKey];
  if (!exp) return;

  title.textContent = exp.title;
  body.innerHTML = `
    <div style="color: var(--text-muted); font-size: 0.85rem;">${exp.desc}</div>
    
    <div>
      <strong style="font-size:0.75rem; text-transform:uppercase; color:var(--text-dim);">Formula / Logica Matematica:</strong>
      <div class="formula-box">${exp.formula}</div>
    </div>

    <div>
      <strong style="font-size:0.75rem; text-transform:uppercase; color:var(--text-dim);">Significato Fisiopatologico:</strong>
      <div style="margin-top:0.25rem;">${exp.meaning}</div>
    </div>

    <div class="clinical-action-box">
      <strong>Azione Clinica Consigliata:</strong><br>
      ${exp.action}
    </div>
  `;

  modal.classList.remove('hidden');
}

/**
 * Apre la modale di spiegazione al click su una riga della tabella anomalie
 */
function openRowExplanationModal(idx) {
  const item = currentFilteredAnomalies[idx];
  if (!item) return;

  const modal = document.getElementById('explanationModal');
  const title = document.getElementById('modalTitle');
  const body = document.getElementById('modalBody');

  title.textContent = `Analisi Evento Anomalo — Timestamp: ${item.timestamp}`;

  const tags = item.methods.map(m => {
    if (m === 'shock_index') return '<span class="tag-method tag-shock">Shock Index</span>';
    if (m === 'severe_hypotension') return '<span class="tag-method tag-hyp">Ipotensione Severa</span>';
    if (m === 'isolation_forest') return '<span class="tag-method tag-iso">Isolation Forest</span>';
    if (m === 'autoencoder') return '<span class="tag-method tag-ae">Autoencoder</span>';
    return `<span class="tag-method">${m}</span>`;
  }).join(' ');

  body.innerHTML = `
    <div style="display:flex; justify-content:space-between; align-items:center; background:var(--bg-main); padding:0.75rem; border-radius:8px; border:1px solid var(--border-color);">
      <div><strong>Frequenza Cardiaca:</strong> ${item.hr !== null ? item.hr + ' bpm' : '—'}</div>
      <div><strong>Saturazione SpO₂:</strong> ${item.spo2 !== null ? item.spo2 + ' %' : '—'}</div>
      <div><strong>Pressione SBP/DBP:</strong> ${item.sbp !== null ? item.sbp + '/' + item.dbp + ' mmHg' : '—'}</div>
    </div>

    <div>
      <strong style="font-size:0.75rem; text-transform:uppercase; color:var(--text-dim);">Metodi di Rilevazione Attivati per Questo Secondo:</strong>
      <div style="margin-top:0.4rem;">${tags}</div>
    </div>

    <div>
      <strong style="font-size:0.75rem; text-transform:uppercase; color:var(--text-dim);">Diagnosi Automatica:</strong>
      <div style="margin-top:0.25rem;">
        ${item.methods.includes('shock_index') ? '⚠️ <strong>Shock Index Elevato (> 0.9):</strong> Il rapporto tra frequenza cardiaca e pressione sistolica evidenzia uno sforzo emodinamico del miocardio.<br>' : ''}
        ${item.methods.includes('severe_hypotension') ? '🚨 <strong>Ipotensione Severa & Desaturazione:</strong> Rischio di ipossia tissutale d\'organo.<br>' : ''}
        ${item.methods.includes('isolation_forest') || item.methods.includes('autoencoder') ? '🔍 <strong>Anomalia Multivariata ML:</strong> Il profilo fisiologico in questo istante temporale si discosta significativamente dalla distribuzione di normalità del paziente.' : ''}
      </div>
    </div>
  `;

  modal.classList.remove('hidden');
}

/**
 * Chiude la modale attiva
 */
function closeModal() {
  document.getElementById('explanationModal').classList.add('hidden');
}

/**
 * Esporta le anomalie correnti in un file CSV scaricabile
 */
function exportAnomaliesCSV() {
  if (!currentFilteredAnomalies || currentFilteredAnomalies.length === 0) {
    alert("Nessun dato anomalo da esportare.");
    return;
  }

  const headers = ["Timestamp", "HR_bpm", "SpO2_pct", "SBP_mmHg", "DBP_mmHg", "MBP_mmHg", "ShockIndex", "Metodi"];
  const csvRows = [headers.join(",")];

  for (const item of currentFilteredAnomalies) {
    const row = [
      `"${item.timestamp}"`,
      item.hr ?? "",
      item.spo2 ?? "",
      item.sbp ?? "",
      item.dbp ?? "",
      item.mbp ?? "",
      item.shock_index ?? "",
      `"${item.methods.join(";")}"`
    ];
    csvRows.push(row.join(","));
  }

  const blob = new Blob([csvRows.join("\n")], { type: "text/csv;charset=utf-8;" });
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.setAttribute("href", url);
  link.setAttribute("download", `anomalie_caso_${currentCaseId || 'export'}.csv`);
  document.body.appendChild(link);
  link.click();
  document.body.removeChild(link);
}
