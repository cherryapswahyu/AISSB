import { useAuth } from '../contexts/AuthContext';
import { useNavigate } from 'react-router-dom';
import CameraList from './CameraList';
import './Dashboard.css';

const Dashboard = () => {
  const { user, logout, isAdmin } = useAuth();
  const navigate = useNavigate();

  const handleLogout = () => {
    logout();
    navigate('/login');
  };

  return (
    <div className="dashboard">
      <header className="dashboard-header">
        <div className="header-content">
          <h1>CCTV Analytics Dashboard</h1>
          <div className="user-info">
            <span>
              {user?.username} ({user?.role})
            </span>
            <button onClick={handleLogout} className="logout-button">
              Logout
            </button>
          </div>
        </div>
      </header>

      <main className="dashboard-main">
        <CameraList isAdmin={isAdmin} />
      </main>
    </div>
  );
};

export default Dashboard;
