import React, { useState } from 'react';
import { Activity, MessageSquareWarning, ArrowRight, ChevronDown, ChevronUp, ScrollText } from 'lucide-react';
import { LineChart, Line, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer } from 'recharts';

const FeedbackCard = ({ session }) => {
  const [isExpanded, setIsExpanded] = useState(false);
  const sentiment = session.OverallSentiment?.toLowerCase() || 'neutral';

  return (
    <div className={`log-card glass ${sentiment}`}>
      <div className="log-header">
        <span className="timestamp">{session.Timestamp}</span>
        {session.Product && <span className="product-badge">{session.Product}</span>}
        <span className={`badge ${sentiment}`}>
          {session.OverallSentiment}
        </span>
      </div>
      <div className="log-body">
        <div className="insight-box">
          <ArrowRight size={16} className="insight-icon" />
          <p>{session.ActionableInsights}</p>
        </div>
      </div>
      
      {session.Transcript && (
        <div className="transcript-section">
          <button 
            className="transcript-toggle" 
            onClick={() => setIsExpanded(!isExpanded)}
          >
            <ScrollText size={14} />
            <span>{isExpanded ? 'Hide Conversation' : 'View Conversation Log'}</span>
            {isExpanded ? <ChevronUp size={14} /> : <ChevronDown size={14} />}
          </button>
          
          {isExpanded && (
            <div className="transcript-content glass-inset">
              {session.Transcript.split('\n').map((line, i) => {
                const isUser = line.toLowerCase().startsWith('user:');
                const isMaya = line.toLowerCase().startsWith('assistant:');
                return (
                  <div key={i} className={`transcript-line ${isUser ? 'user' : isMaya ? 'maya' : ''}`}>
                    <span className="speaker">{line.split(':')[0]}:</span>
                    <span className="text">{line.split(':').slice(1).join(':')}</span>
                  </div>
                );
              })}
            </div>
          )}
        </div>
      )}

      <div className="log-footer">
        <span className="session-id">Session: {session.SessionID}</span>
      </div>
    </div>
  );
};

const FeedbackTab = ({ data, selectedProduct, setSelectedProduct, productList }) => {
  const filteredData = selectedProduct === 'All Products' ? data : data.filter(d => d.Product === selectedProduct);

  const summary = {
    total: filteredData.length,
    positive: filteredData.filter(d => d.OverallSentiment === 'POSITIVE').length,
    neutral: filteredData.filter(d => d.OverallSentiment === 'NEUTRAL').length,
    negative: filteredData.filter(d => d.OverallSentiment === 'NEGATIVE').length,
  };

  return (
    <div className="tab-content">
      <div className="tab-header">
        <div className="header-text">
          <h2>Customer Sentiment Analysis</h2>
          <p>Real-time post-call insights</p>
        </div>
        <select 
          className="product-btn"
          value={selectedProduct} 
          onChange={(e) => setSelectedProduct(e.target.value)}
        >
          {productList.map(p => (
            <option key={p} value={p}>{p}</option>
          ))}
        </select>
      </div>

      <div className="summary-cards compact">
        <div className="card positive-light">
          <h3>Positive</h3>
          <p className="big-number">{summary.positive}</p>
        </div>
        <div className="card neutral-light">
          <h3>Neutral</h3>
          <p className="big-number">{summary.neutral}</p>
        </div>
        <div className="card negative-light">
          <h3>Negative</h3>
          <p className="big-number">{summary.negative}</p>
        </div>
      </div>

      <div className="chart-section glass">
        <h2><Activity size={20}/> Sentiment Trend</h2>
        <div className="chart-wrapper">
          <ResponsiveContainer width="100%" height={250}>
            <LineChart data={filteredData}>
              <CartesianGrid strokeDasharray="3 3" stroke="#333" vertical={false} />
              <XAxis dataKey="Timestamp" stroke="#888" tick={{fontSize: 10}} />
              <YAxis domain={[-1.2, 1.2]} ticks={[-1, 0, 1]} tickFormatter={(val) => {
                if(val === 1) return 'Pos';
                if(val === 0) return 'Neu';
                if(val === -1) return 'Neg';
                return '';
              }} stroke="#888" />
              <Tooltip 
                contentStyle={{backgroundColor: '#111', borderColor: '#333', borderRadius: '8px'}} 
                labelStyle={{color: '#fff'}}
              />
              <Line type="monotone" dataKey="score" stroke="#8b5cf6" strokeWidth={3} dot={{r: 4, fill: '#8b5cf6'}} activeDot={{r: 6}} />
            </LineChart>
          </ResponsiveContainer>
        </div>
      </div>

      <div className="insights-section">
        <h2><MessageSquareWarning size={20}/> Actionable Insights</h2>
        <div className="logs-list">
          {filteredData.length === 0 ? (
            <p className="empty-state">No conversations logged yet.</p>
          ) : (
            [...filteredData].reverse().map((session, idx) => (
              <FeedbackCard key={idx} session={session} />
            ))
          )}
        </div>
      </div>
    </div>
  );
};

export default FeedbackTab;
