import React from 'react';

const MetricCard = ({ title, value, icon: Icon, trend, color }) => {
  return (
    <div className={`metric-card glass ${color}`}>
      <div className="card-top">
        <div className={`icon-container ${color}`}>
          <Icon size={24} />
        </div>
        {trend && <span className="trend-badge">{trend}</span>}
      </div>
      <div className="card-bottom">
        <h3>{title}</h3>
        <p className="big-number">{value}</p>
      </div>
    </div>
  );
};

export default MetricCard;
