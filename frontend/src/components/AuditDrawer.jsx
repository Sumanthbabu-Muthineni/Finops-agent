import React, { useState } from 'react';
import { Terminal, ChevronDown, ChevronUp, Copy, Check } from 'lucide-react';

export const AuditDrawer = ({ auditTrail, confidence }) => {
  const [isOpen, setIsOpen] = useState(false);
  const [copied, setCopied] = useState(false);

  if (!auditTrail || !auditTrail.sql_query || auditTrail.sql_query === 'N/A') return null;

  const handleCopy = () => {
    navigator.clipboard.writeText(auditTrail.sql_query);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };

  return (
    <div className="audit-wrapper">
      <button 
        onClick={() => setIsOpen(!isOpen)} 
        className="audit-toggle-btn"
        aria-expanded={isOpen}
      >
        <Terminal size={14} />
        <span>{isOpen ? 'Hide SQL & Audit Trace' : 'View SQL & Audit Trace'}</span>
        {isOpen ? <ChevronUp size={14} /> : <ChevronDown size={14} />}
      </button>

      {isOpen && (
        <div className="audit-drawer-content">
          <div className="audit-meta-row">
            <div className="meta-item">
              <span>⚡ Latency:</span>
              <strong>{auditTrail.execution_time_ms} ms</strong>
            </div>
            <div className="meta-item">
              <span>📊 Records Scanned:</span>
              <strong>{auditTrail.rows_scanned}</strong>
            </div>
            <div className="meta-item">
              <span>🤖 Model:</span>
              <strong>{auditTrail.model_used}</strong>
            </div>
            {confidence && (
              <div className="meta-item">
                <span>🎯 Formula Score:</span>
                <strong>{Math.round(confidence.score * 100)}% ({confidence.tier})</strong>
              </div>
            )}
          </div>

          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 6 }}>
            <span style={{ fontSize: '0.75rem', color: '#94a3b8' }}>DuckDB ANSI-SQL Query:</span>
            <button 
              onClick={handleCopy} 
              style={{
                background: 'transparent',
                border: 'none',
                color: copied ? '#34d399' : '#94a3b8',
                fontSize: '0.75rem',
                cursor: 'pointer',
                display: 'flex',
                alignItems: 'center',
                gap: 4
              }}
            >
              {copied ? <Check size={12} /> : <Copy size={12} />}
              <span>{copied ? 'Copied' : 'Copy'}</span>
            </button>
          </div>

          <pre className="sql-code-box">
            <code>{auditTrail.sql_query}</code>
          </pre>
        </div>
      )}
    </div>
  );
};
