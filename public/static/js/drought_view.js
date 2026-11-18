/**
 * HydroPulse AI — Drought & Low-Flow View Module
 * Renders compound drought severity, multi-scalar SPI bars, Q90 low-flow stress,
 * and 30-day forward drought outlook trajectories.
 */

export class DroughtView {
  static render(droughtData, currentLang = 'en') {
    if (!droughtData) return;

    // 1. Compound Severity Pill & Summary
    const severityPill = document.getElementById('drought-severity-badge');
    const summaryDesc = document.getElementById('drought-summary-desc');
    const severity = (droughtData.severity_category || 'Normal').toUpperCase();

    if (severityPill) {
      severityPill.textContent = severity;
      if (severity === 'NORMAL') {
        severityPill.style.background = 'rgba(235, 252, 114, 0.12)';
        severityPill.style.color = '#ebfc72';
        severityPill.style.border = '1px solid #ebfc72';
      } else if (severity === 'WATCH') {
        severityPill.style.background = 'rgba(245, 158, 11, 0.15)';
        severityPill.style.color = '#f59e0b';
        severityPill.style.border = '1px solid #f59e0b';
      } else if (severity === 'MODERATE') {
        severityPill.style.background = 'rgba(244, 63, 94, 0.15)';
        severityPill.style.color = '#f43f5e';
        severityPill.style.border = '1px solid #f43f5e';
      } else {
        // Severe / Extreme
        severityPill.style.background = 'rgba(239, 68, 68, 0.18)';
        severityPill.style.color = '#ef4444';
        severityPill.style.border = '1px solid #ef4444';
      }
    }

    if (summaryDesc) {
      if (severity === 'NORMAL') {
        summaryDesc.textContent = 'Precipitation accumulations and river baseflow are tracking seasonal normals.';
      } else if (droughtData.is_low_flow_stress) {
        summaryDesc.textContent = 'Hydrological low-flow deficit active: river discharge is currently below the historical Q90 baseflow threshold.';
      } else {
        summaryDesc.textContent = `Meteorological moisture deficit active with ${severity.toLowerCase()} precipitation anomaly.`;
      }
    }

    // 2. SPI Multi-Scalar Bars
    // Maps SPI value (-3.0 to +3.0) to percentage width (0% to 100%)
    const normalizeSpiPercent = (val) => {
      if (val === null || val === undefined) return 50;
      const clamped = Math.max(-3.0, Math.min(3.0, val));
      return ((clamped + 3.0) / 6.0) * 100;
    };

    const updateSpiRow = (fillId, valId, spiVal) => {
      const fillEl = document.getElementById(fillId);
      const valEl = document.getElementById(valId);
      if (valEl) {
        valEl.textContent = typeof spiVal === 'number' ? (spiVal > 0 ? `+${spiVal.toFixed(2)}` : spiVal.toFixed(2)) : '--';
      }
      if (fillEl) {
        const pct = normalizeSpiPercent(spiVal);
        fillEl.style.width = `${pct}%`;
        if (typeof spiVal === 'number' && spiVal <= -1.5) {
          fillEl.style.background = '#ef4444'; // Severe
        } else if (typeof spiVal === 'number' && spiVal <= -1.0) {
          fillEl.style.background = '#f59e0b'; // Moderate
        } else {
          fillEl.style.background = '#ebfc72'; // Normal/Wet (Lime Surveyor)
        }
      }
    };

    updateSpiRow('spi-1-fill', 'spi-1-val', droughtData.spi_1);
    updateSpiRow('spi-3-fill', 'spi-3-val', droughtData.spi_3);
    updateSpiRow('spi-6-fill', 'spi-6-val', droughtData.spi_6);

    // 3. Hydrological Low-Flow Q90 Status
    const q90Badge = document.getElementById('q90-status-badge');
    const currQ = document.getElementById('q90-current-discharge');
    const threshQ = document.getElementById('q90-threshold-val');

    if (q90Badge) {
      if (droughtData.is_low_flow_stress) {
        q90Badge.textContent = 'LOW-FLOW DEFICIT';
        q90Badge.style.background = 'rgba(239, 68, 68, 0.15)';
        q90Badge.style.color = '#ef4444';
        q90Badge.style.border = '1px solid #ef4444';
      } else {
        q90Badge.textContent = 'ADEQUATE BASEFLOW';
        q90Badge.style.background = 'rgba(235, 252, 114, 0.12)';
        q90Badge.style.color = '#ebfc72';
        q90Badge.style.border = '1px solid #ebfc72';
      }
    }

    if (currQ) {
      currQ.textContent = typeof droughtData.current_discharge === 'number' ? `${droughtData.current_discharge.toFixed(1)} m³/s` : '-- m³/s';
    }
    if (threshQ) {
      threshQ.textContent = typeof droughtData.low_flow_threshold_q90 === 'number' ? `${droughtData.low_flow_threshold_q90.toFixed(1)} m³/s` : '-- m³/s';
    }

    // 4. 30-Day Outlook Trajectory
    const outlookBadge = document.getElementById('drought-outlook-badge');
    const outlookArrow = document.getElementById('drought-outlook-arrow');
    const outlookNarrative = document.getElementById('drought-outlook-narrative');
    const trajectory = (droughtData.drought_outlook_30d || 'Persistent').toUpperCase();

    if (outlookBadge) {
      outlookBadge.textContent = trajectory;
    }

    if (outlookArrow) {
      if (trajectory === 'IMPROVING') {
        outlookArrow.textContent = '↗';
        outlookArrow.style.color = '#10b981';
      } else if (trajectory === 'DETERIORATING') {
        outlookArrow.textContent = '↘';
        outlookArrow.style.color = '#f43f5e';
      } else {
        outlookArrow.textContent = '→';
        outlookArrow.style.color = '#38bdf8';
      }
    }

    if (outlookNarrative) {
      if (trajectory === 'IMPROVING') {
        outlookNarrative.textContent = 'Forecast rainfall accumulation and upstream inflows are expected to alleviate water stress over the next 30 days.';
      } else if (trajectory === 'DETERIORATING') {
        outlookNarrative.textContent = 'Low rainfall projections indicate intensifying hydrologic deficit; proactive reservoir conservation recommended.';
      } else {
        outlookNarrative.textContent = 'Precipitation outlook and hydrologic baseflow indicate persistence of current conditions.';
      }
    }
  }
}
