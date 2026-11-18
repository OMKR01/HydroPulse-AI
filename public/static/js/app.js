/**
 * HydroPulse AI — Application Entry Point
 * Wires together state, API client, Leaflet map, Chart.js hydrographs,
 * river health views, drought trackers, and bilingual EN/HI translations.
 */

import { ApiClient } from './api_client.js';
import { state } from './state.js';
import { MapView } from './map_view.js';
import { HydrographChart } from './hydrograph.js';
import { HealthView } from './health_view.js';
import { DroughtView } from './drought_view.js';

// Bilingual UI Text Dictionary (English & Hindi)
const I18N = {
  en: {
    subhead: 'Jharkhand River Health & Flood Early Warning System',
    refreshText: 'Refresh',
    disclaimerTitle: 'STATUTORY ADVISORY:',
    disclaimerBody: 'HydroPulse AI is an experimental ML research & decision-support system. Official flood warnings, reservoir release advisories, and evacuation notices are issued exclusively by the Central Water Commission (CWC) and Jharkhand State Disaster Management Authority (JSDMA).',
    tickerBadge: 'ACTIVE ALERTS',
    tickerNormal: 'All monitored Jharkhand river stations currently below alert thresholds.',
    filterAll: 'All Basins',
    legendTitle: 'Risk Level Legend',
    legendNormal: 'Normal (Q < P90)',
    legendWatch: 'Watch (P90 ≤ Q < P95)',
    legendWarning: 'Warning (P95 ≤ Q < P99)',
    legendDanger: 'Danger (Q ≥ P99)',
    narrativeHeading: 'Early Warning Status',
    whyTitle: 'Why is this station at this level?',
    tabForecast: 'Flood Forecast (7-Day)',
    tabHealth: 'River Health (WQI)',
    tabDrought: 'Drought & Low-Flow',
    hydroTitle: 'Discharge Hydrograph & 7-Day Forecast Band',
    legHistory: 'Observed / Model (14d)',
    legP50: 'Forecast (P50)',
    legBand: 'Uncertainty Band (P10–P90)',
    peakLabel: 'Peak Forecast',
    p90Label: '90th Percentile Peak',
    wqiTitle: 'Weighted-Arithmetic WQI',
    wqParamsTitle: 'Parameter Readings (mg/L except pH/Cond)',
    droughtStatusTitle: 'Compound Drought Severity',
    outlookTitle: '30-Day Forward Trajectory',
  },
  hi: {
    subhead: 'झारखंड नदी स्वास्थ्य एवं बाढ़ पूर्व चेतावनी प्रणाली',
    refreshText: 'ताज़ा करें',
    disclaimerTitle: 'सांविधिक सलाह:',
    disclaimerBody: 'हाइड्रोपल्स एआई एक प्रायोगिक एमएल अनुसंधान और निर्णय-समर्थन प्रणाली है। आधिकारिक बाढ़ चेतावनी, जलाशय निर्वहन सलाह और निकासी निर्देश केवल केंद्रीय जल आयोग (CWC) और झारखंड राज्य आपदा प्रबंधन प्राधिकरण (JSDMA) द्वारा जारी किए जाते हैं।',
    tickerBadge: 'सक्रिय अलर्ट',
    tickerNormal: 'वर्तमान में झारखंड के सभी निगरानी स्टेशन चेतावनी स्तर से नीचे सामान्य हैं।',
    filterAll: 'सभी बेसिन',
    legendTitle: 'जोखिम स्तर संकेत',
    legendNormal: 'सामान्य (Q < P90)',
    legendWatch: 'निगरानी (P90 ≤ Q < P95)',
    legendWarning: 'चेतावनी (P95 ≤ Q < P99)',
    legendDanger: 'खतरा (Q ≥ P99)',
    narrativeHeading: 'पूर्व चेतावनी स्थिति',
    whyTitle: 'यह स्टेशन इस स्तर पर क्यों है?',
    tabForecast: 'बाढ़ पूर्वानुमान (7-दिन)',
    tabHealth: 'नदी स्वास्थ्य (WQI)',
    tabDrought: 'सूखा एवं निम्न-प्रवाह',
    hydroTitle: 'जल निर्वहन हाइड्रोग्राफ एवं 7-दिवसीय पूर्वानुमान बैंड',
    legHistory: 'अवलोकित / मॉडल (14 दिन)',
    legP50: 'पूर्वानुमान (P50)',
    legBand: 'अनिश्चितता बैंड (P10–P90)',
    peakLabel: 'चरम पूर्वानुमान',
    p90Label: '90वाँ शतमक चरम',
    wqiTitle: 'भारित-अंकगणितीय WQI',
    wqParamsTitle: 'मापदंड पाठ्यांक (pH/चालकता को छोड़कर mg/L में)',
    droughtStatusTitle: 'संयुक्त सूखा गंभीरता',
    outlookTitle: '30-दिवसीय अग्रगामी प्रक्षेपवक्र',
  },
};

