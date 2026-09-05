import React from 'react';
import { AlertTriangle, Bot, User } from 'lucide-react';
import { KpiMetrics } from './KpiMetrics';
import { AuditDrawer } from './AuditDrawer';
import { ConfidenceBadge } from './ConfidenceBadge';

const renderNarrative = (text) => {
  if (!text) return null;

  const lines = text.split('\n');
  const elements = [];
  let currentList = [];

  const formatInline = (str) => {
    const parts = str.split(/(\*\*.*?\*\*)/g);
    return parts.map((part, index) => {
      if (part.startsWith('**') && part.endsWith('**')) {
        return (
          <strong key={index} style={{ color: '#f8fafc', fontWeight: 600 }}>
            {part.slice(2, -2)}
          </strong>
        );
      }
      return part;
    });
  };

  lines.forEach((line, lineIdx) => {
    const trimmed = line.trim();
    if (!trimmed) {
      if (currentList.length > 0) {
        elements.push(
          <ul key={`ul-${lineIdx}`} style={{ margin: '8px 0', paddingLeft: '20px', display: 'flex', flexDirection: 'column', gap: '4px' }}>
            {currentList}
          </ul>
        );
        currentList = [];
      }
      return;
    }

    if (trimmed.startsWith('•') || trimmed.startsWith('-') || trimmed.startsWith('*')) {
      const content = trimmed.replace(/^[•\-\*]\s*/, '');
      currentList.push(
        <li key={`li-${lineIdx}`} style={{ color: '#cbd5e1', lineHeight: '1.5' }}>
          {formatInline(content)}
        </li>
      );
    } else {
      if (currentList.length > 0) {
        elements.push(
          <ul key={`ul-${lineIdx}`} style={{ margin: '8px 0', paddingLeft: '20px', display: 'flex', flexDirection: 'column', gap: '4px' }}>
            {currentList}
          </ul>
        );
        currentList = [];
      }
      elements.push(
        <p key={`p-${lineIdx}`} style={{ margin: '4px 0', color: '#e2e8f0', lineHeight: '1.6' }}>
          {formatInline(trimmed)}
        </p>
      );
    }
  });

  if (currentList.length > 0) {
    elements.push(
      <ul key="ul-last" style={{ margin: '8px 0', paddingLeft: '20px', display: 'flex', flexDirection: 'column', gap: '4px' }}>
        {currentList}
      </ul>
    );
  }

  return elements;
};

export const MessageBubble = ({ message, onOptionClick }) => {
  const isUser = message.role === 'user';

  if (isUser) {
    return (
      <div className="message-wrapper user">
        <div className="avatar user">
          <User size={16} />
        </div>
        <div className="message-body">
          <div className="user-bubble">
            {message.content}
          </div>
        </div>
      </div>
    );
  }

  const {
    narrative,
    confidence,
    anomaly,
    summary_metrics,
    audit_trail,
    clarification_options
  } = message;

  return (
    <div className="message-wrapper assistant">
      <div className="avatar assistant">
        <Bot size={16} />
      </div>
      <div className="message-body">
        <div className="assistant-bubble">
          {/* Header row with Confidence Badge */}
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 12 }}>
            <span style={{ fontSize: '0.78rem', color: '#94a3b8', fontWeight: 600 }}>FinOps Assistant</span>
            <ConfidenceBadge confidence={confidence} />
          </div>

          {/* Anomaly Callout Banner */}
          {anomaly && anomaly.detected && (
            <div className="anomaly-alert">
              <AlertTriangle className="alert-icon" size={20} />
              <div>
                <strong>Statistical Anomaly Detected:</strong> {anomaly.message}
              </div>
            </div>
          )}

          {/* Plain English Narrative */}
          <div className="narrative-text">
            {renderNarrative(narrative)}
          </div>

          {/* Clarification Suggestion Pills if prompted */}
          {clarification_options && clarification_options.length > 0 && (
            <div style={{ margin: '10px 0' }}>
              <span style={{ fontSize: '0.8rem', color: '#94a3b8', display: 'block', marginBottom: 6 }}>
                Did you mean one of these vendors?
              </span>
              <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6 }}>
                {clarification_options.map((opt, i) => (
                  <button
                    key={i}
                    onClick={() => onOptionClick && onOptionClick(opt)}
                    className="pill-btn"
                    style={{ padding: '4px 10px', fontSize: '0.75rem' }}
                  >
                    {opt}
                  </button>
                ))}
              </div>
            </div>
          )}

          {/* KPI Summary Cards */}
          <KpiMetrics metrics={summary_metrics} />

          {/* Expandable Audit Drawer */}
          <AuditDrawer auditTrail={audit_trail} confidence={confidence} />
        </div>
      </div>
    </div>
  );
};
