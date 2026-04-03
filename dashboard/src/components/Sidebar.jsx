import React from 'react';
import { LayoutDashboard, Users, MessageSquareText, ShieldCheck } from 'lucide-react';

const Sidebar = ({ activeTab, setActiveTab }) => {
  const tabs = [
    { id: 'dashboard', label: 'Dashboard', icon: LayoutDashboard },
    { id: 'leads', label: 'Leads', icon: Users },
    { id: 'feedback', label: 'Customer Feedback', icon: MessageSquareText },
  ];

  return (
    <aside className="sidebar">
      <div className="sidebar-logo">
        <ShieldCheck className="logo-icon" />
        <span>Maya Admin</span>
      </div>
      <nav className="sidebar-nav">
        {tabs.map((tab) => {
          const Icon = tab.icon;
          return (
            <button
              key={tab.id}
              className={`nav-item ${activeTab === tab.id ? 'active' : ''}`}
              onClick={() => setActiveTab(tab.id)}
            >
              <Icon size={20} />
              <span>{tab.label}</span>
            </button>
          );
        })}
      </nav>
      <div className="sidebar-footer">
        <div className="status-indicator">
          <span className="pulse"></span>
          Maya Live
        </div>
      </div>
    </aside>
  );
};

export default Sidebar;
