/**
 * HydroPulse AI — River Health & Water Quality View Module
 * Renders Weighted-Arithmetic WQI, CPCB Designated-Best-Use classes,
 * individual pollutant parameters, and industrial hotspot warnings.
 */

const CPCB_DESCRIPTIONS = {
  A: 'Class A: Drinking Water Source without conventional treatment but after disinfection.',
  B: 'Class B: Outdoor bathing (Organised).',
  C: 'Class C: Drinking water source after conventional treatment and disinfection.',
  D: 'Class D: Propagation of Wild life and Fisheries.',
  E: 'Class E: Irrigation, Industrial Cooling, Controlled Waste disposal.',
  Below_E: 'Below Class E: Not suitable for designated best uses; heavily degraded.',
};

export class HealthView {
  static render(wqData, currentLang = 'en') {
    if (!wqData) return;

    // 1. WQI Score & Badge
    const scoreVal = document.getElementById('wqi-score-value');
    const statusBadge = document.getElementById('wqi-status-badge');
    const rawScore = wqData.wqi_score;

    if (scoreVal) {
      scoreVal.textContent = typeof rawScore === 'number' ? rawScore.toFixed(1) : '--';
    }

    if (statusBadge) {
      const category = wqData.wqi_category || 'Unknown';
      statusBadge.textContent = category.toUpperCase();

      if (rawScore <= 25) {
        statusBadge.style.background = 'rgba(235, 252, 114, 0.15)';
        statusBadge.style.color = '#ebfc72';
        statusBadge.style.border = '1px solid #ebfc72';
      } else if (rawScore <= 50) {
        statusBadge.style.background = 'rgba(186, 205, 49, 0.15)';
        statusBadge.style.color = '#bacd31';
        statusBadge.style.border = '1px solid #bacd31';
      } else if (rawScore <= 75) {
        statusBadge.style.background = 'rgba(245, 158, 11, 0.15)';
        statusBadge.style.color = '#f59e0b';
        statusBadge.style.border = '1px solid #f59e0b';
      } else {
        statusBadge.style.background = 'rgba(239, 68, 68, 0.15)';
        statusBadge.style.color = '#ef4444';
        statusBadge.style.border = '1px solid #ef4444';
      }
    }

    // 2. CPCB Class Letter & Description
    const classLetter = document.getElementById('cpcb-class-letter');
    const classDesc = document.getElementById('cpcb-class-desc');
    const cpcbClass = wqData.cpcb_class || 'C';

    if (classLetter) {
      classLetter.textContent = cpcbClass.replace('_', ' ');
    }
    if (classDesc) {
      classDesc.textContent = CPCB_DESCRIPTIONS[cpcbClass] || 'Criteria evaluated per CPCB statutory rules.';
    }

    // 3. Industrial Corridor Hotspot Alert
    const hotspotBanner = document.getElementById('hotspot-alert-banner');
    const hotspotReason = document.getElementById('hotspot-alert-reason');

    if (hotspotBanner) {
      if (wqData.is_industrial_hotspot) {
        hotspotBanner.hidden = false;
        if (hotspotReason) {
          hotspotReason.textContent = wqData.hotspot_reason || 'Severe organic or chemical effluent exceedance in industrial corridor.';
        }
      } else {
        hotspotBanner.hidden = true;
      }
    }

    // 4. Parameter Grid
    const params = wqData.parameters || {};
    const setParam = (id, val, unit = '') => {
      const el = document.getElementById(id);
      if (el) {
        el.textContent = typeof val === 'number' ? `${val.toFixed(1)}${unit ? ' ' + unit : ''}` : '--';
      }
    };

    setParam('wq-param-ph', params.ph);
    setParam('wq-param-do', params.dissolved_oxygen, 'mg/L');
    setParam('wq-param-bod', params.bod, 'mg/L');
    setParam('wq-param-cod', params.cod, 'mg/L');
    setParam('wq-param-cond', params.conductivity, 'µS/cm');
    setParam('wq-param-turb', params.turbidity, 'NTU');
  }
}
