/**
 * VITALDB APPLICATION CONTROLLER - MAIN ENTRYPOINT
 * State coordination, router events, user interactions & shortcuts
 */

const app = {
  /**
   * Avvio dell'applicazione
   */
  async init() {
    this.initTheme();
    this.setupEventListeners();
    this.setupKeyboardShortcuts();
    
    await this.checkHealth();
    await this.loadCases();

    // Sottoscrizione allo store
    store.subscribe((state) => {
      this.onStateChange(state);
    });
  },

  /**
   * Inizializzazione tema salvato
   */
  initTheme() {
    const savedTheme = localStorage.getItem('vitaldb_theme') || 'light';
    document.documentElement.setAttribute('data-theme', savedTheme);
    this.updateThemeIcon(savedTheme);
  },

  /**
   * Switch tema Dark / Light
   */
  toggleTheme() {
    const current = document.documentElement.getAttribute('data-theme') || 'dark';
    const next = current === 'dark' ? 'light' : 'dark';
    document.documentElement.setAttribute('data-theme', next);
    localStorage.setItem('vitaldb_theme', next);
    this.updateThemeIcon(next);
    store.setState({ theme: next });

    // Ridisegna grafici se ci sono dati caricati
    const { seriesData, anomalyResults, activeAlgoHighlight } = store.getState();
    if (seriesData.length > 0) {
      renderCharts(seriesData, anomalyResults, activeAlgoHighlight);
    }
  },

  updateThemeIcon(theme) {
    const btn = document.getElementById('btnThemeToggle');
    if (btn) {
      btn.innerHTML = theme === 'dark' ? getIcon('sun') : getIcon('moon');
      btn.setAttribute('title', theme === 'dark' ? 'Passa a Modalità Chiara (Tasto D)' : 'Passa a Modalità Scura (Tasto D)');
    }
  },

  /**
   * Health check periodico del backend Docker e MongoDB
   */
  async checkHealth() {
    const dot = document.getElementById('healthDot');
    const label = document.getElementById('healthLabel');
    
    const res = await api.checkHealth();
    if (res && res.status === 'ok') {
      if (dot) dot.classList.remove('offline');
      if (label) label.textContent = `MongoDB 8.0 • ${(res.total_points || 311173).toLocaleString()} p.ti`;
    } else {
      if (dot) dot.classList.add('offline');
      if (label) label.textContent = 'API Offline su :8000';
    }
  },

  /**
   * Carica la lista di casi clinici da MongoDB
   */
  async loadCases() {
    try {
      const cases = await api.getCases();
      store.setState({ cases });

      // Popola i filtri dei reparti
      components.renderDeptPills(cases, store.getState().departmentFilter);

      // Renderizza la lista nella sidebar
      components.renderCaseList(store.getFilteredCases(), store.getState().currentCaseId);

      // Seleziona il primo caso se disponibile
      if (cases.length > 0 && !store.getState().currentCaseId) {
        this.selectCase(cases[0].case_id);
      }
    } catch (err) {
      const listContainer = document.getElementById('caseScrollList');
      if (listContainer) {
        listContainer.innerHTML = `
          <div style="color:var(--alert-critical); padding:1rem; font-size:0.8rem; text-align:center;">
            Errore di connessione a MongoDB.
          </div>`;
      }
    }
  },

  /**
   * Seleziona un caso clinico e ne carica la serie temporale
   */
  async selectCase(caseId) {
    const { cases, downsampleWindow } = store.getState();
    const caseObj = cases.find(c => c.case_id === caseId) || { case_id: caseId, department: 'Chirurgia' };

    store.setState({
      currentCaseId: caseId,
      currentCase: caseObj,
      anomalyResults: null,
      activeAlgoHighlight: null
    });

    // Aggiorna classe attiva nella lista
    components.renderCaseList(store.getFilteredCases(), caseId);

    // Mostra canvas e nasconde empty state
    const emptyState = document.getElementById('emptyStatePlaceholder');
    const workbenchCanvas = document.getElementById('workbenchCanvas');
    if (emptyState) emptyState.classList.add('hidden');
    if (workbenchCanvas) workbenchCanvas.classList.remove('hidden');

    await this.loadSeries(caseId, downsampleWindow);
  },

  /**
   * Carica la serie temporale per il caso specificato
   */
  async loadSeries(caseId, windowSeconds) {
    try {
      const seriesData = await api.getSeries(caseId, windowSeconds);
      store.setState({ seriesData });

      const caseObj = store.getState().currentCase;
      components.renderPatientHUD(caseObj, seriesData.length);
      components.renderBentoVitals(seriesData, null);
      components.renderConsensusBar(null, null);

      // Reset della tabella anomalie
      const tableWrapper = document.getElementById('anomalyTableWrapper');
      if (tableWrapper) tableWrapper.classList.add('hidden');

      // Renderizza grafici
      renderCharts(seriesData, null, null);
    } catch (err) {
      alert(`Errore nel caricamento della serie temporale per il caso #${caseId}`);
    }
  },

  /**
   * Esegue l'Anomaly Detection sul caso attivo
   */
  async runDetection() {
    const { currentCaseId, seriesData } = store.getState();
    if (!currentCaseId) return;

    const btn = document.getElementById('btnRunDetection');
    if (btn) {
      btn.innerHTML = `${getIcon('refresh', 'animate-spin')} Rilevamento in corso...`;
      btn.disabled = true;
    }

    try {
      const anomalyResults = await api.runDetect(currentCaseId);
      store.setState({ anomalyResults, activeAlgoHighlight: null });

      components.renderBentoVitals(seriesData, anomalyResults);
      components.renderConsensusBar(anomalyResults, null);
      components.renderAnomalyTable(anomalyResults.anomalies, 'all', store.getState().anomalyLimit);

      // Aggiorna grafici con gli overlay delle anomalie
      renderCharts(seriesData, anomalyResults, null);
    } catch (err) {
      alert(`Errore durante l'elaborazione dell'Anomaly Detection: ${err.message}`);
    } finally {
      if (btn) {
        btn.innerHTML = `${getIcon('shieldAlert')} Rileva Anomalie`;
        btn.disabled = false;
      }
    }
  },

  /**
   * Cambia la risoluzione temporale (Downsampling)
   */
  onWindowChange(val) {
    store.setState({ downsampleWindow: val });
    const { currentCaseId } = store.getState();
    if (currentCaseId) {
      this.loadSeries(currentCaseId, val);
    }
  },

  /**
   * Filtra per reparto chirurgico
   */
  setDeptFilter(dept) {
    store.setState({ departmentFilter: dept });
    const filtered = store.getFilteredCases();
    components.renderDeptPills(store.getState().cases, dept);
    components.renderCaseList(filtered, store.getState().currentCaseId);
  },

  /**
   * Cerca per ID caso o nome reparto
   */
  onSearchInput(val) {
    store.setState({ searchQuery: val });
    const filtered = store.getFilteredCases();
    components.renderCaseList(filtered, store.getState().currentCaseId);
  },

  /**
   * Cambia la tab principale (Serie Temporali vs Lakehouse & Governance)
   */
  switchTab(tabKey) {
    store.setState({ activeTab: tabKey });

    const btnSeries = document.getElementById('tabSeriesBtn');
    const btnLake = document.getElementById('tabLakehouseBtn');
    const viewSeries = document.getElementById('viewSeries');
    const viewLake = document.getElementById('viewLakehouse');

    if (tabKey === 'series') {
      btnSeries.classList.add('active');
      btnLake.classList.remove('active');
      viewSeries.classList.remove('hidden');
      viewLake.classList.add('hidden');
    } else {
      btnLake.classList.add('active');
      btnSeries.classList.remove('active');
      viewLake.classList.remove('hidden');
      viewSeries.classList.add('hidden');
      
      // Inizializza o aggiorna le viste Lakehouse
      lakehouseView.init();
    }
  },

  /**
   * Evidenzia le anomalie di un singolo algoritmo sui grafici
   */
  toggleAlgoHighlight(methodKey) {
    const { activeAlgoHighlight, seriesData, anomalyResults } = store.getState();
    const nextHighlight = activeAlgoHighlight === methodKey ? null : methodKey;
    
    store.setState({ activeAlgoHighlight: nextHighlight });
    components.renderConsensusBar(anomalyResults, nextHighlight);
    renderCharts(seriesData, anomalyResults, nextHighlight);
  },

  /**
   * Filtra la tabella delle anomalie per severità o metodo
   */
  onTableFilterChange(filterVal) {
    store.setState({ anomalyMethodFilter: filterVal });
    const { anomalyResults, anomalyLimit } = store.getState();
    if (anomalyResults) {
      components.renderAnomalyTable(anomalyResults.anomalies, filterVal, anomalyLimit);
    }
  },

  /**
   * Cambia il limite delle righe visibili in tabella
   */
  onTableLimitChange(limitVal) {
    store.setState({ anomalyLimit: limitVal });
    const { anomalyResults, anomalyMethodFilter } = store.getState();
    if (anomalyResults) {
      components.renderAnomalyTable(anomalyResults.anomalies, anomalyMethodFilter, limitVal);
    }
  },

  /**
   * Esporta gli eventi anomali filtrati in CSV
   */
  exportCSV() {
    const { currentCaseId, anomalyResults, anomalyMethodFilter } = store.getState();
    if (!anomalyResults || !anomalyResults.anomalies) return;

    let items = anomalyResults.anomalies;
    if (anomalyMethodFilter === 'high_severity') {
      items = items.filter(a => a.methods.length >= 3);
    } else if (anomalyMethodFilter !== 'all') {
      items = items.filter(a => a.methods.includes(anomalyMethodFilter));
    }

    components.exportAnomaliesCSV(currentCaseId, items);
  },

  /**
   * Ispezione timestamp anomalo da riga tabella
   */
  inspectAnomalyTimestamp(ts) {
    // Evidenzia riga e sposta il mirino
    console.log(`Focus su timestamp anomalo: ${ts}`);
  },

  /**
   * Apre spiegazione clinica in modale
   */
  openExplanation(methodKey) {
    components.openModalExplanation(methodKey);
  },

  /**
   * Chiude la modale attiva
   */
  closeModal() {
    const modal = document.getElementById('explanationModal');
    if (modal) modal.classList.add('hidden');
  },

  /**
   * Configura scorciatoie da tastiera
   */
  setupKeyboardShortcuts() {
    window.addEventListener('keydown', (e) => {
      // Tasto / per cercare
      if (e.key === '/' && document.activeElement.tagName !== 'INPUT') {
        e.preventDefault();
        const searchInput = document.getElementById('caseSearchInput');
        if (searchInput) searchInput.focus();
      }
      // Tasto Esc per chiudere modali
      if (e.key === 'Escape') {
        this.closeModal();
      }
      // Tasto D per commutare tema
      if ((e.key === 'd' || e.key === 'D') && document.activeElement.tagName !== 'INPUT') {
        this.toggleTheme();
      }
      // Tasti 1 e 2 per navigazione tabs
      if (e.key === '1' && document.activeElement.tagName !== 'INPUT') {
        this.switchTab('series');
      }
      if (e.key === '2' && document.activeElement.tagName !== 'INPUT') {
        this.switchTab('lakehouse');
      }
      // Tasto R per eseguire rilevamento
      if ((e.key === 'r' || e.key === 'R') && document.activeElement.tagName !== 'INPUT') {
        this.runDetection();
      }
    });
  },

  setupEventListeners() {
    // Chiudi modale cliccando sul backdrop
    const modal = document.getElementById('explanationModal');
    if (modal) {
      modal.addEventListener('click', (e) => {
        if (e.target === modal) this.closeModal();
      });
    }
  },

  onStateChange(state) {
    // Hook per eventuali reazioni globali
  }
};

window.app = app;

// Avvio al caricamento del DOM
document.addEventListener('DOMContentLoaded', async () => {
  // Carica i template parziali in modo asincrono prima di avviare l'app
  if (typeof loadPartials === 'function') {
    await loadPartials();
  }
  app.init();
});
