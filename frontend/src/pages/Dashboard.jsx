import { useState, useEffect } from 'react';
import { useAuth } from '../contexts/AuthContext';
import { useNavigate } from 'react-router-dom';
import LiveMonitor from '../components/LiveMonitor';
import CameraManager from '../components/CameraManager';
import UserManager from '../components/UserManager';
import BranchManager from '../components/BranchManager';
import Reports from '../components/Reports';
import { Box, AppBar, Toolbar, Typography, Button, Grid, Card, CardContent, CardActions, Alert, CircularProgress, Switch, FormControlLabel } from '@mui/material';
import { CameraAlt, List, Logout, ArrowBack, Analytics, PlayArrow, People, Store, Settings, Assessment } from '@mui/icons-material';
import { analysisAPI, backgroundServiceAPI } from '../services/api';

const Dashboard = () => {
  const { user, logout } = useAuth();
  const navigate = useNavigate();
  const [activeView, setActiveView] = useState(null);
  const [analyzing, setAnalyzing] = useState(false);
  const [analysisResult, setAnalysisResult] = useState(null);
  const [backgroundServiceStatus, setBackgroundServiceStatus] = useState(null);
  const [backgroundServiceLoading, setBackgroundServiceLoading] = useState(false);

  const handleLogout = () => {
    logout();
    navigate('/login');
  };

  const handleKelolaKamera = () => {
    setActiveView('camera-manager');
  };

  const handleKelolaUser = () => {
    setActiveView('user-manager');
  };

  const handleListCabang = () => {
    setActiveView('branch-manager');
  };

  const handleReports = () => {
    setActiveView('reports');
  };

  const handleLiveMonitor = (cameraId) => {
    setActiveView(`live-monitor-${cameraId}`);
  };

  const handleBackToDashboard = () => {
    setActiveView(null);
  };

  const handleAnalyzeAll = async () => {
    if (!window.confirm('Jalankan analisis untuk semua kamera? Proses ini mungkin memakan waktu beberapa detik.')) {
      return;
    }

    setAnalyzing(true);
    setAnalysisResult(null);
    try {
      const result = await analysisAPI.analyzeAll();
      setAnalysisResult({
        type: 'success',
        message: `Analisis selesai! ${result.total_cameras} kamera diproses.`,
        details: result,
      });
    } catch (error) {
      setAnalysisResult({
        type: 'error',
        message: 'Gagal menjalankan analisis: ' + (error.response?.data?.detail || error.message),
      });
    } finally {
      setAnalyzing(false);
    }
  };

  // Load background service status
  useEffect(() => {
    if (user?.role === 'admin') {
      loadBackgroundServiceStatus();
      // Refresh status setiap 5 detik
      const interval = setInterval(loadBackgroundServiceStatus, 5000);
      return () => clearInterval(interval);
    }
  }, [user?.role]);

  const loadBackgroundServiceStatus = async () => {
    try {
      const status = await backgroundServiceAPI.getStatus();
      setBackgroundServiceStatus(status);
    } catch (error) {
      console.error('Gagal memuat status background service:', error);
    }
  };

  const handleToggleBackgroundService = async () => {
    if (!backgroundServiceStatus) return;

    setBackgroundServiceLoading(true);
    try {
      if (backgroundServiceStatus.enabled) {
        await backgroundServiceAPI.disable();
      } else {
        await backgroundServiceAPI.enable();
      }
      // Reload status setelah toggle
      await loadBackgroundServiceStatus();
    } catch (error) {
      setAnalysisResult({
        type: 'error',
        message: 'Gagal mengubah status background service: ' + (error.response?.data?.detail || error.message),
      });
    } finally {
      setBackgroundServiceLoading(false);
    }
  };

  return (
    <Box sx={{ display: 'flex', flexDirection: 'column', width: '100%', minHeight: '100vh', position: 'relative', zIndex: 1 }}>
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
          ) : activeView === 'user-manager' ? (
            <Box>
              <Button startIcon={<ArrowBack />} onClick={handleBackToDashboard} sx={{ mb: 2 }}>
                Kembali ke Dashboard
              </Button>
              <UserManager />
            </Box>
          ) : activeView === 'branch-manager' ? (
            <Box>
              <Button startIcon={<ArrowBack />} onClick={handleBackToDashboard} sx={{ mb: 2 }}>
                Kembali ke Dashboard
              </Button>
              <BranchManager />
            </Box>
          ) : activeView === 'reports' ? (
            <Box>
              <Button startIcon={<ArrowBack />} onClick={handleBackToDashboard} sx={{ mb: 2 }}>
                Kembali ke Dashboard
              </Button>
              <Reports />
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
              {analysisResult && (
                <Alert severity={analysisResult.type} sx={{ mb: 2 }} onClose={() => setAnalysisResult(null)}>
                  {analysisResult.message}
                </Alert>
              )}

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
                      <People sx={{ fontSize: 48, color: 'secondary.main', mb: 2 }} />
                      <Typography variant="h6" component="h2" gutterBottom>
                        Kelola User
                      </Typography>
                      <Typography variant="body2" color="text.secondary">
                        Tambah, edit, dan kelola user (admin & staff)
                      </Typography>
                    </CardContent>
                    <CardActions>
                      <Button fullWidth variant="contained" color="secondary" startIcon={<People />} onClick={handleKelolaUser}>
                        Buka
                      </Button>
                    </CardActions>
                  </Card>
                </Grid>
                <Grid item xs={12} sm={6} md={4}>
                  <Card elevation={3}>
                    <CardContent>
                      <Analytics sx={{ fontSize: 48, color: 'success.main', mb: 2 }} />
                      <Typography variant="h6" component="h2" gutterBottom>
                        Run Analysis
                      </Typography>
                      <Typography variant="body2" color="text.secondary">
                        Jalankan analisis AI untuk semua kamera (billing, alerts, zone states)
                      </Typography>
                    </CardContent>
                    <CardActions>
                      <Button fullWidth variant="contained" color="success" startIcon={analyzing ? <CircularProgress size={20} /> : <PlayArrow />} onClick={handleAnalyzeAll} disabled={analyzing}>
                        {analyzing ? 'Memproses...' : 'Jalankan Analisis'}
                      </Button>
                    </CardActions>
                  </Card>
                </Grid>
                <Grid item xs={12} sm={6} md={4}>
                  <Card elevation={3}>
                    <CardContent>
                      <Store sx={{ fontSize: 48, color: 'primary.main', mb: 2 }} />
                      <Typography variant="h6" component="h2" gutterBottom>
                        Manajemen Cabang
                      </Typography>
                      <Typography variant="body2" color="text.secondary">
                        Lihat semua cabang, kamera, zona, dan statistik
                      </Typography>
                    </CardContent>
                    <CardActions>
                      <Button fullWidth variant="contained" startIcon={<Store />} onClick={handleListCabang}>
                        Buka
                      </Button>
                    </CardActions>
                  </Card>
                </Grid>
                <Grid item xs={12} sm={6} md={4}>
                  <Card elevation={3}>
                    <CardContent>
                      <Settings sx={{ fontSize: 48, color: backgroundServiceStatus?.enabled ? 'success.main' : 'error.main', mb: 2 }} />
                      <Typography variant="h6" component="h2" gutterBottom>
                        Background Service
                      </Typography>
                      <Typography variant="body2" color="text.secondary" sx={{ mb: 2 }}>
                        {backgroundServiceStatus?.enabled ? `Aktif - ${backgroundServiceStatus.active_threads || 0} thread berjalan` : 'Nonaktif - Deteksi otomatis dimatikan'}
                      </Typography>
                      <FormControlLabel
                        control={<Switch checked={backgroundServiceStatus?.enabled || false} onChange={handleToggleBackgroundService} disabled={backgroundServiceLoading || !backgroundServiceStatus} color="primary" />}
                        label={backgroundServiceStatus?.enabled ? 'Aktif' : 'Nonaktif'}
                      />
                    </CardContent>
                  </Card>
                </Grid>
                <Grid item xs={12} sm={6} md={4}>
                  <Card elevation={3}>
                    <CardContent>
                      <Assessment sx={{ fontSize: 48, color: 'info.main', mb: 2 }} />
                      <Typography variant="h6" component="h2" gutterBottom>
                        Laporan & Analitik
                      </Typography>
                      <Typography variant="body2" color="text.secondary">
                        Lihat laporan meja terisi, antrian penuh, dan statistik lainnya
                      </Typography>
                    </CardContent>
                    <CardActions>
                      <Button fullWidth variant="contained" color="info" startIcon={<Assessment />} onClick={handleReports}>
                        Buka Laporan
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