class DashboardApp {
  constructor() {
    this.api = new ApiClient();
    this.mapView = null;
    this.hydrograph = null;
    this.currentStationData = null;

    this.init();
  }

  async init() {
    // 1. Initialize Map
    this.mapView = new MapView('map-viewport', (stationId) => {
      this.selectStation(stationId);
    });

    // 2. Initialize Hydrograph
    this.hydrograph = new HydrographChart('hydrograph-canvas');

    // 3. Wire DOM Events
    this.wireEvents();

    // 4. Initial Data Load
    await this.refreshData();

    // 5. Auto-select first station (e.g. Bokaro or Ramgarh)
    const firstFeature = state.riskMap?.features?.[0];
    if (firstFeature) {
      this.selectStation(firstFeature.properties.station_id);
    }

    // 6. Setup 60s live refresh polling
    setInterval(() => this.refreshData(true), 60000);

    // 7. Live Real-Time Clock
    this.startLiveClock();
  }

  startLiveClock() {
    const clockEl = document.getElementById('system-clock-display');
    if (!clockEl) return;

    const pad = (n) => String(n).padStart(2, '0');

    const updateClock = () => {
      const now = new Date();
      const year = now.getFullYear();
      const month = pad(now.getMonth() + 1);
      const day = pad(now.getDate());
      const hours = pad(now.getHours());
      const mins = pad(now.getMinutes());
      const secs = pad(now.getSeconds());
      clockEl.textContent = `${year}-${month}-${day} ${hours}:${mins}:${secs} IST`;
    };

    updateClock();
    setInterval(updateClock, 1000);
  }

  wireEvents() {
    // Language Toggle
    const langBtn = document.getElementById('lang-toggle-btn');
    if (langBtn) {
      langBtn.addEventListener('click', () => {
        const nextLang = state.currentLang === 'en' ? 'hi' : 'en';
        state.setLang(nextLang);
        this.applyLanguage(nextLang);
        this.updateLangBtn(nextLang);
        if (state.activeStationId) {
          this.updateStationNarrative(this.currentStationData);
        }
      });
    }

    // Refresh Button
    const refreshBtn = document.getElementById('refresh-data-btn');
    if (refreshBtn) {
      refreshBtn.addEventListener('click', async () => {
        refreshBtn.classList.add('spinning');
        await this.refreshData();
        setTimeout(() => refreshBtn.classList.remove('spinning'), 600);
      });
    }

    // Basin Filters
    const filterPills = document.querySelectorAll('.basin-pill');
    filterPills.forEach((pill) => {
      pill.addEventListener('click', () => {
        filterPills.forEach((p) => {
          p.classList.remove('active');
          p.setAttribute('aria-checked', 'false');
        });
        pill.classList.add('active');
        pill.setAttribute('aria-checked', 'true');

        const basin = pill.dataset.basin || 'all';
        state.setActiveBasin(basin);
        this.mapView.renderStations(state.riskMap, basin, state.currentLang);
      });
    });

    // Panel Tabs
    const tabs = [
      { btnId: 'tab-btn-forecast', paneId: 'tab-pane-forecast', name: 'forecast' },
      { btnId: 'tab-btn-health', paneId: 'tab-pane-health', name: 'health' },
      { btnId: 'tab-btn-drought', paneId: 'tab-pane-drought', name: 'drought' },
    ];

    tabs.forEach(({ btnId, paneId, name }) => {
      const btn = document.getElementById(btnId);
      if (btn) {
        btn.addEventListener('click', () => {
          tabs.forEach((t) => {
            const b = document.getElementById(t.btnId);
            const p = document.getElementById(t.paneId);
            if (b) {
              b.classList.remove('active');
              b.setAttribute('aria-selected', 'false');
            }
            if (p) {
              p.classList.remove('active');
              p.hidden = true;
            }
          });

          btn.classList.add('active');
          btn.setAttribute('aria-selected', 'true');
          const pane = document.getElementById(paneId);
          if (pane) {
            pane.classList.add('active');
            pane.hidden = false;
          }
          state.setActiveTab(name);
        });
      }
    });
  }

