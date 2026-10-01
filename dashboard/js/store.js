/**
 * VITALDB APPLICATION STORE - REACTIVE STATE MANAGEMENT
 * Pub/Sub Pattern for modular synchronization across views and components
 */

class AppStore {
  constructor() {
    this.state = {
      cases: [],
      currentCaseId: null,
      currentCase: null,
      departmentFilter: '',
      searchQuery: '',
      seriesData: [],
      anomalyResults: null,
      activeTab: 'series',
      theme: localStorage.getItem('vitaldb_theme') || 'light',
      downsampleWindow: '60',
      anomalyMethodFilter: 'all',
      anomalyLimit: 'all',
      activeAlgoHighlight: null,
      isDetecting: false,
      benchmarkData: null,
      qualityData: null,
      evaluationData: null
    };

    this.listeners = [];
  }

  getState() {
    return this.state;
  }

  setState(updates) {
    this.state = { ...this.state, ...updates };
    this.notify();
  }

  subscribe(listener) {
    this.listeners.push(listener);
    return () => {
      this.listeners = this.listeners.filter(l => l !== listener);
    };
  }

  notify() {
    for (const listener of this.listeners) {
      try {
        listener(this.state);
      } catch (err) {
        console.error('Errore listener store:', err);
      }
    }
  }

  /**
   * Helper per filtrare l'elenco dei casi in base a ricerca e reparto
   */
  getFilteredCases() {
    let list = this.state.cases;
    if (this.state.departmentFilter) {
      list = list.filter(c => c.department === this.state.departmentFilter);
    }
    if (this.state.searchQuery) {
      const q = this.state.searchQuery.toLowerCase().trim();
      list = list.filter(c => 
        String(c.case_id).includes(q) || 
        (c.department && c.department.toLowerCase().includes(q))
      );
    }
    return list;
  }
}

// Istanza singleton condivisa
const store = new AppStore();
window.store = store;
