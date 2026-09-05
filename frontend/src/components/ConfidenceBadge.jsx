import React from 'react';

export const ConfidenceBadge = ({ confidence }) => {
  if (!confidence) return null;

  const scorePct = Math.round(confidence.score * 100);
  const tier = (confidence.tier || 'HIGH').toLowerCase();

  const tierColors = {
    high: '🟢',
    medium: '🟡',
    low: '🔴'
  };

  return (
    <span className={`confidence-pill ${tier}`} title={confidence.explanation}>
      <span>{tierColors[tier] || '🟢'}</span>
      <span>{scorePct}% Confidence ({confidence.tier})</span>
    </span>
  );
};