  updateLangBtn(lang) {
    const enSpan = document.querySelector('.lang-en');
    const hiSpan = document.querySelector('.lang-hi');
    if (enSpan && hiSpan) {
      if (lang === 'hi') {
        enSpan.classList.remove('active');
        hiSpan.classList.add('active');
      } else {
        enSpan.classList.add('active');
        hiSpan.classList.remove('active');
      }
    }
  }

  applyLanguage(lang) {
    const dict = I18N[lang] || I18N.en;
    const setText = (id, text) => {
      const el = document.getElementById(id);
      if (el) el.textContent = text;
    };

    setText('i18n-subhead', dict.subhead);
    setText('i18n-refresh-text', dict.refreshText);
    setText('i18n-disclaimer-title', dict.disclaimerTitle);
    setText('i18n-disclaimer-body', dict.disclaimerBody);
    setText('i18n-ticker-badge', dict.tickerBadge);
    setText('i18n-filter-all', dict.filterAll);
    setText('i18n-legend-title', dict.legendTitle);
    setText('i18n-legend-normal', dict.legendNormal);
    setText('i18n-legend-watch', dict.legendWatch);
    setText('i18n-legend-warning', dict.legendWarning);
    setText('i18n-legend-danger', dict.legendDanger);
    setText('i18n-narrative-heading', dict.narrativeHeading);
    setText('i18n-why-title', dict.whyTitle);
    setText('i18n-tab-forecast', dict.tabForecast);
    setText('i18n-tab-health', dict.tabHealth);
    setText('i18n-tab-drought', dict.tabDrought);
    setText('i18n-hydrograph-title', dict.hydroTitle);
    setText('i18n-leg-history', dict.legHistory);
    setText('i18n-leg-p50', dict.legP50);
    setText('i18n-leg-band', dict.legBand);
    setText('i18n-peak-label', dict.peakLabel);
    setText('i18n-p90-label', dict.p90Label);
    setText('i18n-wqi-title', dict.wqiTitle);
    setText('i18n-wq-params-title', dict.wqParamsTitle);
    setText('i18n-drought-status-title', dict.droughtStatusTitle);
    setText('i18n-outlook-title', dict.outlookTitle);

    // Re-render map markers with new tooltip languages
    if (state.riskMap && this.mapView) {
      this.mapView.renderStations(state.riskMap, state.activeBasinFilter, lang);
    }
  }

