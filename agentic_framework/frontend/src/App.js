import React, { useState, useEffect, useRef } from 'react';
import './App.css';

const API_URL = process.env.REACT_APP_API_URL || 'https://orchestrator.calmpebble-eb198128.westus2.azurecontainerapps.io';

// Hardcoded Azure AD token for demo purposes (Cognitive Services resource)
const AZURE_TOKEN = "eyJ0eXAiOiJKV1QiLCJhbGciOiJSUzI1NiIsIng1dCI6IkhTMjNiN0RvN1RjYVUxUm9MSHdwSXEyNFZZZyIsImtpZCI6IkhTMjNiN0RvN1RjYVUxUm9MSHdwSXEyNFZZZyJ9.eyJhdWQiOiJodHRwczovL2NvZ25pdGl2ZXNlcnZpY2VzLmF6dXJlLmNvbSIsImlzcyI6Imh0dHBzOi8vc3RzLndpbmRvd3MubmV0Lzc0Yzc3YmU2LTFhZDMtNDk1Ny1hNGYyLTk0MDI4MzcyZDdkNi8iLCJpYXQiOjE3NTk1MjE2MzAsIm5iZiI6MTc1OTUyMTYzMCwiZXhwIjoxNzU5NTI3MDIyLCJhY3IiOiIxIiwiYWlvIjoiQVhRQWkvOGFBQUFBMndrSTZzNEZoYmJCZU5NVGtueFJjdUJIY1Q3SGd6TTJ0ZHFRTzhYRFpjdStiSXN2SitSUldvaFU0aHJjc05OMmtVL2tGTUw0UC9XUkptbCtHQm5DbTIzMVNIeWJUMG1DanhidnhPT3Rubk5ReTdoMmZsYjFZNmdnSG1sYlN0WXlwZzdIRTMyd1k1VTBOK01PWmJDd09RPT0iLCJhbXIiOlsicHdkIiwibWZhIl0sImFwcGlkIjoiMDRiMDc3OTUtOGRkYi00NjFhLWJiZWUtMDJmOWUxYmY3YjQ2IiwiYXBwaWRhY3IiOiIwIiwiZmFtaWx5X25hbWUiOiJBLiIsImdpdmVuX25hbWUiOiJFbWlsaW8iLCJncm91cHMiOlsiMWZjMDRkOTgtZDM1ZS00YTM0LThmOGYtZGFmNmQzZWFkMzQxIl0sImlkdHlwIjoidXNlciIsImlwYWRkciI6IjIwOC45OC4yMjIuOTEiLCJuYW1lIjoiRW1pbGlvIEEuIiwib2lkIjoiZjk2ZThhNDItZjYyZS00MDY0LTg4OTctMWUxMmNhNmUyNTBhIiwicHVpZCI6IjEwMDMyMDAzMkM2MjlBQzUiLCJwd2RfZXhwIjoiMzEzNTc4OTU4IiwicHdkX3VybCI6Imh0dHBzOi8vcHJvZHVjdGl2aXR5LnNlY3VyZXNlcnZlci5uZXQvbWljcm9zb2Z0P21hcmtldGlkPWVuLVVTJmVtYWlsPWNvbnRhY3QlNDBnZW5lcmFpLmNhJnNvdXJjZT1WaWV3VXNlcnMmYWN0aW9uPVJlc2V0UGFzc3dvcmQiLCJyaCI6IjEuQVZFQTVudkhkTk1hVjBtazhwUUNnM0xYMXBBaU1YM0lLRHhIb08yT1UzU2JiVzNRQUZKUkFBLiIsInNjcCI6InVzZXJfaW1wZXJzb25hdGlvbiIsInNpZCI6IjAwOGI1N2Y5LWQxN2QtYmVmNS1iMzdhLTU5NGUyMjEzNmM1YiIsInN1YiI6Im5UWGs0dFhaUlQ4QTYyNG1SeDdaTTlscy10WTNhUjhkS21oclZYSmVBRDgiLCJ0aWQiOiI3NGM3N2JlNi0xYWQzLTQ5NTctYTRmMi05NDAyODM3MmQ3ZDYiLCJ1bmlxdWVfbmFtZSI6ImNvbnRhY3RAZ2VuZXJhaS5jYSIsInVwbiI6ImNvbnRhY3RAZ2VuZXJhaS5jYSIsInV0aSI6IkdJbnZFZm5ka2tHcW1rcUp4bXNiQUEiLCJ2ZXIiOiIxLjAiLCJ3aWRzIjpbIjYyZTkwMzk0LTY5ZjUtNDIzNy05MTkwLTAxMjE3NzE0NWUxMCIsImI3OWZiZjRkLTNlZjktNDY4OS04MTQzLTc2YjE5NGU4NTUwOSJdLCJ4bXNfZnRkIjoiN3NSeFQ1MEQ3VFV1TlhIVHE1X0NjZldoOTNKRGd0WHpYNE5IYmJBMFprTUJkWE4zWlhOME15MWtjMjF6IiwieG1zX2lkcmVsIjoiMSAyMiJ9.V6ENrfQQ-mt6mP_9pt10KZXhisOHIeKKAHhDUHO7GA6OzSdkAS2Zgc5oNiGgNbUwFhLKkvTuxuSET1gj54UAVpaUMeLaGmKaqHI8p0K4SskP4MxIL09soIoXkpMzxWaoMNg--MtlTfqDraaNz312vxE9zLkgctUTkafhutFEH8wCugqnnxy4H9K742h9vPXE38sMeTX2NF01gx5XYrn7xXD1ccP2ConP0u_AOaKEJsiS8XkOT4iDEDpWedsOOeh3X2D5NvdZPkGC7dNUGqzSPzZVsE11fGFSbwGgknKo2uKbmXCLTXnk9C7Rzw3lTk7WQc1lvFYwQdqARkYlYO4pWw";

