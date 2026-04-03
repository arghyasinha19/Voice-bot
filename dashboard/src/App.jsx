import { useState, useEffect, useCallback } from 'react';
import Papa from 'papaparse';
import { RefreshCw, LayoutDashboard, Users, MessageSquareText } from 'lucide-react';
import Sidebar from './components/Sidebar';
import DashboardTab from './components/DashboardTab';
import LeadsTab from './components/LeadsTab';
import FeedbackTab from './components/FeedbackTab';
import './App.css';

const API_BASE_URL = 'http://localhost:8001/api';
const STATS_URL = `${API_BASE_URL}/dashboard`;
const LEADS_URL = `${API_BASE_URL}/leads-history`;
const FEEDBACK_URL = `${API_BASE_URL}/feedback`;

function App() {
  const [activeTab, setActiveTab] = useState('dashboard');
  const [stats, setStats] = useState({});
  const [leads, setLeads] = useState([]);
  const [sentimentData, setSentimentData] = useState([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);
  const [selectedProduct, setSelectedProduct] = useState('All Products');

  const fetchData = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      // 1. Fetch Stats
      const statsRes = await fetch(STATS_URL);
      if (statsRes.ok) {
        const statsJson = await statsRes.json();
        setStats(statsJson);
      }

      // 2. Fetch Leads (Now a JSON list from API)
      const leadsRes = await fetch(LEADS_URL);
      if (leadsRes.ok) {
        const leadsJson = await leadsRes.json();
        setLeads(leadsJson);
      }

      // 3. Fetch Feedback (Now a JSON list from API)
      const feedbackRes = await fetch(FEEDBACK_URL);
      if (feedbackRes.ok) {
        const feedbackJson = await feedbackRes.json();
        setSentimentData(feedbackJson);
      }
    } catch (err) {
      console.error("Error fetching dashboard data:", err);
      setError("Dashboard API is offline (Port 8001). Please check the server.");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchData();
    // Refresh every 30 seconds for "live" feel
    const interval = setInterval(fetchData, 30000);
    return () => clearInterval(interval);
  }, [fetchData]);

  const productList = ['All Products', ...new Set(sentimentData.map(d => d.Product).filter(Boolean))];

  const renderContent = () => {
    switch (activeTab) {
      case 'dashboard':
        return <DashboardTab stats={stats} />;
      case 'leads':
        return <LeadsTab leads={leads} />;
      case 'feedback':
        return (
          <FeedbackTab 
            data={sentimentData} 
            selectedProduct={selectedProduct}
            setSelectedProduct={setSelectedProduct}
            productList={productList}
          />
        );
      default:
        return <DashboardTab stats={stats} />;
    }
  };

  return (
    <div className="app-container">
      <Sidebar activeTab={activeTab} setActiveTab={setActiveTab} />
      <main className="main-content">
        <header className="main-header">
           <div className="greeting">
              <h1>{activeTab.charAt(0).toUpperCase() + activeTab.slice(1)}</h1>
              <p>Welcome back, Administrator</p>
           </div>
           <button className="refresh-btn" onClick={fetchData} disabled={loading}>
            <RefreshCw className={loading ? 'spinning' : ''} size={18} />
            {loading ? 'Updating...' : 'Sync Now'}
          </button>
        </header>
        
        {error && <div className="error-banner">{error}</div>}
        
        <div className="content-area">
          {renderContent()}
        </div>
      </main>
    </div>
  );
}

export default App;
