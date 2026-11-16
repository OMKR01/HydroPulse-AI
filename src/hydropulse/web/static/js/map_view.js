/**
 * HydroPulse AI — Leaflet Map View Module
 * Renders color-blind safe SVG markers (Shape + Color + Text Label) for each station,
 * handles geospatial risk overlays, click events, and basin filtering.
 */

/* global L */

const RISK_CONFIG = {
  normal: {
    color: '#10b981',
    symbol: '●',
    labelEn: 'Normal',
    labelHi: 'सामान्य',
    svg: (color) => `<svg width="24" height="24" viewBox="0 0 24 24" class="marker-svg">
      <circle cx="12" cy="12" r="9" fill="${color}" stroke="#ffffff" stroke-width="2"/>
    </svg>`,
  },
  watch: {
    color: '#f59e0b',
    symbol: '■',
    labelEn: 'Watch',
    labelHi: 'निगरानी',
    svg: (color) => `<svg width="24" height="24" viewBox="0 0 24 24" class="marker-svg">
      <rect x="3" y="3" width="18" height="18" rx="3" fill="${color}" stroke="#ffffff" stroke-width="2"/>
    </svg>`,
  },
  warning: {
    color: '#f43f5e',
    symbol: '▲',
    labelEn: 'Warning',
    labelHi: 'चेतावनी',
    svg: (color) => `<svg width="26" height="26" viewBox="0 0 26 26" class="marker-svg pulsing-marker">
      <polygon points="13,2 25,23 1,23" fill="${color}" stroke="#ffffff" stroke-width="2"/>
    </svg>`,
  },
  danger: {
    color: '#9333ea',
    symbol: '◆',
    labelEn: 'Danger',
    labelHi: 'खतरा',
    svg: (color) => `<svg width="26" height="26" viewBox="0 0 26 26" class="marker-svg pulsing-marker">
      <polygon points="13,1 25,13 13,25 1,13" fill="${color}" stroke="#ffffff" stroke-width="2"/>
    </svg>`,
  },
};

export class MapView {
  constructor(containerId, onStationSelect) {
    this.containerId = containerId;
    this.onStationSelect = onStationSelect;
    this.map = null;
    this.markersLayer = null;
    this.features = [];
    this.activeStationId = null;

    this.initMap();
  }

  initMap() {
    // Center of Jharkhand (Ranchi/Damodar/Subarnarekha confluence corridor)
    const jharkhandCenter = [23.6102, 85.2799];
    const initialZoom = 8;

    this.map = L.map(this.containerId, {
      center: jharkhandCenter,
      zoom: initialZoom,
      minZoom: 6,
      maxZoom: 14,
      zoomControl: true,
    });

    // High-contrast, clean CartoDB Dark Matter basemap
    L.tileLayer('https://{s}.basemaps.cartocdn.com/rastertiles/voyager/{z}/{x}/{y}{r}.png', {
      attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> &copy; <a href="https://carto.com/attributions">CARTO</a>',
      subdomains: 'abcd',
      maxZoom: 19,
    }).addTo(this.map);

    this.markersLayer = L.layerGroup().addTo(this.map);
  }

  createStationIcon(alertLevel) {
    const levelKey = (alertLevel || 'normal').toLowerCase();
    const cfg = RISK_CONFIG[levelKey] || RISK_CONFIG.normal;

    return L.divIcon({
      className: 'custom-station-icon',
      html: cfg.svg(cfg.color),
      iconSize: [26, 26],
      iconAnchor: [13, 13],
      popupAnchor: [0, -14],
    });
  }

  renderStations(geoJsonData, activeBasin = 'all', currentLang = 'en') {
    if (!this.markersLayer) return;
    this.markersLayer.clearLayers();
    this.features = geoJsonData?.features || [];

    const bounds = [];

    this.features.forEach((feature) => {
      const props = feature.properties || {};
      const geom = feature.geometry || {};
      const [lon, lat] = geom.coordinates || [0, 0];

      // Basin filter
      if (activeBasin !== 'all' && props.basin !== activeBasin) {
        return;
      }

      bounds.push([lat, lon]);

      const levelKey = (props.alert_level || 'normal').toLowerCase();
      const cfg = RISK_CONFIG[levelKey] || RISK_CONFIG.normal;
      const levelLabel = currentLang === 'hi' ? cfg.labelHi : cfg.labelEn;

      const icon = this.createStationIcon(props.alert_level);
      const marker = L.marker([lat, lon], {
        icon,
        title: `${props.station_name} (${levelLabel})`,
        alt: `${props.station_name} Risk: ${levelLabel}`,
      });

      // Accessible popup tooltip
      const popupHtml = `
        <div style="font-family: sans-serif; font-size: 12px; color: #111;">
          <strong style="font-size: 13px;">${props.station_name}</strong><br/>
          <span>Basin: ${props.basin} &bull; River: ${props.river}</span><br/>
          <span style="font-weight: bold; color: ${cfg.color};">
            ${cfg.symbol} ${levelLabel}
          </span> &bull; 
          <span>Flow: ${props.current_discharge?.toFixed(1) ?? '--'} m³/s</span>
        </div>
      `;
      marker.bindPopup(popupHtml);

      // Station click interaction
      marker.on('click', () => {
        if (this.onStationSelect) {
          this.onStationSelect(props.station_id);
        }
      });

      this.markersLayer.addLayer(marker);
    });

    if (bounds.length > 0 && activeBasin !== 'all') {
      this.map.fitBounds(bounds, { padding: [40, 40], maxZoom: 10 });
    }
  }

  highlightStation(stationId) {
    this.activeStationId = stationId;
    const target = this.features.find((f) => f.properties?.station_id === stationId);
    if (target && target.geometry?.coordinates) {
      const [lon, lat] = target.geometry.coordinates;
      this.map.panTo([lat, lon], { animate: true, duration: 0.5 });
    }
  }
}
