import React from 'react';

export const KpiMetrics = ({ metrics }) => {
  if (!metrics || metrics.length === 0) return null;

  return (
    <div className="kpi-grid">
      {metrics.map((m, idx) => (
        <div key={idx} className="kpi-card">
          <span className="kpi-label">{m.label}</span>
          <span className="kpi-value">{m.value}</span>
        </div>
      ))}
    </div>
  );
};
