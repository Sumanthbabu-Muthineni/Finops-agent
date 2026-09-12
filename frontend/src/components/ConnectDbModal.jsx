import React, { useState, useEffect } from 'react';
import { 
  Database, X, ShieldCheck, Check, Copy, AlertTriangle, 
  RefreshCw, Server, ArrowRight, Zap, Lock, HardDrive, CheckCircle2, ChevronRight
} from 'lucide-react';
import { connectDatabase, disconnectDatabase, getDbStatus, getDbAdvisor } from '../services/api';

export const ConnectDbModal = ({ isOpen, onClose, sessionId, onDatabaseConnected, onDatabaseDisconnected }) => {
  const [formData, setFormData] = useState({
    host: '',
    port: 3306,
    database: '',
    username: '',
    password: '',
    ssl: false
  });

  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);
  const [activeConnection, setActiveConnection] = useState(null);
  const [advisorReport, setAdvisorReport] = useState(null);
  const [copiedIndex, setCopiedIndex] = useState(null);
  const [copiedAll, setCopiedAll] = useState(false);

  // Check current DB status when modal opens
  useEffect(() => {
    if (isOpen && sessionId) {
      setError(null);
      getDbStatus(sessionId)
        .then(data => {
          if (data && data.is_custom) {
            setActiveConnection(data);
            return getDbAdvisor(sessionId);
          } else {
            setActiveConnection(null);
            setAdvisorReport(null);
          }
        })
        .then(adv => {
          if (adv && adv.report) {
            setAdvisorReport(adv.report);
          }
        })
        .catch(err => console.error("Error fetching DB status:", err));
    }
  }, [isOpen, sessionId]);

  if (!isOpen) return null;

  const handleChange = (e) => {
    const { name, value, type, checked } = e.target;
    setFormData(prev => ({
      ...prev,
      [name]: type === 'checkbox' ? checked : value
    }));
  };

  const handleConnect = async (e) => {
    e.preventDefault();
    setError(null);
    setLoading(true);

    try {
      const res = await connectDatabase(formData, sessionId);
      setActiveConnection({
        is_custom: true,
        info: {
          database: res.database,
          host: res.host,
          port: res.port
        },
        tables_count: res.tables_count,
        tables: res.tables
      });
      setAdvisorReport(res.advisor_report);
      if (onDatabaseConnected) {
        onDatabaseConnected(res);
      }
    } catch (err) {
      console.error("Connection failed:", err);
      const msg = err.response?.data?.detail || err.message || "Failed to establish database connection.";
      setError(msg);
    } finally {
      setLoading(false);
    }
  };

  const handleDisconnect = async () => {
    setLoading(true);
    setError(null);
    try {
      await disconnectDatabase(sessionId);
      setActiveConnection(null);
      setAdvisorReport(null);
      if (onDatabaseDisconnected) {
        onDatabaseDisconnected();
      }
    } catch (err) {
      console.error("Disconnect failed:", err);
      setError("Failed to disconnect from database.");
    } finally {
      setLoading(false);
    }
  };

  const copyToClipboard = (text, idx) => {
    navigator.clipboard.writeText(text);
    setCopiedIndex(idx);
    setTimeout(() => setCopiedIndex(null), 2000);
  };

  const copyAllDdl = () => {
    if (!advisorReport?.recommendations?.length) return;
    const allDdl = advisorReport.recommendations.map(r => r.suggested_ddl).join('\n\n');
    navigator.clipboard.writeText(allDdl);
    setCopiedAll(true);
    setTimeout(() => setCopiedAll(false), 2500);
  };

  return (
    <div className="modal-overlay" onClick={onClose}>
      <div className="modal-card" onClick={e => e.stopPropagation()}>
        {/* Header */}
        <div className="modal-header">
          <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
            <div className="modal-icon-badge">
              <Database size={20} color="#3b82f6" />
            </div>
            <div>
              <h2 className="modal-title">Connect Your Relational Database</h2>
              <p className="modal-subtitle">Enterprise zero-DDL read-only query engine & performance advisor</p>
            </div>
          </div>
          <button className="modal-close-btn" onClick={onClose} aria-label="Close modal">
            <X size={18} />
          </button>
        </div>

        {/* Security & Zero-DDL Guarantee Banner */}
        <div className="security-banner">
          <ShieldCheck size={18} color="#10b981" style={{ flexShrink: 0, marginTop: 2 }} />
          <div style={{ fontSize: '0.8rem', lineHeight: '1.4' }}>
            <strong style={{ color: '#10b981' }}>Zero-DDL Protection:</strong> All external queries execute under strict <code style={{ color: '#38bdf8' }}>SET SESSION TRANSACTION READ ONLY</code>. The agent will <strong>never</strong> create, modify, or drop tables or views on your database.
          </div>
        </div>

        {/* Modal Body: Either Connected Overview or Connection Form */}
        <div className="modal-body">
          {error && (
            <div className="error-callout">
              <AlertTriangle size={18} color="#ef4444" style={{ flexShrink: 0 }} />
              <div>
                <div style={{ fontWeight: 600, color: '#ef4444', marginBottom: 4 }}>Connection Failed</div>
                <div style={{ fontSize: '0.82rem', color: '#fca5a5' }}>{error}</div>
                <div style={{ fontSize: '0.75rem', color: '#cbd5e1', marginTop: 6, lineHeight: '1.4' }}>
                  💡 <em>Check host firewall/security groups to allow inbound port 3306, and ensure your user has SELECT privileges.</em>
                </div>
              </div>
            </div>
          )}

          {activeConnection && activeConnection.is_custom ? (
            /* Connected State View */
            <div className="connected-view">
              <div className="connection-status-card">
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start' }}>
                  <div style={{ display: 'flex', gap: 12, alignItems: 'center' }}>
                    <div className="connected-pulse-dot"></div>
                    <div>
                      <span className="connected-tag">Active Custom Database</span>
                      <h3 style={{ margin: '4px 0 2px 0', fontSize: '1.1rem', color: '#f8fafc' }}>
                        {activeConnection.info?.database}
                      </h3>
                      <span style={{ fontSize: '0.78rem', color: '#94a3b8' }}>
                        {activeConnection.info?.host}:{activeConnection.info?.port}
                      </span>
                    </div>
                  </div>
                  <button 
                    onClick={handleDisconnect} 
                    disabled={loading}
                    className="disconnect-btn"
                  >
                    {loading ? <RefreshCw size={12} className="spin" /> : null}
                    Disconnect & Revert to Demo DB
                  </button>
                </div>

                <div className="db-stats-row">
                  <div className="stat-pill">
                    <span className="stat-pill-label">Discovered Tables</span>
                    <strong className="stat-pill-val">{activeConnection.tables_count || 0}</strong>
                  </div>
                  <div className="stat-pill">
                    <span className="stat-pill-label">Permission</span>
                    <strong className="stat-pill-val" style={{ color: '#10b981' }}>READ ONLY</strong>
                  </div>
                  <div className="stat-pill">
                    <span className="stat-pill-label">Introspection</span>
                    <strong className="stat-pill-val" style={{ color: '#38bdf8' }}>Complete</strong>
                  </div>
                </div>
              </div>

              {/* Proactive Performance Advisor Section */}
              <div className="advisor-section">
                <div className="advisor-header">
                  <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                    <Zap size={16} color="#f59e0b" />
                    <h4 style={{ margin: 0, fontSize: '0.92rem', color: '#f8fafc' }}>
                      Zero-DDL Proactive Index Recommendations
                    </h4>
                  </div>
                  {advisorReport?.recommendations?.length > 0 && (
                    <button onClick={copyAllDdl} className="copy-all-btn">
                      {copiedAll ? <Check size={12} color="#10b981" /> : <Copy size={12} />}
                      <span>{copiedAll ? 'All DDL Copied!' : 'Copy All SQL'}</span>
                    </button>
                  )}
                </div>

                <p className="advisor-lead">
                  {advisorReport?.lead_summary || 
                    "To ensure sub-100ms analytics latency, our engine scanned your tables and identified columns that would benefit from indexing:"}
                </p>

                {advisorReport?.recommendations?.length > 0 ? (
                  <div className="recommendations-list">
                    {advisorReport.recommendations.map((rec, idx) => (
                      <div key={idx} className="rec-card">
                        <div className="rec-top">
                          <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
                            <span className="table-badge">{rec.table}.{rec.column}</span>
                            <span className={`priority-badge priority-${rec.priority.toLowerCase()}`}>
                              {rec.priority} Priority
                            </span>
                          </div>
                          <button 
                            onClick={() => copyToClipboard(rec.suggested_ddl, idx)} 
                            className="copy-sql-btn"
                            title="Copy CREATE INDEX statement"
                          >
                            {copiedIndex === idx ? (
                              <>
                                <Check size={12} color="#10b981" />
                                <span style={{ color: '#10b981' }}>Copied</span>
                              </>
                            ) : (
                              <>
                                <Copy size={12} />
                                <span>Copy SQL</span>
                              </>
                            )}
                          </button>
                        </div>
                        <p className="rec-reason">{rec.reason}</p>
                        <pre className="sql-snippet-box">
                          <code>{rec.suggested_ddl}</code>
                        </pre>
                      </div>
                    ))}
                  </div>
                ) : (
                  <div className="optimal-indexes-box">
                    <CheckCircle2 size={18} color="#10b981" />
                    <span>Your database indexes are already fully optimized for financial queries!</span>
                  </div>
                )}
              </div>

              <div style={{ display: 'flex', justifyContent: 'flex-end', marginTop: 16 }}>
                <button onClick={onClose} className="primary-action-btn">
                  Start Querying {activeConnection.info?.database}
                  <ChevronRight size={16} />
                </button>
              </div>
            </div>
          ) : (
            /* Connection Form View */
            <form onSubmit={handleConnect} className="connect-form">
              <div className="form-grid">
                <div className="form-group" style={{ gridColumn: 'span 2' }}>
                  <label className="form-label">Database Host / Endpoint *</label>
                  <div className="input-with-icon">
                    <Server size={14} className="input-icon" />
                    <input
                      type="text"
                      name="host"
                      required
                      placeholder="e.g. database-prod.cxxxx.rds.amazonaws.com or 127.0.0.1"
                      value={formData.host}
                      onChange={handleChange}
                      className="form-input"
                    />
                  </div>
                </div>

                <div className="form-group">
                  <label className="form-label">Port *</label>
                  <input
                    type="number"
                    name="port"
                    required
                    value={formData.port}
                    onChange={handleChange}
                    className="form-input"
                  />
                </div>

                <div className="form-group">
                  <label className="form-label">Database Name *</label>
                  <div className="input-with-icon">
                    <HardDrive size={14} className="input-icon" />
                    <input
                      type="text"
                      name="database"
                      required
                      placeholder="e.g. finops_data"
                      value={formData.database}
                      onChange={handleChange}
                      className="form-input"
                    />
                  </div>
                </div>

                <div className="form-group">
                  <label className="form-label">Username (Read-Only Recommended) *</label>
                  <input
                    type="text"
                    name="username"
                    required
                    placeholder="e.g. finops_ro_user"
                    value={formData.username}
                    onChange={handleChange}
                    className="form-input"
                  />
                </div>

                <div className="form-group">
                  <label className="form-label">Password *</label>
                  <div className="input-with-icon">
                    <Lock size={14} className="input-icon" />
                    <input
                      type="password"
                      name="password"
                      placeholder="••••••••••••"
                      value={formData.password}
                      onChange={handleChange}
                      className="form-input"
                    />
                  </div>
                </div>
              </div>

              <div className="ssl-toggle-row">
                <label className="checkbox-container">
                  <input
                    type="checkbox"
                    name="ssl"
                    checked={formData.ssl}
                    onChange={handleChange}
                  />
                  <span className="checkbox-label">Require SSL / TLS Encrypted Connection (AWS RDS / Cloud DBs)</span>
                </label>
              </div>

              <div className="modal-actions">
                <button type="button" onClick={onClose} className="cancel-btn">
                  Cancel
                </button>
                <button type="submit" disabled={loading} className="submit-connect-btn">
                  {loading ? (
                    <>
                      <RefreshCw size={14} className="spin" />
                      <span>Introspecting & Connecting...</span>
                    </>
                  ) : (
                    <>
                      <Zap size={14} />
                      <span>Test & Connect Database</span>
                    </>
                  )}
                </button>
              </div>
            </form>
          )}
        </div>
      </div>
    </div>
  );
};