  async refreshData(isSilent = false) {
    try {
      const [riskMapResp, alertsResp] = await Promise.all([
        this.api.getRiskMap(),
        this.api.getAlerts(),
      ]);

      state.riskMap = riskMapResp.data;
      state.alerts = alertsResp.data?.alerts || [];

      // Update Provenance Pill
      const provPill = document.getElementById('provenance-label');
      if (provPill && riskMapResp.data?.data_provenance) {
        provPill.textContent = riskMapResp.data.data_provenance.toUpperCase().replace('_', ' ');
      }

      // Render Map Markers
      this.mapView.renderStations(state.riskMap, state.activeBasinFilter, state.currentLang);

      // Update Risk Summary Counters
      this.updateRiskCounters(state.riskMap);

      // Update Basin Alert Ticker
      this.updateAlertsTicker(state.alerts);

      // If active station selected, refresh it
      if (state.activeStationId) {
        await this.selectStation(state.activeStationId, true);
      }
    } catch (err) {
      console.error('[DashboardApp] Refresh failed:', err);
    }
  }

  updateRiskCounters(geoJson) {
    const counts = { normal: 0, watch: 0, warning: 0, danger: 0 };
    const features = geoJson?.features || [];

    features.forEach((f) => {
      const lvl = (f.properties?.alert_level || 'normal').toLowerCase();
      if (counts[lvl] !== undefined) {
        counts[lvl]++;
      }
    });

    const setNum = (id, num) => {
      const el = document.getElementById(id);
      if (el) el.textContent = num;
    };

    setNum('count-normal', counts.normal);
    setNum('count-watch', counts.watch);
    setNum('count-warning', counts.warning);
    setNum('count-danger', counts.danger);
  }

  updateAlertsTicker(alerts) {
    const tickerEl = document.getElementById('alerts-ticker-content');
    if (!tickerEl) return;

    if (!alerts || alerts.length === 0) {
      tickerEl.textContent = state.currentLang === 'hi' ? I18N.hi.tickerNormal : I18N.en.tickerNormal;
      return;
    }

    const messages = alerts.map((a) => {
      const msg = state.currentLang === 'hi' ? a.message_hi : a.message_en;
      return `[${a.alert_level.toUpperCase()}] ${a.station_name}: ${msg}`;
    });

    tickerEl.textContent = messages.join('  •  ');
  }

  async selectStation(stationId, forceReload = false) {
    state.setActiveStation(stationId);
    this.mapView.highlightStation(stationId);

    // Find GeoJSON properties for header metadata
    const feature = state.riskMap?.features?.find((f) => f.properties?.station_id === stationId);
    const props = feature?.properties || {};

    // Update Header Metadata
    const nameEl = document.getElementById('detail-station-name');
    const basinRiverEl = document.getElementById('detail-basin-river');
    const coordsEl = document.getElementById('detail-coords');
    const verifiedEl = document.getElementById('detail-verified-tag');

    if (nameEl) nameEl.textContent = props.station_name || stationId;
    if (basinRiverEl) basinRiverEl.textContent = `${props.basin || 'Jharkhand'} Basin • ${props.river || 'River'}`;
    if (coordsEl) {
      const [lon, lat] = feature?.geometry?.coordinates || [0, 0];
      coordsEl.textContent = `Lat: ${lat.toFixed(4)}° N • Lon: ${lon.toFixed(4)}° E`;
    }
    if (verifiedEl) {
      verifiedEl.textContent = props.verified ? 'Verified Gauge' : 'Candidate Gauge (Verified: False)';
      verifiedEl.style.color = props.verified ? '#10b981' : '#fdba74';
    }

    // Update Alert Badge in Header
    const riskBadge = document.getElementById('detail-risk-badge');
    const riskSymbol = document.getElementById('detail-risk-symbol');
    const riskName = document.getElementById('detail-risk-name');
    const alertLevel = (props.alert_level || 'normal').toLowerCase();

    const symbols = { normal: '●', watch: '■', warning: '▲', danger: '◆' };
    if (riskSymbol) riskSymbol.textContent = symbols[alertLevel] || '●';
    if (riskName) riskName.textContent = alertLevel.toUpperCase();

    if (riskBadge) {
      riskBadge.className = `station-alert-badge counter-${alertLevel}`;
    }

    // Parallel fetch station-specific intelligence
    try {
      const [forecastResp, historyResp, wqResp, droughtResp] = await Promise.all([
        this.api.getStationForecast(stationId, 7),
        this.api.getStationHistory(stationId, 14),
        this.api.getWaterQuality(stationId),
        this.api.getDrought(stationId),
      ]);

      this.currentStationData = {
        props,
        forecast: forecastResp.data,
        history: historyResp.data,
        wq: wqResp.data,
        drought: droughtResp.data,
      };

      // 1. Narrative & Explainability
      this.updateStationNarrative(this.currentStationData);

      // 2. Hydrograph & Forecast Metrics
      this.hydrograph.render(historyResp.data, forecastResp.data, forecastResp.data?.thresholds);
      this.updateForecastMetrics(forecastResp.data);

      // 3. Water Quality & CPCB Class
      HealthView.render(wqResp.data, state.currentLang);

      // 4. Drought & SPI Tracker
      DroughtView.render(droughtResp.data, state.currentLang);
    } catch (err) {
      console.error(`[DashboardApp] Error loading station ${stationId}:`, err);
    }
  }

