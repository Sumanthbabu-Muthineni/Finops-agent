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
            {auditTrail.index_status && (
              <div className="meta-item">
                <span>🔍 Indexing:</span>
                {auditTrail.index_status === 'OPTIMAL_INDEX_HIT' ? (
                  <span style={{ color: '#10b981', fontWeight: 600 }}>⚡ B-Tree Indexed</span>
                ) : (
                  <span style={{ color: '#f59e0b', fontWeight: 600 }}>⚠️ Unindexed Scan</span>
                )}
              </div>
            )}
          </div>

          {auditTrail.advisories && auditTrail.advisories.length > 0 && (
            <div style={{
              background: 'rgba(245, 158, 11, 0.08)',
              border: '1px solid rgba(245, 158, 11, 0.25)',
              borderRadius: 8,
              padding: '10px 14px',
              marginBottom: 12
            }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: 6, color: '#f59e0b', fontSize: '0.8rem', fontWeight: 600, marginBottom: 4 }}>
                <span>💡 Proactive Index Optimization Advisory:</span>
              </div>
              <p style={{ margin: '0 0 6px 0', fontSize: '0.78rem', color: '#cbd5e1', lineHeight: '1.4' }}>
                This query executed a sequential scan because key filter columns lack B-Tree indexes. Adding this index on your database will accelerate future aggregations:
              </p>
              {auditTrail.advisories.map((adv, idx) => (
                <pre key={idx} className="sql-code-box" style={{ margin: '4px 0', background: 'rgba(0,0,0,0.5)', fontSize: '0.75rem' }}>
                  <code>{typeof adv === 'object' ? (adv.advisory || adv.suggested_sql || JSON.stringify(adv)) : adv}</code>
                </pre>
              ))}
            </div>
          )}

          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 6 }}>
            <span style={{ fontSize: '0.75rem', color: '#94a3b8' }}>MySQL ANSI-SQL Query:</span>
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
