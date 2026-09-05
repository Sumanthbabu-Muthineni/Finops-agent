import React from 'react';
import { AlertTriangle, Bot, User } from 'lucide-react';
import { KpiMetrics } from './KpiMetrics';
import { FinancialAgGrid } from './FinancialAgGrid';
import { AuditDrawer } from './AuditDrawer';
import { ConfidenceBadge } from './ConfidenceBadge';

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
    table_data,
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
            {narrative}
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
                    onClick={() => onOptionClick && onOptionClick(`Show spend for ${opt}`)}
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

          {/* Interactive AG Grid Table */}
          <FinancialAgGrid rowData={table_data} />

          {/* Expandable Audit Drawer */}
          <AuditDrawer auditTrail={audit_trail} confidence={confidence} />
        </div>
      </div>
    </div>
  );
};