  updateStationNarrative(data) {
    if (!data) return;
    const alertTextEl = document.getElementById('detail-alert-text');
    const factorsListEl = document.getElementById('detail-explain-factors');

    // Find station alert if active
    const activeAlert = state.alerts?.find((a) => a.station_id === data.props?.station_id);

    if (alertTextEl) {
      if (activeAlert) {
        alertTextEl.textContent = state.currentLang === 'hi' ? activeAlert.message_hi : activeAlert.message_en;
      } else {
        alertTextEl.textContent = state.currentLang === 'hi'
          ? 'नदी में जल निर्वहन मौसमी आधार रेखा के भीतर है। तत्काल बाढ़ का कोई खतरा नहीं है।'
          : 'River discharge is tracking seasonal baseline conditions. No immediate flood risk detected.';
      }
    }

    if (factorsListEl) {
      factorsListEl.innerHTML = '';
      const factors = activeAlert?.primary_factors || [
        'Historical seasonal baseline flow rates observed across the catchment.',
        'No significant 48h antecedent precipitation surge detected.',
      ];

      factors.forEach((f) => {
        const li = document.createElement('li');
        li.textContent = f;
        factorsListEl.appendChild(li);
      });
    }
  }

  updateForecastMetrics(forecastData) {
    const peakQ = document.getElementById('metric-peak-q');
    const peakDay = document.getElementById('metric-peak-day');
    const p90Peak = document.getElementById('metric-p90-peak');
    const threshWarn = document.getElementById('metric-threshold-warning');
    const threshDang = document.getElementById('metric-threshold-danger');

    const forecastItems = forecastData?.forecast || [];
    let maxP50 = 0;
    let maxP50Day = 1;
    let maxP90 = 0;

    forecastItems.forEach((f) => {
      if (f.p50 > maxP50) {
        maxP50 = f.p50;
        maxP50Day = f.horizon_days;
      }
      if (f.p90 > maxP90) {
        maxP90 = f.p90;
      }
    });

    if (peakQ) peakQ.textContent = `${maxP50.toFixed(1)} m³/s`;
    if (peakDay) peakDay.textContent = `Lead Day t+${maxP50Day}`;
    if (p90Peak) p90Peak.textContent = `${maxP90.toFixed(1)} m³/s`;

    const thresh = forecastData?.thresholds || {};
    if (threshWarn) threshWarn.textContent = thresh.warning ? `${thresh.warning.toFixed(1)} m³/s` : '-- m³/s';
    if (threshDang) threshDang.textContent = thresh.danger ? `${thresh.danger.toFixed(1)} m³/s` : '-- m³/s';
  }
}

// Bootstrap on DOM ready
document.addEventListener('DOMContentLoaded', () => {
  window.app = new DashboardApp();
});
