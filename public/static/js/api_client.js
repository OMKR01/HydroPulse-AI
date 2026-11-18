/**
 * HydroPulse AI — API Client Module
 * Handles robust asynchronous data fetching from Phase 5 REST endpoints,
 * tracking response timing, provenance metadata, and error envelopes.
 */

export class ApiClient {
  constructor(baseUrl = '') {
    this.baseUrl = baseUrl;
  }

  async fetchEndpoint(endpoint) {
    const t0 = performance.now();
    try {
      const resp = await fetch(`${this.baseUrl}${endpoint}`, {
        headers: {
          'Accept': 'application/json',
          'X-Client': 'HydroPulse-Dashboard/0.1.0',
        },
      });

      const elapsedMs = Math.round(performance.now() - t0);
      const provenance = resp.headers.get('X-Data-Provenance') || 'model_reanalysis';
      const cacheStatus = resp.headers.get('X-Cache') || 'MISS';

      if (!resp.ok) {
        const errorJson = await resp.json().catch(() => ({}));
        throw new Error(errorJson?.error?.detail || `HTTP Error ${resp.status}`);
      }

      const json = await resp.json();
      return {
        data: json,
        provenance,
        cacheStatus,
        elapsedMs,
      };
    } catch (err) {
      console.error(`[ApiClient] Failed fetching ${endpoint}:`, err);
      throw err;
    }
  }

  async getStations() {
    return this.fetchEndpoint('/api/v1/stations');
  }

  async getRiskMap() {
    return this.fetchEndpoint('/api/v1/risk/map');
  }

  async getAlerts() {
    return this.fetchEndpoint('/api/v1/alerts');
  }

  async getStationForecast(stationId, days = 7) {
    return this.fetchEndpoint(`/api/v1/stations/${encodeURIComponent(stationId)}/forecast?days=${days}`);
  }

  async getStationHistory(stationId, days = 14) {
    return this.fetchEndpoint(`/api/v1/stations/${encodeURIComponent(stationId)}/history?days=${days}`);
  }

  async getWaterQuality(stationId) {
    return this.fetchEndpoint(`/api/v1/water-quality/${encodeURIComponent(stationId)}`);
  }

  async getDrought(stationId) {
    return this.fetchEndpoint(`/api/v1/drought/${encodeURIComponent(stationId)}`);
  }
}