function App() {
  const [isAuthenticated, setIsAuthenticated] = useState(false);
  const [username, setUsername] = useState('');
  const [password, setPassword] = useState('');
  const [token, setToken] = useState('');
  const [messages, setMessages] = useState([]);
  const [sessionId, setSessionId] = useState(null);
  const [input, setInput] = useState('');
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const [expandedLineage, setExpandedLineage] = useState(null); // Which message's lineage is open
  const [expandedMcpCard, setExpandedMcpCard] = useState(null); // Which MCP card is expanded (format: "msgIdx-toolIdx")
  const messagesEndRef = useRef(null);

  const scrollToBottom = () => {
    messagesEndRef.current?.scrollIntoView({ behavior: "smooth" });
  };

  useEffect(() => {
    scrollToBottom();
  }, [messages]);

  useEffect(() => {
    // Use hardcoded Azure AD token for backend API calls
    console.log('Token loaded:', AZURE_TOKEN ? 'YES (length: ' + AZURE_TOKEN.length + ')' : 'NO - MISSING!');
    setToken(AZURE_TOKEN);
  }, []);

  const generateSessionId = () => {
    if (window.crypto?.randomUUID) return window.crypto.randomUUID();
    return 'sess-' + Math.random().toString(36).slice(2) + Date.now().toString(36);
  };

  const handleLogin = async (e) => {
    e.preventDefault();
    setError('');
    if (!username || !password) {
      setError('Please enter username and password');
      return;
    }
    if (!token) {
      setError('Backend token not configured.');
      return;
    }
    try {
      const resp = await fetch('/login', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ username, password })
      });
      if (!resp.ok) {
        const data = await resp.json().catch(() => ({}));
        throw new Error(data.detail || 'Login failed');
      }
      localStorage.setItem('username', username);
      const newSess = generateSessionId();
      setSessionId(newSess);
      setIsAuthenticated(true);
      setMessages([{
        role: 'assistant',
        content: `Welcome ${username}! (Session: ${newSess}) Ask me anything about your accounts, opportunities, or contacts.`
      }]);
    } catch (err) {
      setError(err.message);
    }
  };

  const handleLogout = () => {
    setIsAuthenticated(false);
    setUsername('');
    setPassword('');
    setMessages([]);
    localStorage.removeItem('username');
    setSessionId(null);
    // Keep the token - it's for backend API calls, not user auth
  };

  const handleNewSession = () => {
    const newSess = generateSessionId();
    setSessionId(newSess);
    setMessages([{
      role: 'assistant',
      content: `Started a new session (${newSess}). What would you like to explore now?`
    }]);
  };

  const handleSendMessage = async (e) => {
    e.preventDefault();
    if (!input.trim() || loading) return;

    const userMessage = { role: 'user', content: input };
    setMessages(prev => [...prev, userMessage]);
    setInput('');
    setLoading(true);
    setError('');

    try {
      console.log('Sending request to:', `${API_URL}/chat`);
      console.log('Token available:', token ? 'YES (length: ' + token.length + ')' : 'NO - MISSING!');
      
      const response = await fetch(`${API_URL}/chat`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'Authorization': `Bearer ${token}`
        },
        body: JSON.stringify({
          user_id: username,
          session_id: sessionId || 'default',
          messages: [userMessage]
        })
      });

      if (!response.ok) {
        const errorData = await response.json();
        throw new Error(errorData.detail || `HTTP error! status: ${response.status}`);
      }

      const data = await response.json();
      
      setMessages(prev => [...prev, {
        role: 'assistant',
        content: data.response,
        metadata: {
          rounds: data.rounds,
          mcps_used: data.mcps_used,
          execution_time_ms: data.metadata?.execution_time_ms,
          tool_lineage: data.tool_lineage || [], // Array of {tool_name, mcp_server, timestamp, result_summary}
          reasoning_trace: data.reasoning_trace || [] // Array of reasoning steps
        }
      }]);
    } catch (err) {
      console.error('=== FULL ERROR DETAILS ===');
      console.error('Error type:', err.name);
      console.error('Error message:', err.message);
      console.error('Full error:', err);
      console.error('API URL was:', `${API_URL}/chat`);
      console.error('Token length:', token ? token.length : 'NO TOKEN');
      
      const errorDetails = `
ERROR DETAILS:
- Type: ${err.name}
- Message: ${err.message}
- API URL: ${API_URL}/chat
- Token present: ${token ? 'YES (length: ' + token.length + ')' : 'NO'}

If "Failed to fetch", this is likely a CORS or network issue.
Try: Right-click page → Inspect → Network tab to see the actual request.`;
      
      setError(err.message);
      setMessages(prev => [...prev, {
        role: 'assistant',
        content: errorDetails,
        isError: true
      }]);
    } finally {
      setLoading(false);
    }
  };

  if (!isAuthenticated) {
    return (
      <div className="App">
        <div className="login-container">
          <div className="login-box">
            <h1>🤖 Salesforce AI Assistant</h1>
            <p className="subtitle">Sign in to get started</p>
            <form onSubmit={handleLogin}>
              <div className="form-group">
                <label htmlFor="username">Username</label>
                <input
                  id="username"
                  type="text"
                  placeholder="Enter your email"
                  value={username}
                  onChange={(e) => setUsername(e.target.value)}
                  autoFocus
                />
              </div>
              <div className="form-group">
                <label htmlFor="password">Password</label>
                <input
                  id="password"
                  type="password"
                  placeholder="Enter your password"
                  value={password}
                  onChange={(e) => setPassword(e.target.value)}
                />
              </div>
              {error && <div className="error-message">{error}</div>}
              <button type="submit" className="btn-primary">Sign In</button>
              <p className="help-text">
                Using Azure AD token for authentication.
                <br />
                Default credentials loaded from environment.
              </p>
            </form>
          </div>
        </div>
      </div>
    );
  }

  return (
    <div className="App">
      <header className="app-header">
        <h1>🤖 Salesforce AI Assistant</h1>
        <div className="user-info">
          <span>👤 {username}</span>
          {sessionId && <span style={{marginLeft:'0.75rem', fontSize:'0.8rem', opacity:0.8}}>Session: {sessionId}</span>}
          <button onClick={handleNewSession} className="btn-secondary" style={{marginLeft:'0.75rem'}}>New Session</button>
          <button onClick={handleLogout} className="btn-logout">Logout</button>
        </div>
      </header>

      <div className="chat-container">
        <div className="messages">
          {messages.map((msg, idx) => (
            <div key={idx} className={`message ${msg.role} ${msg.isError ? 'error' : ''}`}>
              <div className="message-header">
                <strong>{msg.role === 'user' ? '👤 You' : '🤖 Assistant'}</strong>
                {msg.metadata && (
                  <span className="message-meta">
                    {msg.metadata.mcps_used?.join(', ')} • 
                    {msg.metadata.rounds} rounds • 
                    {(msg.metadata.execution_time_ms / 1000).toFixed(2)}s
                    {msg.metadata.tool_lineage && msg.metadata.tool_lineage.length > 0 && (
                      <button 
                        className="lineage-button"
                        onClick={() => setExpandedLineage(expandedLineage === idx ? null : idx)}
                        title="View tool execution lineage"
                      >
                        💡 {expandedLineage === idx ? 'Hide' : 'Show'} Lineage
                      </button>
                    )}
                  </span>
                )}
              </div>
              <div className="message-content">{msg.content}</div>
              {msg.metadata && expandedLineage === idx && msg.metadata.tool_lineage && (
                <div className="tool-lineage">
                  <h4>🔍 Tool Execution Lineage</h4>
                  <div className="lineage-container">
                    {/* Timeline on the left */}
                    <div className="lineage-timeline">
                      {msg.metadata.tool_lineage.map((tool, toolIdx) => (
                        <div key={toolIdx} className="timeline-node">
                          <div className="timeline-number">{toolIdx + 1}</div>
                          {toolIdx < msg.metadata.tool_lineage.length - 1 && <div className="timeline-connector"></div>}
                        </div>
                      ))}
                    </div>
                    
                    {/* MCP cards on the right */}
                    <div className="lineage-cards">
                      {msg.metadata.tool_lineage.map((tool, toolIdx) => (
                        <div key={toolIdx} className="mcp-card">
                          {/* Level 1: MCP Server */}
                          <div 
                            className="mcp-header"
                            onClick={() => {
                              const key = `${idx}-${toolIdx}`;
                              setExpandedMcpCard(expandedMcpCard === key ? null : key);
                            }}
                            style={{cursor: 'pointer'}}
                          >
                            <div className="mcp-title">
                              <span className="mcp-badge">📊 {tool.mcp_server || 'MCP'}</span>
                              <span className="mcp-arrow">{expandedMcpCard === `${idx}-${toolIdx}` ? '▼' : '▶'}</span>
                            </div>
                            <div className="mcp-summary">
                              <span className="tool-name-preview">{tool.tool_name || tool.name}</span>
                              <span className="result-preview">{tool.result_summary}</span>
                            </div>
                          </div>
                          
                          {/* Level 2: Tool Details (collapsible) */}
                          {expandedMcpCard === `${idx}-${toolIdx}` && (
                            <div className="tool-details">
                              <div className="detail-section">
                                <div className="detail-label">🔧 Tool Called</div>
                                <div className="detail-value">
                                  <code>{tool.tool_name || tool.name}</code>
                                </div>
                              </div>
                              
                              {tool.input && (
                                <div className="detail-section">
                                  <div className="detail-label">📥 Input</div>
                                  <pre className="detail-code">{typeof tool.input === 'string' ? tool.input : JSON.stringify(tool.input, null, 2)}</pre>
                                </div>
                              )}
                              
                              {tool.result_summary && (
                                <div className="detail-section">
                                  <div className="detail-label">📊 Result</div>
                                  <div className="detail-value">{tool.result_summary}</div>
                                </div>
                              )}
                              
                              {tool.output && (
                                <div className="detail-section">
                                  <div className="detail-label">📤 Full Output</div>
                                  <pre className="detail-code">{typeof tool.output === 'string' ? tool.output : JSON.stringify(tool.output, null, 2)}</pre>
                                </div>
                              )}
                              
                              {tool.timestamp && (
                                <div className="detail-timestamp">
                                  ⏱️ {new Date(tool.timestamp).toLocaleTimeString()}
                                </div>
                              )}
                            </div>
                          )}
                        </div>
                      ))}
                    </div>
                  </div>
                  {msg.metadata.reasoning_trace && msg.metadata.reasoning_trace.length > 0 && (
                    <div className="reasoning-trace">
                      <h4>🧠 Reasoning Trace</h4>
                      {msg.metadata.reasoning_trace.map((step, stepIdx) => (
                        <div key={stepIdx} className="reasoning-step">
                          {step}
                        </div>
                      ))}
                    </div>
                  )}
                </div>
              )}
            </div>
          ))}
          {loading && (
            <div className="message assistant loading">
              <div className="message-header"><strong>🤖 Assistant</strong></div>
              <div className="message-content">
                <div className="typing-indicator">
                  <span></span><span></span><span></span>
                </div>
              </div>
            </div>
          )}
          <div ref={messagesEndRef} />
        </div>

        <form onSubmit={handleSendMessage} className="input-form">
          {error && <div className="error-banner">{error}</div>}
          <input
            type="text"
            placeholder="Ask me anything about your Salesforce data..."
            value={input}
            onChange={(e) => setInput(e.target.value)}
            disabled={loading}
          />
          <button type="submit" disabled={loading || !input.trim()} className="btn-send">
            {loading ? '...' : 'Send'}
          </button>
        </form>
      </div>
    </div>
  );
}

export default App;
