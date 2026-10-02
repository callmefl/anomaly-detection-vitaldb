/**
 * VITALDB CLIENT SERVICE - ASYNC API LAYER
 * Handles communications with FastAPI Docker backend on port 8000
 */

const API_BASE = window.location.origin.includes('8000') 
  ? window.location.origin 
  : 'http://localhost:8000';

const api = {
  /**
   * Health Check dell'API e del cluster MongoDB TimeSeries
   */
  async checkHealth() {
    try {
      const res = await fetch(`${API_BASE}/health`, { signal: AbortSignal.timeout(4000) });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      return await res.json();
    } catch (err) {
      console.warn('API Health check fallito:', err);
      return null;
    }
  },

  /**
   * Lista dei casi clinici registrati in MongoDB Gold
   */
  async getCases() {
    try {
      const res = await fetch(`${API_BASE}/cases`, { signal: AbortSignal.timeout(6000) });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      return await res.json();
    } catch (err) {
      console.error('Errore getCases:', err);
      throw err;
    }
  },

  /**
   * Serie temporale biometrica con supporto downsampling (window_seconds)
   */
  async getSeries(caseId, windowSeconds = '') {
    const query = windowSeconds ? `?window_seconds=${windowSeconds}` : '';
    const res = await fetch(`${API_BASE}/cases/${caseId}/series${query}`, { signal: AbortSignal.timeout(10000) });
    if (!res.ok) throw new Error(`Impossibile recuperare serie per case #${caseId}`);
    return await res.json();
  },

  /**
   * Esegue la pipeline di Anomaly Detection (Regole Cliniche + Modelli ML)
   */
  async runDetect(caseId) {
    const res = await fetch(`${API_BASE}/cases/${caseId}/detect`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      signal: AbortSignal.timeout(60000)
    });
    if (!res.ok) throw new Error(`Errore esecuzione detection per case #${caseId}`);
    return await res.json();
  },

  /**
   * Recupera il Benchmark delle prestazioni ETL e storage (Bronze vs Silver vs Gold)
   */
  async getBenchmark() {
    try {
      const res = await fetch(`${API_BASE}/benchmark`, { signal: AbortSignal.timeout(5000) });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      return await res.json();
    } catch (err) {
      console.warn('Benchmark live non disponibile, caricamento cache...');
      return null;
    }
  },

  /**
   * Recupera il Data Quality Report live generato dal layer Silver
   */
  async getQuality() {
    try {
      const res = await fetch(`${API_BASE}/quality`, { signal: AbortSignal.timeout(5000) });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      return await res.json();
    } catch (err) {
      console.warn('Quality report live non disponibile, caricamento cache...');
      return null;
    }
  },

  /**
   * Recupera il Report quantitativo Machine Learning (Precision/Recall/F1/AUC)
   */
  async getEvaluation() {
    try {
      const res = await fetch(`${API_BASE}/evaluation`, { signal: AbortSignal.timeout(5000) });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      return await res.json();
    } catch (err) {
      console.warn('Evaluation report live non disponibile, caricamento cache...');
      return null;
    }
  }
};

window.api = api;
