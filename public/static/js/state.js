/**
 * HydroPulse AI — State Management Module
 * Central store for selected station, language toggle (en/hi), active tab,
 * filter state, and cached API responses.
 */

export const state = {
  currentLang: 'en', // 'en' | 'hi'
  activeBasinFilter: 'all', // 'all' | 'Damodar' | 'Subarnarekha'
  activeStationId: null,
  activeTab: 'forecast', // 'forecast' | 'health' | 'drought'

  // Data cache
  stations: [],
  riskMap: null,
  alerts: [],
  stationDetailsCache: new Map(),

  // Event subscribers
  listeners: new Set(),

  subscribe(listener) {
    this.listeners.add(listener);
    return () => this.listeners.delete(listener);
  },

  notify(event, payload) {
    for (const listener of this.listeners) {
      listener(event, payload);
    }
  },

  setLang(lang) {
    if (this.currentLang !== lang) {
      this.currentLang = lang;
      this.notify('lang_changed', lang);
    }
  },

  setActiveBasin(basin) {
    this.activeBasinFilter = basin;
    this.notify('basin_filter_changed', basin);
  },

  setActiveStation(stationId) {
    this.activeStationId = stationId;
    this.notify('station_selected', stationId);
  },

  setActiveTab(tabName) {
    this.activeTab = tabName;
    this.notify('tab_changed', tabName);
  },
};
