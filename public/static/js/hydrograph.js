/**
 * HydroPulse AI — Chart.js Hydrograph Module
 * Plots time-series river discharge combining 14-day historical observations,
 * 1–7 day forward P50 forecast, shaded P10–P90 quantile uncertainty band,
 * and horizontal warning/danger threshold lines.
 */

/* global Chart */

export class HydrographChart {
  constructor(canvasId) {
    this.canvasId = canvasId;
    this.chart = null;
  }

  destroy() {
    if (this.chart) {
      this.chart.destroy();
      this.chart = null;
    }
  }

  render(historyData, forecastData, thresholds) {
    const canvas = document.getElementById(this.canvasId);
    if (!canvas) return;
    const ctx = canvas.getContext('2d');

    this.destroy();

    const historyItems = historyData?.records || [];
    const forecastItems = forecastData?.forecast || [];

    // Construct unified date labels
    const labels = [];
    const obsValues = [];
    const p50Values = [];
    const p10Values = [];
    const p90Values = [];

    // History items (up to 14 days)
    historyItems.forEach((item) => {
      labels.push(item.date);
      obsValues.push(item.discharge);
      p50Values.push(null);
      p10Values.push(null);
      p90Values.push(null);
    });

    // Bridge last historical point to first forecast point for continuity
    if (historyItems.length > 0 && forecastItems.length > 0) {
      const lastObs = historyItems[historyItems.length - 1];
      p50Values[p50Values.length - 1] = lastObs.discharge;
      p10Values[p10Values.length - 1] = lastObs.discharge;
      p90Values[p90Values.length - 1] = lastObs.discharge;
    }

    // Forecast items
    forecastItems.forEach((f) => {
      labels.push(f.date);
      obsValues.push(null);
      p50Values.push(f.p50);
      p10Values.push(f.p10);
      p90Values.push(f.p90);
    });

    const warnThreshold = thresholds?.warning || null;
    const dangThreshold = thresholds?.danger || null;

    const datasets = [
      // Observed History Line
      {
        label: 'Observed / Reanalysis',
        data: obsValues,
        borderColor: '#84837b',
        backgroundColor: '#84837b',
        borderWidth: 1.8,
        pointRadius: 2,
        tension: 0.15,
      },
      // P50 Median Forecast Line (Lime Surveyor)
      {
        label: 'Forecast (P50)',
        data: p50Values,
        borderColor: '#ebfc72',
        backgroundColor: '#ebfc72',
        borderWidth: 2.2,
        pointRadius: 3,
        pointHoverRadius: 5,
        tension: 0.15,
      },
      // P90 Upper Bound (Fills down to P10)
      {
        label: 'P90 (Upper Bound)',
        data: p90Values,
        borderColor: 'rgba(235, 252, 114, 0.45)',
        borderWidth: 1,
        borderDash: [4, 4],
        pointRadius: 0,
        fill: '+1', // Fills to P10 dataset below
        backgroundColor: 'rgba(235, 252, 114, 0.12)',
        tension: 0.15,
      },
      // P10 Lower Bound
      {
        label: 'P10 (Lower Bound)',
        data: p10Values,
        borderColor: 'rgba(235, 252, 114, 0.45)',
        borderWidth: 1,
        borderDash: [4, 4],
        pointRadius: 0,
        fill: false,
        tension: 0.15,
      },
    ];

    // Add threshold horizontal lines
    if (warnThreshold) {
      datasets.push({
        label: `Warning Level (${warnThreshold} m³/s)`,
        data: labels.map(() => warnThreshold),
        borderColor: '#bacd31',
        borderWidth: 1.5,
        borderDash: [6, 4],
        pointRadius: 0,
        fill: false,
      });
    }

    if (dangThreshold) {
      datasets.push({
        label: `Danger Level (${dangThreshold} m³/s)`,
        data: labels.map(() => dangThreshold),
        borderColor: '#ef4444',
        borderWidth: 1.5,
        borderDash: [6, 4],
        pointRadius: 0,
        fill: false,
      });
    }

    this.chart = new Chart(ctx, {
      type: 'line',
      data: { labels, datasets },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        interaction: {
          mode: 'index',
          intersect: false,
        },
        plugins: {
          legend: { display: false },
          tooltip: {
            backgroundColor: 'rgba(19, 20, 14, 0.96)',
            borderColor: '#404040',
            borderWidth: 1,
            titleColor: '#f4f3e8',
            bodyColor: '#84837b',
            titleFont: { family: 'JetBrains Mono', size: 12 },
            bodyFont: { family: 'JetBrains Mono', size: 12 },
            callbacks: {
              label(context) {
                if (context.raw === null || context.raw === undefined) return null;
                const val = typeof context.raw === 'number' ? context.raw.toFixed(1) : context.raw;
                return ` ${context.dataset.label}: ${val} m³/s`;
              },
            },
          },
        },
        scales: {
          x: {
            grid: { color: 'rgba(64, 64, 64, 0.4)' },
            ticks: {
              color: '#84837b',
              font: { family: 'JetBrains Mono', size: 10 },
              maxRotation: 45,
            },
          },
          y: {
            title: {
              display: true,
              text: 'Discharge (m³/s)',
              color: '#84837b',
              font: { family: 'JetBrains Mono', size: 11 },
            },
            grid: { color: 'rgba(64, 64, 64, 0.4)' },
            ticks: {
              color: '#84837b',
              font: { family: 'JetBrains Mono', size: 10 },
            },
          },
        },
      },
    });
  }
}
