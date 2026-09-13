import React, { useState, useMemo } from 'react';
import { AlertTriangle, Bot, User, Table, ChevronDown, ChevronUp } from 'lucide-react';
import { KpiMetrics } from './KpiMetrics';
import { AuditDrawer } from './AuditDrawer';
import { ConfidenceBadge } from './ConfidenceBadge';
import { FinancialAgGrid, prepareExportData } from './FinancialAgGrid';
import { CsvExportButton } from './CsvExportButton';

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
  const [showTable, setShowTable] = useState(false);

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
    clarification_options,
    table_data
  } = message;

  const hasRecords = Array.isArray(table_data) && table_data.length > 0;
  const exportData = useMemo(() => prepareExportData(table_data), [table_data]);

  // Safety limits on export: do not allow exporting unbounded full-database scans
  const totalScanned = audit_trail?.rows_scanned || (hasRecords ? table_data.length : 0);
  const isAllScan = totalScanned > 500;
  const canExport = hasRecords && !isAllScan && table_data.length <= 100;
  const isCapped = totalScanned > 100 && table_data.length === 100;

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

          {/* Collapsible Records Table & 1-Click CSV Export */}
          {hasRecords && (
            <div className="table-toggle-wrapper" style={{ marginTop: 14 }}>
              <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', flexWrap: 'wrap', gap: 8 }}>
                <button
                  onClick={() => setShowTable(prev => !prev)}
                  className="btn-table-toggle"
                  style={{
                    display: 'inline-flex',
                    alignItems: 'center',
                    gap: 6,
                    background: showTable ? 'rgba(59, 130, 246, 0.18)' : 'rgba(30, 41, 59, 0.65)',
                    border: `1px solid ${showTable ? 'rgba(59, 130, 246, 0.5)' : 'rgba(71, 85, 105, 0.4)'}`,
                    color: showTable ? '#60a5fa' : '#cbd5e1',
                    padding: '6px 12px',
                    borderRadius: 6,
                    fontSize: '0.78rem',
                    fontWeight: 600,
                    cursor: 'pointer',
                    transition: 'all 0.15s ease'
                  }}
                  title={showTable ? "Click to collapse AG Grid" : "Click to view interactive data grid"}
                >
                  <Table size={14} />
                  <span>{showTable ? 'Hide Records Table' : `View Records Table (${table_data.length} ${table_data.length === 1 ? 'item' : 'items'})`}</span>
                  {showTable ? <ChevronUp size={14} /> : <ChevronDown size={14} />}
                </button>

                {canExport ? (
                  <CsvExportButton
                    data={exportData}
                    filename="financial_records.csv"
                    label={isCapped ? `Export CSV (Top ${table_data.length})` : "Export CSV"}
                  />
                ) : isAllScan ? (
                  <span style={{ fontSize: '0.74rem', color: '#94a3b8', background: 'rgba(148, 163, 184, 0.08)', padding: '3px 8px', borderRadius: 4 }}>
                    CSV export restricted for full-database queries
                  </span>
                ) : null}
              </div>

              {showTable && (
                <div style={{ marginTop: 10 }}>
                  <FinancialAgGrid
                    rowData={table_data}
                    totalRowsScanned={audit_trail?.rows_scanned}
                  />
                </div>
              )}
            </div>
          )}

          {/* Expandable Audit Drawer */}
          <AuditDrawer auditTrail={audit_trail} confidence={confidence} />
        </div>
      </div>
    </div>
  );
};
