import { useState } from 'react';
import { useAuth } from '../contexts/AuthContext';
import { useNavigate } from 'react-router-dom';
import LiveMonitor from '../components/LiveMonitor';
import CameraManager from '../components/CameraManager';
import { Box, AppBar, Toolbar, Typography, Button, Grid, Card, CardContent, CardActions } from '@mui/material';
import { CameraAlt, List, Logout, ArrowBack } from '@mui/icons-material';

const Dashboard = () => {
  const { user, logout } = useAuth();
  const navigate = useNavigate();
  const [activeView, setActiveView] = useState(null);

  const handleLogout = () => {
    logout();
    navigate('/login');
  };

  const handleKelolaKamera = () => {
    setActiveView('camera-manager');
  };

  const handleListCabang = () => {
    // TODO: Navigate ke halaman list semua cabang
    console.log('List Semua Cabang');
  };

  const handleLiveMonitor = (cameraId) => {
    setActiveView(`live-monitor-${cameraId}`);
  };

  const handleBackToDashboard = () => {
    setActiveView(null);
  };

  return (
    <Box sx={{ display: 'flex', flexDirection: 'column', width: '100%', minHeight: '100vh' }}>
      <AppBar position="static" elevation={2}>
        <Toolbar>
          <Typography variant="h6" component="div" sx={{ flexGrow: 1 }}>
            Halo, {user?.username || 'User'}
          </Typography>
          <Button color="inherit" startIcon={<Logout />} onClick={handleLogout}>
            Logout
          </Button>
        </Toolbar>
      </AppBar>

      <Box sx={{ width: '100%', flex: 1, px: { xs: 1, sm: 2, md: 3 }, py: 2 }}>
        {user?.role === 'admin' ? (
          activeView === 'camera-manager' ? (
            <Box>
              <Button startIcon={<ArrowBack />} onClick={handleBackToDashboard} sx={{ mb: 2 }}>
                Kembali ke Dashboard
              </Button>
              <CameraManager onSetupZona={handleLiveMonitor} />
            </Box>
          ) : activeView?.startsWith('live-monitor-') ? (
            <Box sx={{ width: '100%' }}>
              <Button startIcon={<ArrowBack />} onClick={handleBackToDashboard} sx={{ mb: 2 }}>
                Kembali ke Dashboard
              </Button>
              <LiveMonitor branchId={parseInt(activeView.split('-')[2])} />
            </Box>
          ) : (
            <Box>
              <Typography variant="h4" component="h1" gutterBottom fontWeight="bold">
                Dashboard Admin
              </Typography>
              <Grid container spacing={3} sx={{ mt: 2 }}>
                <Grid item xs={12} sm={6} md={4}>
                  <Card elevation={3}>
                    <CardContent>
                      <CameraAlt sx={{ fontSize: 48, color: 'primary.main', mb: 2 }} />
                      <Typography variant="h6" component="h2" gutterBottom>
                        Kelola Kamera
                      </Typography>
                      <Typography variant="body2" color="text.secondary">
                        Tambah, edit, dan kelola kamera CCTV
                      </Typography>
                    </CardContent>
                    <CardActions>
                      <Button fullWidth variant="contained" startIcon={<CameraAlt />} onClick={handleKelolaKamera}>
                        Buka
                      </Button>
                    </CardActions>
                  </Card>
                </Grid>
                <Grid item xs={12} sm={6} md={4}>
                  <Card elevation={3}>
                    <CardContent>
                      <List sx={{ fontSize: 48, color: 'primary.main', mb: 2 }} />
                      <Typography variant="h6" component="h2" gutterBottom>
                        List Semua Cabang
                      </Typography>
                      <Typography variant="body2" color="text.secondary">
                        Lihat semua cabang dan statistik
                      </Typography>
                    </CardContent>
                    <CardActions>
                      <Button fullWidth variant="contained" startIcon={<List />} onClick={handleListCabang}>
                        Buka
                      </Button>
                    </CardActions>
                  </Card>
                </Grid>
              </Grid>
            </Box>
          )
        ) : user?.role === 'staff' ? (
          <Box sx={{ width: '100%' }}>
            <Typography variant="h4" component="h1" gutterBottom fontWeight="bold">
              Cabang Saya (ID: {user?.branch_id || 'N/A'})
            </Typography>
            <LiveMonitor branchId={user?.branch_id} />
          </Box>
        ) : (
          <Box sx={{ textAlign: 'center', mt: 4 }}>
            <Typography variant="h6" color="text.secondary">
              Memuat dashboard...
            </Typography>
          </Box>
        )}
      </Box>
    </Box>
  );
};

export default Dashboard;
