import React, { useState, useEffect, useRef } from 'react';
import { Send, PlusCircle, Database, Cpu, Sparkles } from 'lucide-react';
import { sendMessage, getHealth } from './services/api';
import { MessageBubble } from './components/MessageBubble';

const SAMPLE_QUESTIONS = [
  "What is our total available balance across all banks?",
  "How much was credited vs debited in June 2026?",
  "Show recent transactions for HDFC Bank",
  "Which accounts have a negative balance?",
  "Show transactions for Program 21",
  "Lookup transaction with reference ID 1715499972"
];

export default function App() {
  const [messages, setMessages] = useState([]);
  const [input, setInput] = useState('');
  const [loading, setLoading] = useState(false);
  const [sessionId, setSessionId] = useState(() => 'sess-' + Math.random().toString(36).substring(2, 9));
  const [health, setHealth] = useState(null);
  const messagesEndRef = useRef(null);

  // Load backend status on mount
  useEffect(() => {
    getHealth()
      .then(data => setHealth(data))
      .catch(err => console.error("Could not fetch health status:", err));
  }, []);

  // Auto-scroll to bottom on new message
  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages, loading]);

  const handleSend = async (textToSend) => {
    const query = (textToSend || input).trim();
    if (!query || loading) return;

    // Optimistically add user message
    const userMsg = { role: 'user', content: query };
    setMessages(prev => [...prev, userMsg]);
    setInput('');
    setLoading(true);

    try {
      const response = await sendMessage(query, sessionId);
      const assistantMsg = {
        role: 'assistant',
        narrative: response.narrative,
        confidence: response.confidence,
        anomaly: response.anomaly,
        summary_metrics: response.summary_metrics,
        table_data: response.table_data,
        audit_trail: response.audit_trail,
        clarification_options: response.clarification_options,
        status: response.status
      };
      setMessages(prev => [...prev, assistantMsg]);
    } catch (error) {
      console.error("API error:", error);
      const errorMsg = {
        role: 'assistant',
        narrative: "An error occurred while processing your request. Please ensure the backend server is running on port 8000.",
        confidence: { score: 0.0, tier: 'LOW', explanation: 'Network/Server Error' },
        anomaly: { detected: false },
        summary_metrics: [],
        table_data: [],
        audit_trail: { sql_query: 'N/A', execution_time_ms: 0, rows_scanned: 0, model_used: 'N/A' }
      };
      setMessages(prev => [...prev, errorMsg]);
    } finally {
      setLoading(false);
    }
  };

  const handleNewChat = () => {
    setMessages([]);
    setSessionId('sess-' + Math.random().toString(36).substring(2, 9));
  };

  return (
    <div className="app-container">
      {/* Top Navbar */}
      <header className="app-header">
        <div className="brand-section">
          <div className="brand-logo">
            <Database size={20} />
          </div>
          <div>
            <div className="brand-title">TBX FinOps Assistant</div>
            <div className="brand-subtitle">Grounded Connected Banking & Financial Operations</div>
          </div>
        </div>

        <div className="header-badges">
          <div className="status-badge" title="Underlying Relational Database">
            <span className="pulse-dot"></span>
            <span>PostgreSQL Active</span>
          </div>

          <div className="status-badge" title="Model Efficiency Rubric">
            <Cpu size={12} style={{ color: '#3b82f6' }} />
            <span>8B Model ({health?.llm_provider || 'bedrock'})</span>
          </div>

          <button onClick={handleNewChat} className="btn-secondary" title="Start a clean session">
            <PlusCircle size={14} />
            <span>New Session</span>
          </button>
        </div>
      </header>

      {/* Main Viewport */}
      <main className="chat-viewport">
        {messages.length === 0 ? (
          <div className="welcome-hero">
            <div style={{ display: 'inline-flex', padding: 8, borderRadius: 12, background: 'rgba(59, 130, 246, 0.1)', color: '#60a5fa', marginBottom: 12 }}>
              <Sparkles size={28} />
            </div>
            <h1>Ask Any Financial Operations Question</h1>
            <p>
              Grounded, zero-hallucination answers powered by PostgreSQL analytics, automated IQR outlier detection, and dynamic schema inspection.
            </p>

            <div className="sample-questions-grid">
              {SAMPLE_QUESTIONS.map((q, idx) => (
                <button
                  key={idx}
                  onClick={() => handleSend(q)}
                  className="pill-btn"
                >
                  {q}
                </button>
              ))}
            </div>
          </div>
        ) : (
          messages.map((msg, idx) => (
            <MessageBubble
              key={idx}
              message={msg}
              onOptionClick={opt => handleSend(opt)}
            />
          ))
        )}

        {loading && (
          <div className="message-wrapper assistant">
            <div className="avatar assistant">
              <Sparkles size={16} />
            </div>
            <div className="message-body">
              <div className="assistant-bubble" style={{ padding: '12px 18px' }}>
                <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
                  <span style={{ fontSize: '0.85rem', color: '#94a3b8' }}>
                    Compiling query & executing in PostgreSQL...
                  </span>
                  <div className="typing-indicator">
                    <div className="typing-dot"></div>
                    <div className="typing-dot"></div>
                    <div className="typing-dot"></div>
                  </div>
                </div>
              </div>
            </div>
          </div>
        )}

        <div ref={messagesEndRef} />
      </main>

      {/* Query Input Bar */}
      <div className="chat-input-container">
        <form
          onSubmit={(e) => {
            e.preventDefault();
            handleSend();
          }}
          className="chat-input-box"
        >
          <input
            type="text"
            className="chat-input"
            placeholder="Ask about spend, payouts, reconciliation, or vendors (e.g. 'How much did we spend on vendor payouts last month?')..."
            value={input}
            onChange={(e) => setInput(e.target.value)}
            disabled={loading}
          />
          <button
            type="submit"
            className="send-btn"
            disabled={loading || !input.trim()}
            title="Send query"
          >
            <Send size={16} />
          </button>
        </form>
      </div>
    </div>
  );
}
