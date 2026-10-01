/**
 * VITALDB CLINICAL TELEMETRY - UI PRESENTATION COMPONENTS
 * Clean architecture renderers for Cases, HUD Vitals, Consensus Bar, Tables and Modals
 */

const components = {
  /**
   * Renderizza la lista dei casi nella sidebar rail
   */
  renderCaseList(cases, currentCaseId) {
    const container = document.getElementById('caseScrollList');
    if (!container) return;

    if (!cases || cases.length === 0) {
      container.innerHTML = `
        <div style="text-align: center; color: var(--text-tertiary); padding: 2rem 1rem; font-size: 0.8rem;">
          Nessun caso trovato per i filtri selezionati.
        </div>`;
      return;
    }

    container.innerHTML = cases.map(c => {
      const isActive = c.case_id === currentCaseId;
      const dept = c.department || 'Chirurgia Generale';
      const pts = (c.record_count || 0).toLocaleString();

      return `
        <div class="case-item-card ${isActive ? 'active' : ''}" onclick="app.selectCase(${c.case_id})">
          <div class="case-item-info">
            <div class="case-item-title">
              <span>Caso Clinico #${c.case_id}</span>
            </div>
            <div class="case-item-meta">
              <span>${dept}</span>
              <span>•</span>
              <span class="num-mono">${pts} p.ti</span>
            </div>
          </div>
        </div>
      `;
    }).join('');
  },

  /**
   * Renderizza i pulsanti a pillola per i reparti chirurgici (Data Governance)
   */
  renderDeptPills(cases, currentDept) {
    const track = document.getElementById('deptPillTrack');
    if (!track) return;

    const depts = Array.from(new Set(cases.map(c => c.department).filter(Boolean))).sort();
    
    let html = `
      <button class="dept-pill ${!currentDept ? 'active' : ''}" onclick="app.setDeptFilter('')">
        Tutti i Reparti (${cases.length})
      </button>
    `;

    for (const d of depts) {
      const count = cases.filter(c => c.department === d).length;
      html += `
        <button class="dept-pill ${currentDept === d ? 'active' : ''}" onclick="app.setDeptFilter('${d}')">
          ${d} (${count})
        </button>
      `;
    }

    track.innerHTML = html;
  },

  /**
   * Aggiorna l'HUD del paziente in cima alla dashboard
   */
  renderPatientHUD(caseObj, pointCount) {
    const title = document.getElementById('hudPatientTitle');
    const dept = document.getElementById('hudPatientDept');
    const ageSex = document.getElementById('hudPatientAgeSex');
    const points = document.getElementById('hudPatientPoints');

    if (title) title.textContent = `Paziente Intraoperatorio #${caseObj.case_id}`;
    if (dept) dept.textContent = caseObj.department || 'Chirurgia Generale';
    if (ageSex) {
      const ageStr = caseObj.age ? `${caseObj.age} anni` : 'Età N/D';
      const sexStr = caseObj.sex ? (caseObj.sex === 'M' ? 'Maschio' : 'Femmina') : 'Sesso N/D';
      ageSex.textContent = `${ageStr} • ${sexStr}`;
    }
    if (points) points.textContent = `${(pointCount || 0).toLocaleString()} campioni Gold`;
  },

  /**
   * Renderizza i 5 cartellini Bento Vitals con indicatori clinici
   */
  renderBentoVitals(seriesData, anomalyResult) {
    if (!seriesData || seriesData.length === 0) return;

    const validHR = seriesData.map(d => d.Solar8000_HR).filter(v => v !== null && v !== undefined);
    const validSpO2 = seriesData.map(d => d.Solar8000_PLETH_SPO2).filter(v => v !== null && v !== undefined);
    const validSBP = seriesData.map(d => d.Solar8000_NIBP_SBP).filter(v => v !== null && v !== undefined);
    const validDBP = seriesData.map(d => d.Solar8000_NIBP_DBP).filter(v => v !== null && v !== undefined);
    const validMBP = seriesData.map(d => d.Solar8000_NIBP_MBP).filter(v => v !== null && v !== undefined);

    const avgHR = validHR.length ? (validHR.reduce((a, b) => a + b, 0) / validHR.length).toFixed(0) : '—';
    const minHR = validHR.length ? Math.min(...validHR).toFixed(0) : '—';
    const maxHR = validHR.length ? Math.max(...validHR).toFixed(0) : '—';

    const avgSpO2 = validSpO2.length ? (validSpO2.reduce((a, b) => a + b, 0) / validSpO2.length).toFixed(1) : '—';
    const minSpO2 = validSpO2.length ? Math.min(...validSpO2).toFixed(0) : '—';

    const avgSBP = validSBP.length ? (validSBP.reduce((a, b) => a + b, 0) / validSBP.length).toFixed(0) : '—';
    const avgDBP = validDBP.length ? (validDBP.reduce((a, b) => a + b, 0) / validDBP.length).toFixed(0) : '—';
    const avgMBP = validMBP.length ? (validMBP.reduce((a, b) => a + b, 0) / validMBP.length).toFixed(0) : '—';

    // Calcolo Shock Index medio
    let avgSI = '—';
    let siStatusText = 'In attesa calcolo';
    let siStatusClass = '';
    if (avgHR !== '—' && avgSBP !== '—' && parseFloat(avgSBP) > 0) {
      const siVal = parseFloat(avgHR) / parseFloat(avgSBP);
      avgSI = siVal.toFixed(2);
      if (siVal > 0.9) {
        siStatusText = 'Allarme Shock (> 0.9)';
        siStatusClass = 'style="color: var(--telemetry-shock);"';
      } else if (siVal >= 0.7) {
        siStatusText = 'Borderline (0.7 – 0.9)';
        siStatusClass = 'style="color: var(--telemetry-amber);"';
      } else {
        siStatusText = 'Stabilità Emodinamica (< 0.7)';
        siStatusClass = 'style="color: var(--telemetry-emerald);"';
      }
    }

    // Totale anomalie uniche
    const uniqueAnomalies = anomalyResult ? anomalyResult.anomaly_count : 0;
    const hasDetected = anomalyResult !== null;

    // Popolamento elementi DOM
    const elHR = document.getElementById('vitalHR');
    const elHRRange = document.getElementById('vitalHRRange');
    const elSpO2 = document.getElementById('vitalSpO2');
    const elSpO2Min = document.getElementById('vitalSpO2Min');
    const elNIBP = document.getElementById('vitalNIBP');
    const elMBP = document.getElementById('vitalMBP');
    const elSI = document.getElementById('vitalShockIndex');
    const elSIStatus = document.getElementById('vitalSIStatus');
    const elAnom = document.getElementById('vitalAnomaliesCount');
    const elAnomStatus = document.getElementById('vitalAnomaliesStatus');

    if (elHR) elHR.textContent = avgHR;
    if (elHRRange) elHRRange.textContent = `Min ${minHR} • Max ${maxHR} bpm`;

    if (elSpO2) elSpO2.textContent = avgSpO2;
    if (elSpO2Min) elSpO2Min.textContent = `Nadir: ${minSpO2}% (Target > 95%)`;

    if (elNIBP) elNIBP.textContent = `${avgSBP}/${avgDBP}`;
    if (elMBP) elMBP.textContent = `MAP Media: ${avgMBP} mmHg`;

    if (elSI) elSI.textContent = avgSI;
    if (elSIStatus) {
      elSIStatus.innerHTML = `<span ${siStatusClass}>${siStatusText}</span>`;
    }

    if (elAnom) elAnom.textContent = hasDetected ? uniqueAnomalies.toLocaleString() : '—';
    if (elAnomStatus) {
      if (hasDetected) {
        elAnomStatus.textContent = `${uniqueAnomalies} istanti temporali critici`;
      } else {
        elAnomStatus.textContent = 'Premi "Rileva Anomalie"';
      }
    }
  },

  /**
   * Renderizza la barra di consensus con i 4 algoritmi
   */
  renderConsensusBar(anomalyResult, activeHighlight) {
    const summary = anomalyResult ? (anomalyResult.summary_by_method || {}) : {};

    const cntSI = summary.shock_index || 0;
    const cntHyp = summary.severe_hypotension || 0;
    const cntIso = summary.isolation_forest || 0;
    const cntAe = summary.autoencoder || 0;

    const elSI = document.getElementById('countShockIndex');
    const elHyp = document.getElementById('countSevereHyp');
    const elIso = document.getElementById('countIsoForest');
    const elAe = document.getElementById('countAutoencoder');

    if (elSI) elSI.textContent = cntSI.toLocaleString();
    if (elHyp) elHyp.textContent = cntHyp.toLocaleString();
    if (elIso) elIso.textContent = cntIso.toLocaleString();
    if (elAe) elAe.textContent = cntAe.toLocaleString();

    // Gestione stato chip attivo
    document.querySelectorAll('.algo-chip').forEach(chip => {
      const method = chip.getAttribute('data-method');
      if (activeHighlight && activeHighlight === method) {
        chip.classList.add('active-highlight');
      } else {
        chip.classList.remove('active-highlight');
      }
    });
  },

  /**
   * Renderizza la tabella ad alta densità per l'ispezione dei punti critici
   */
  renderAnomalyTable(anomalies, filterMethod = 'all', limitSize = 'all') {
    const container = document.getElementById('anomalyTableWrapper');
    const tbody = document.getElementById('anomalyTableBody');
    const subtitle = document.getElementById('anomalyTableSubtitle');

    if (!tbody || !anomalies) return;

    if (anomalies.length === 0) {
      if (container) container.classList.add('hidden');
      return;
    }

    if (container) container.classList.remove('hidden');

    let filtered = anomalies;
    if (filterMethod === 'high_severity') {
      filtered = anomalies.filter(a => a.methods.length >= 3);
    } else if (filterMethod !== 'all') {
      filtered = anomalies.filter(a => a.methods.includes(filterMethod));
    }

    let displayRows = filtered;
    if (limitSize !== 'all') {
      const maxRows = parseInt(limitSize, 10);
      displayRows = filtered.slice(0, maxRows);
    }

    if (subtitle) {
      subtitle.textContent = `Visualizzazione di ${displayRows.length} eventi su ${filtered.length} filtrati (${anomalies.length} totali nel caso)`;
    }

    tbody.innerHTML = displayRows.map((item, idx) => {
      const methodCount = item.methods.length;
      let severityBadge = '';
      if (methodCount >= 3) {
        severityBadge = '<span class="severity-pill sev-high">Critica (3+ Algoritmi)</span>';
      } else if (methodCount === 2) {
        severityBadge = '<span class="severity-pill sev-med">Moderata (2 Algoritmi)</span>';
      } else {
        severityBadge = '<span class="severity-pill sev-low">Advisory (1 Algoritmo)</span>';
      }

      const tags = item.methods.map(m => {
        if (m === 'shock_index') return '<span class="m-tag m-tag-shock">Shock Index</span>';
        if (m === 'severe_hypotension') return '<span class="m-tag m-tag-hyp">Ipotensione</span>';
        if (m === 'isolation_forest') return '<span class="m-tag m-tag-iso">IsoForest</span>';
        if (m === 'autoencoder') return '<span class="m-tag m-tag-ae">Autoencoder</span>';
        return `<span class="m-tag">${m}</span>`;
      }).join(' ');

      const hrVal = item.hr !== null ? `<span class="num-mono cell-primary">${item.hr.toFixed(0)}</span>` : '—';
      const spo2Val = item.spo2 !== null ? `<span class="num-mono" style="color:var(--telemetry-cyan); font-weight:600;">${item.spo2.toFixed(0)}%</span>` : '—';
      const nibpVal = (item.sbp !== null && item.dbp !== null) 
        ? `<span class="num-mono">${item.sbp.toFixed(0)} / ${item.dbp.toFixed(0)}</span>` 
        : '—';
      const siVal = item.shock_index !== null 
        ? `<span class="num-mono" style="color:${item.shock_index > 0.9 ? 'var(--telemetry-shock)' : 'var(--text-primary)'}; font-weight:700;">${item.shock_index.toFixed(2)}</span>` 
        : '—';

      return `
        <tr onclick="app.inspectAnomalyTimestamp('${item.timestamp}')">
          <td class="num-mono" style="color:var(--text-tertiary);">${idx + 1}</td>
          <td class="num-mono cell-primary">${item.timestamp}</td>
          <td>${severityBadge}</td>
          <td>${hrVal}</td>
          <td>${spo2Val}</td>
          <td>${nibpVal}</td>
          <td>${siVal}</td>
          <td><div class="method-tags-cell">${tags}</div></td>
        </tr>
      `;
    }).join('');
  },

  /**
   * Spiegazione clinica e matematica dei 4 metodi di Anomaly Detection
   */
  openModalExplanation(methodKey) {
    const modal = document.getElementById('explanationModal');
    const title = document.getElementById('modalTitle');
    const body = document.getElementById('modalBody');

    if (!modal || !title || !body) return;

    const data = {
      shock_index: {
        title: "Shock Index Clinico (SI)",
        formula: "SI = Frequenza Cardiaca (HR) / Pressione Sistolica (SBP) > 0.9",
        rationale: "Lo Shock Index è un consolidato indicatore prognostico in terapia intensiva e medicina d'urgenza. In condizioni fisiologiche a riposo, il valore normale oscilla tra 0.5 e 0.7. Un rapporto superiore a 0.9 identifica una discrepanza tra la richiesta metabolica e la capacità contrattile ventricolare, precedendo clinicamente il collasso emodinamico da shock emorragico, settico o cardiogeno prima che la sola ipotensione diventi manifesta.",
        classification: "Regola Clinica Emodinamica Guidata (Rule-Based White-Box)"
      },
      severe_hypotension: {
        title: "Ipotensione Severa & Desaturazione Arteriosa",
        formula: "MBP < 65 mmHg  E  SpO₂ < 90%",
        rationale: "La pressione arteriosa media (MBP) al di sotto dei 65 mmHg compromette drasticamente l'autoregolazione e la perfusione d'organo cerebrale e renale. Quando tale ipoperfusione si associa a desaturazione sistemica dell'ossigeno (SpO₂ < 90%), il paziente sperimenta uno stato di ipossia tissutale critica. La combinazione di queste due soglie delimita un evento sentinella che richiede tempestivo intervento rianimatorio.",
        classification: "Regola Clinica Multi-Parametrica (Soglie Fisiologiche Validate)"
      },
      isolation_forest: {
        title: "Isolation Forest (Machine Learning Non Supervisionato)",
        formula: "Score(x) = 2^(- E(h(x)) / c(n))  [Isolamento Spaziale degli Outlier]",
        rationale: "Algoritmo basato su ensemble di alberi di decisione aleatori (Random Trees). A differenza di altri metodi che calcolano la densità o la distanza dei punti, l'Isolation Forest 'isola' le osservazioni anomale partizionando ricorsivamente lo spazio delle feature (HR, SpO₂, SBP, DBP, MBP). Poiché i punti patologici o artefatti sono rari e dimensionalmente distanti dalla normale traiettoria intraoperatoria, richiedono un numero sensibilmente inferiore di split per essere isolati rispetto ai punti fisiologici ordinari.",
        classification: "Algoritmo ML di Isolamento Spaziale (Scikit-Learn, Complessità O(n log n))"
      },
      autoencoder: {
        title: "Autoencoder Neurale Profondo (Deep Learning)",
        formula: "MSE = (1/N) * ∑ (X_t - X̂_t)² > 95° Percentile",
        rationale: "Rete neurale artificiale addestrata a comprimere la sequenza temporale biometrica in uno spazio latente compatto a bassa dimensionalità (bottleneck) e a ricostruire l'input originario. Durante il monitoraggio stabile, l'errore quadratico medio di ricostruzione (MSE) è ridotto. Quando insorge un pattern disarmonico, aritmico o di repentino collasso emodinamico non previsto dalla varietà latente appresa, l'errore di ricostruzione subisce un'impennata che supera la soglia di allerta del 95° percentile.",
        classification: "Modello Neurale di Ricostruzione d'Errore (MLP/LSTM, PyTorch/Scikit-Learn)"
      }
    };

    const info = data[methodKey] || data.shock_index;

    title.textContent = info.title;
    body.innerHTML = `
      <div class="formula-callout-card">
        <span class="formula-label">Criterio Matematico di Soglia:</span>
        <div class="formula-text num-mono">${info.formula}</div>
      </div>

      <div>
        <h4 class="modal-section-title">Inquadramento Metodologico</h4>
        <p>${info.classification}</p>
      </div>

      <div>
        <h4 class="modal-section-title">Razionale Fisiopatologico & Clinico</h4>
        <p>${info.rationale}</p>
      </div>
    `;

    modal.classList.remove('hidden');
  },

  /**
   * Esporta gli eventi anomali in formato CSV
   */
  exportAnomaliesCSV(caseId, anomalies) {
    if (!anomalies || anomalies.length === 0) {
      alert('Nessun evento anomalo disponibile da esportare.');
      return;
    }

    const headers = ['Timestamp', 'Livello_Severita', 'HR_bpm', 'SpO2_pct', 'NIBP_SBP', 'NIBP_DBP', 'NIBP_MBP', 'Shock_Index', 'Metodi_Rilevati'];
    const rows = anomalies.map(a => [
      `"${a.timestamp}"`,
      `"${a.methods.length >= 3 ? 'Alta' : a.methods.length === 2 ? 'Media' : 'Bassa'}"`,
      a.hr !== null ? a.hr : '',
      a.spo2 !== null ? a.spo2 : '',
      a.sbp !== null ? a.sbp : '',
      a.dbp !== null ? a.dbp : '',
      a.mbp !== null ? a.mbp : '',
      a.shock_index !== null ? a.shock_index : '',
      `"${a.methods.join(';')}"`
    ]);

    const csvContent = 'data:text/csv;charset=utf-8,' + 
      [headers.join(','), ...rows.map(r => r.join(','))].join('\n');

    const encodedUri = encodeURI(csvContent);
    const link = document.createElement('a');
    link.setAttribute('href', encodedUri);
    link.setAttribute('download', `VitalDB_Anomalie_Caso_${caseId}.csv`);
    document.body.appendChild(link);
    link.click();
    document.body.removeChild(link);
    document.body.removeChild(link);
  }
};

window.components = components;
