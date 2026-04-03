import React from 'react';
import { User, Mail, Phone, ShoppingBag, Contact, ClipboardCopy } from 'lucide-react';

const LeadsTab = ({ leads }) => {
  const copyToClipboard = (text) => {
    navigator.clipboard.writeText(text);
    alert('Copied to clipboard!');
  };

  return (
    <div className="tab-content">
      <div className="tab-header">
        <h2>Dyson Leads Registry</h2>
        <p>Live leads captured by Maya Voice Assistant</p>
      </div>

      <div className="leads-grid">
        {leads.length === 0 ? (
          <div className="empty-state glass">
             <Contact size={48} className="empty-icon" />
             <p>No leads captured yet. Maya is waiting to help.</p>
          </div>
        ) : (
          [...leads].reverse().map((lead, idx) => (
            <div key={idx} className="lead-card glass">
              <div className="lead-header">
                <div className="lead-avatar">
                   <User size={24} />
                </div>
                <div className="lead-id">
                   <span className="label">Reference ID</span>
                   <span className="value">{lead.record_id}</span>
                   <button onClick={() => copyToClipboard(lead.record_id)} className="copy-btn">
                     <ClipboardCopy size={14} />
                   </button>
                </div>
              </div>
              <div className="lead-name">
                 <h3>{lead.name}</h3>
                 <span className="badge-product">{lead.product || 'General Interest'}</span>
              </div>
              <div className="lead-contact">
                 <div className="contact-item">
                    <Mail size={16} />
                    <span>{lead.email || 'N/A'}</span>
                 </div>
                 <div className="contact-item">
                    <Phone size={16} />
                    <span>{lead.phone || 'N/A'}</span>
                 </div>
              </div>
              <div className="lead-summary">
                 <ShoppingBag size={16} />
                 <p>{lead.summary}</p>
              </div>
              <div className="lead-footer">
                 <span className="timestamp">{new Date(lead.timestamp).toLocaleString()}</span>
                 <span className="session-id">Session: {lead.session_id}</span>
              </div>
            </div>
          ))
        )}
      </div>
    </div>
  );
};

export default LeadsTab;
