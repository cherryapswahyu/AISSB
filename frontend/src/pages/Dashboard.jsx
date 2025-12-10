import { useState, useEffect } from 'react';
import { useAuth } from '../contexts/AuthContext';
import { useNavigate } from 'react-router-dom';
import LiveMonitor from '../components/LiveMonitor';
import CameraManager from '../components/CameraManager';
import UserManager from '../components/UserManager';
import BranchManager from '../components/BranchManager';
import Reports from '../components/Reports';
import StaffFaceManager from '../components/StaffFaceManager';
import { Box, Drawer, AppBar, Toolbar, Typography, Button, List, ListItem, ListItemButton, ListItemIcon, ListItemText, Alert, CircularProgress, Switch, FormControlLabel, Chip, Paper, Divider, IconButton, Collapse } from '@mui/material';
import { CameraAlt, Logout, PlayArrow, People, Store, Settings, Assessment, Face, Dashboard as DashboardIcon, Menu as MenuIcon, ExpandLess, ExpandMore } from '@mui/icons-material';
import { analysisAPI, backgroundServiceAPI } from '../services/api';

const DRAWER_WIDTH = 280;

const Dashboard = () => {
  const { user, logout } = useAuth();
  const navigate = useNavigate();
  const [activeView, setActiveView] = useState(null);
  const [analyzing, setAnalyzing] = useState(false);
  const [analysisResult, setAnalysisResult] = useState(null);
  const [backgroundServiceStatus, setBackgroundServiceStatus] = useState(null);
  const [backgroundServiceLoading, setBackgroundServiceLoading] = useState(false);
  const [mobileOpen, setMobileOpen] = useState(false);
  const [desktopOpen, setDesktopOpen] = useState(true);
  const [settingsOpen, setSettingsOpen] = useState(false);

  const handleLogout = () => {
    logout();
    navigate('/login');
  };

  const handleDrawerToggle = () => {
    setMobileOpen(!mobileOpen);
  };

  const handleDesktopDrawerToggle = () => {
    setDesktopOpen(!desktopOpen);
  };

  const handleKelolaKamera = () => {
    setActiveView('camera-manager');
    setMobileOpen(false);
  };

  const handleKelolaUser = () => {
    setActiveView('user-manager');
    setMobileOpen(false);
  };

  const handleListCabang = () => {
    setActiveView('branch-manager');
    setMobileOpen(false);
  };

  const handleReports = () => {
    setActiveView('reports');
    setMobileOpen(false);
  };

  const handleStaffFaces = () => {
    setActiveView('staff-faces');
    setMobileOpen(false);
  };

  const handleLiveMonitor = (cameraId) => {
    setActiveView(`live-monitor-${cameraId}`);
    setMobileOpen(false);
  };

  const handleBackToDashboard = () => {
    setActiveView(null);
    setMobileOpen(false);
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

  useEffect(() => {
    if (user?.role === 'admin') {
      loadBackgroundServiceStatus();
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

  // Render sub-views
  const renderSubView = () => {
    switch (activeView) {
      case 'camera-manager':
        return <CameraManager onSetupZona={handleLiveMonitor} />;
      case 'user-manager':
        return <UserManager />;
      case 'branch-manager':
        return <BranchManager />;
      case 'reports':
        return <Reports />;
      case 'staff-faces':
        return <StaffFaceManager />;
      default:
        if (activeView?.startsWith('live-monitor-')) {
          return <LiveMonitor branchId={parseInt(activeView.split('-')[2])} />;
        }
        return null;
    }
  };

  // Admin menu items
  const adminMenuItems = [
    {
      id: 'dashboard',
      icon: DashboardIcon,
      title: 'Dashboard',
      action: handleBackToDashboard,
      active: activeView === null,
    },
    {
      id: 'camera',
      icon: CameraAlt,
      title: 'Kelola Kamera',
      action: handleKelolaKamera,
      active: activeView === 'camera-manager',
    },
    {
      id: 'user',
      icon: People,
      title: 'Kelola User',
      action: handleKelolaUser,
      active: activeView === 'user-manager',
    },
    {
      id: 'branch',
      icon: Store,
      title: 'Manajemen Cabang',
      action: handleListCabang,
      active: activeView === 'branch-manager',
    },
    {
      id: 'reports',
      icon: Assessment,
      title: 'Laporan & Analitik',
      action: handleReports,
      active: activeView === 'reports',
    },
    {
      id: 'staff',
      icon: Face,
      title: 'Manajemen Staff',
      action: handleStaffFaces,
      active: activeView === 'staff-faces',
    },
  ];

  // Sidebar content
  const drawerContent = (
    <Box sx={{ display: 'flex', flexDirection: 'column', height: '100%', overflow: 'auto' }}>
      <Toolbar
        sx={{
          bgcolor: 'primary.main',
          color: 'white',
          display: 'flex',
          alignItems: 'center',
          minHeight: { xs: '56px', sm: '64px' },
          px: { xs: 1.5, sm: 2 },
        }}>
        <DashboardIcon sx={{ mr: 1, fontSize: { xs: 20, sm: 24 } }} />
        <Typography variant="h6" noWrap component="div" sx={{ fontWeight: 600, fontSize: { xs: '1rem', sm: '1.25rem' } }}>
          CCTV Analytics
        </Typography>
      </Toolbar>
      <Divider />
      {user?.role === 'admin' && (
        <>
          <List sx={{ pt: { xs: 1, sm: 2 }, flexGrow: 1, overflow: 'auto' }}>
            {adminMenuItems.map((item) => {
              const IconComponent = item.icon;
              return (
                <ListItem key={item.id} disablePadding>
                  <ListItemButton
                    onClick={item.action}
                    selected={item.active}
                    sx={{
                      mx: { xs: 0.5, sm: 1 },
                      mb: { xs: 0.25, sm: 0.5 },
                      borderRadius: 2,
                      minHeight: { xs: 48, sm: 40 }, // Larger touch target for mobile
                      py: { xs: 1.5, sm: 1 },
                      px: { xs: 1.5, sm: 2 },
                      '&.Mui-selected': {
                        bgcolor: 'primary.main',
                        color: 'white',
                        '&:hover': {
                          bgcolor: 'primary.dark',
                        },
                        '& .MuiListItemIcon-root': {
                          color: 'white',
                        },
                      },
                      '&:hover': {
                        bgcolor: 'action.hover',
                      },
                      '&:active': {
                        bgcolor: 'action.selected',
                      },
                    }}>
                    <ListItemIcon
                      sx={{
                        minWidth: { xs: 44, sm: 40 },
                        color: item.active ? 'white' : 'inherit',
                      }}>
                      <IconComponent sx={{ fontSize: { xs: 24, sm: 20 } }} />
                    </ListItemIcon>
                    <ListItemText
                      primary={item.title}
                      primaryTypographyProps={{
                        fontSize: { xs: '0.95rem', sm: '0.875rem' },
                        fontWeight: item.active ? 600 : 400,
                      }}
                    />
                  </ListItemButton>
                </ListItem>
              );
            })}
          </List>
          <Divider sx={{ my: { xs: 0.5, sm: 1 } }} />
          <List>
            <ListItem disablePadding>
              <ListItemButton
                onClick={() => setSettingsOpen(!settingsOpen)}
                sx={{
                  mx: { xs: 0.5, sm: 1 },
                  borderRadius: 2,
                  minHeight: { xs: 48, sm: 40 },
                  py: { xs: 1.5, sm: 1 },
                  px: { xs: 1.5, sm: 2 },
                  '&:hover': {
                    bgcolor: 'action.hover',
                  },
                  '&:active': {
                    bgcolor: 'action.selected',
                  },
                }}>
                <ListItemIcon sx={{ minWidth: { xs: 44, sm: 40 } }}>
                  <Settings sx={{ fontSize: { xs: 24, sm: 20 } }} />
                </ListItemIcon>
                <ListItemText
                  primary="Settings"
                  primaryTypographyProps={{
                    fontSize: { xs: '0.95rem', sm: '0.875rem' },
                  }}
                />
                {settingsOpen ? <ExpandLess /> : <ExpandMore />}
              </ListItemButton>
            </ListItem>
            <Collapse in={settingsOpen} timeout="auto" unmountOnExit>
              <List component="div" disablePadding>
                <ListItem sx={{ pl: { xs: 3, sm: 4 }, pr: { xs: 1.5, sm: 2 }, py: { xs: 1.5, sm: 1 } }}>
                  <Box sx={{ width: '100%' }}>
                    <Typography variant="body2" color="text.secondary" sx={{ mb: 1, fontSize: { xs: '0.875rem', sm: '0.8125rem' } }}>
                      Background Service
                    </Typography>
                    <Typography variant="caption" color="text.secondary" sx={{ display: 'block', mb: 1.5, fontSize: { xs: '0.75rem', sm: '0.6875rem' } }}>
                      {backgroundServiceStatus?.enabled ? `Aktif - ${backgroundServiceStatus.active_threads || 0} thread berjalan` : 'Nonaktif'}
                    </Typography>
                    <FormControlLabel
                      control={
                        <Switch
                          checked={backgroundServiceStatus?.enabled || false}
                          onChange={handleToggleBackgroundService}
                          disabled={backgroundServiceLoading || !backgroundServiceStatus}
                          size="medium"
                          sx={{
                            '& .MuiSwitch-switchBase': {
                              padding: { xs: 1, sm: 0.75 },
                            },
                          }}
                        />
                      }
                      label={<Typography sx={{ fontSize: { xs: '0.875rem', sm: '0.8125rem' } }}>{backgroundServiceStatus?.enabled ? 'Aktif' : 'Nonaktif'}</Typography>}
                    />
                  </Box>
                </ListItem>
                <ListItem sx={{ pl: { xs: 3, sm: 4 }, pr: { xs: 1.5, sm: 2 }, py: { xs: 1, sm: 0.5 } }}>
                  <Button
                    fullWidth
                    variant="contained"
                    color="success"
                    startIcon={analyzing ? <CircularProgress size={18} color="inherit" /> : <PlayArrow />}
                    onClick={handleAnalyzeAll}
                    disabled={analyzing}
                    sx={{
                      textTransform: 'none',
                      minHeight: { xs: 44, sm: 36 },
                      fontSize: { xs: '0.875rem', sm: '0.8125rem' },
                      py: { xs: 1.5, sm: 1 },
                    }}>
                    {analyzing ? 'Memproses...' : 'Run Analysis'}
                  </Button>
                </ListItem>
              </List>
            </Collapse>
          </List>
        </>
      )}
      {user?.role === 'staff' && (
        <List sx={{ pt: { xs: 1, sm: 2 }, flexGrow: 1 }}>
          <ListItem disablePadding>
            <ListItemButton
              onClick={handleBackToDashboard}
              selected={activeView === null}
              sx={{
                mx: { xs: 0.5, sm: 1 },
                borderRadius: 2,
                minHeight: { xs: 48, sm: 40 },
                py: { xs: 1.5, sm: 1 },
                px: { xs: 1.5, sm: 2 },
                '&.Mui-selected': {
                  bgcolor: 'primary.main',
                  color: 'white',
                  '&:hover': {
                    bgcolor: 'primary.dark',
                  },
                },
                '&:active': {
                  bgcolor: 'action.selected',
                },
              }}>
              <ListItemIcon sx={{ minWidth: { xs: 44, sm: 40 } }}>
                <DashboardIcon sx={{ fontSize: { xs: 24, sm: 20 } }} />
              </ListItemIcon>
              <ListItemText
                primary="Live Monitor"
                primaryTypographyProps={{
                  fontSize: { xs: '0.95rem', sm: '0.875rem' },
                  fontWeight: activeView === null ? 600 : 400,
                }}
              />
            </ListItemButton>
          </ListItem>
        </List>
      )}
      <Box sx={{ p: { xs: 1.5, sm: 2 }, borderTop: 1, borderColor: 'divider', flexShrink: 0 }}>
        <Box sx={{ display: 'flex', alignItems: 'center', mb: { xs: 1.5, sm: 1 } }}>
          <Chip
            label={user?.username || 'User'}
            size="small"
            sx={{
              mr: 1,
              bgcolor: 'action.selected',
              fontSize: { xs: '0.75rem', sm: '0.6875rem' },
              height: { xs: 28, sm: 24 },
            }}
          />
        </Box>
        <Button
          fullWidth
          variant="outlined"
          startIcon={<Logout />}
          onClick={handleLogout}
          sx={{
            textTransform: 'none',
            minHeight: { xs: 44, sm: 36 },
            fontSize: { xs: '0.875rem', sm: '0.8125rem' },
            py: { xs: 1.5, sm: 1 },
          }}>
          Logout
        </Button>
      </Box>
    </Box>
  );

  return (
    <Box sx={{ display: 'flex', minHeight: '100vh', bgcolor: 'background.default' }}>
      {/* AppBar for mobile only */}
      <AppBar
        position="fixed"
        sx={{
          display: { xs: 'block', sm: 'none' },
          bgcolor: 'primary.main',
        }}>
        <Toolbar>
          <IconButton
            color="inherit"
            aria-label="open drawer"
            edge="start"
            onClick={handleDrawerToggle}
            sx={{
              mr: 2,
              minWidth: 44,
              minHeight: 44,
            }}>
            <MenuIcon />
          </IconButton>
          <Typography
            variant="h6"
            noWrap
            component="div"
            sx={{
              flexGrow: 1,
              fontWeight: 600,
              fontSize: '1rem',
            }}>
            {activeView ? 'CCTV Analytics' : 'Dashboard Admin'}
          </Typography>
        </Toolbar>
      </AppBar>

      {/* AppBar for desktop - untuk tombol toggle sidebar */}
      <AppBar
        position="fixed"
        sx={{
          display: { xs: 'none', sm: 'block' },
          width: { sm: desktopOpen ? `calc(100% - ${DRAWER_WIDTH}px)` : '100%' },
          ml: { sm: desktopOpen ? `${DRAWER_WIDTH}px` : 0 },
          bgcolor: 'primary.main',
          transition: 'width 0.3s, margin-left 0.3s',
        }}>
        <Toolbar>
          <IconButton
            color="inherit"
            aria-label="toggle drawer"
            edge="start"
            onClick={handleDesktopDrawerToggle}
            sx={{
              mr: 2,
              minWidth: 44,
              minHeight: 44,
            }}>
            <MenuIcon />
          </IconButton>
          <Typography
            variant="h6"
            noWrap
            component="div"
            sx={{
              flexGrow: 1,
              fontWeight: 600,
              fontSize: '1.25rem',
            }}>
            {activeView ? 'CCTV Analytics' : 'Dashboard Admin'}
          </Typography>
        </Toolbar>
      </AppBar>

      {/* Sidebar Drawer */}
      <Box component="nav" sx={{ width: { sm: DRAWER_WIDTH }, flexShrink: { sm: 0 } }}>
        <Drawer
          variant="temporary"
          open={mobileOpen}
          onClose={handleDrawerToggle}
          ModalProps={{
            keepMounted: true, // Better open performance on mobile.
          }}
          sx={{
            display: { xs: 'block', sm: 'none' },
            '& .MuiDrawer-paper': {
              boxSizing: 'border-box',
              width: { xs: '85vw', sm: DRAWER_WIDTH },
              maxWidth: DRAWER_WIDTH,
            },
            '& .MuiBackdrop-root': {
              backgroundColor: 'rgba(0, 0, 0, 0.5)',
            },
          }}>
          {drawerContent}
        </Drawer>
        <Drawer
          variant="persistent"
          open={desktopOpen}
          sx={{
            display: { xs: 'none', sm: 'block' },
            '& .MuiDrawer-paper': {
              boxSizing: 'border-box',
              width: DRAWER_WIDTH,
              position: 'relative',
              height: '100vh',
              overflow: 'hidden',
              transition: 'width 0.3s',
            },
          }}>
          {drawerContent}
        </Drawer>
      </Box>

      {/* Main Content */}
      <Box
        component="main"
        sx={{
          flexGrow: 1,
          p: { xs: 2, sm: 3 },
          width: { sm: desktopOpen ? `calc(100% - ${DRAWER_WIDTH}px)` : '100%' },
          mt: { xs: 7, sm: 7 },
          overflow: 'auto',
          transition: 'width 0.3s',
        }}>
        {user?.role === 'admin' ? (
          activeView ? (
            <Box>
              {analysisResult && (
                <Alert
                  severity={analysisResult.type}
                  sx={{
                    mb: 3,
                    '& .MuiAlert-message': {
                      fontSize: { xs: '0.875rem', sm: '1rem' },
                    },
                  }}
                  onClose={() => setAnalysisResult(null)}>
                  {analysisResult.message}
                </Alert>
              )}
              {renderSubView()}
            </Box>
          ) : (
            <Box>
              <Typography variant="h4" component="h1" gutterBottom fontWeight="bold" color="text.primary" sx={{ fontSize: { xs: '1.75rem', sm: '2.125rem' } }}>
                Dashboard Admin
              </Typography>
              <Typography variant="body1" color="text.secondary" sx={{ mb: { xs: 3, sm: 4 }, fontSize: { xs: '0.875rem', sm: '1rem' } }}>
                Kelola sistem CCTV Analytics Anda dari sini
              </Typography>

              {analysisResult && (
                <Alert
                  severity={analysisResult.type}
                  sx={{
                    mb: 3,
                    '& .MuiAlert-message': {
                      fontSize: { xs: '0.875rem', sm: '1rem' },
                    },
                  }}
                  onClose={() => setAnalysisResult(null)}>
                  {analysisResult.message}
                </Alert>
              )}

              <Paper
                elevation={2}
                sx={{
                  p: { xs: 2.5, sm: 4 },
                  borderRadius: 3,
                }}>
                <Typography variant="h6" gutterBottom sx={{ mb: { xs: 2, sm: 3 }, fontSize: { xs: '1.125rem', sm: '1.25rem' } }}>
                  Selamat Datang
                </Typography>
                <Typography variant="body1" color="text.secondary" paragraph sx={{ fontSize: { xs: '0.875rem', sm: '1rem' } }}>
                  Gunakan menu di sidebar untuk mengakses berbagai fitur manajemen sistem.
                </Typography>
                <Typography variant="body2" color="text.secondary" sx={{ fontSize: { xs: '0.8125rem', sm: '0.875rem' } }}>
                  Pilih menu dari sidebar untuk mulai mengelola kamera, user, cabang, dan lainnya.
                </Typography>
              </Paper>
            </Box>
          )
        ) : user?.role === 'staff' ? (
          <Box>
            <Paper elevation={2} sx={{ p: { xs: 2, sm: 3 }, mb: 3 }}>
              <Typography variant="h5" component="h1" gutterBottom fontWeight="bold" sx={{ fontSize: { xs: '1.5rem', sm: '1.75rem' } }}>
                Cabang Saya
              </Typography>
              <Typography variant="body2" color="text.secondary" sx={{ fontSize: { xs: '0.8125rem', sm: '0.875rem' } }}>
                ID Cabang: {user?.branch_id || 'N/A'}
              </Typography>
            </Paper>
            <LiveMonitor branchId={user?.branch_id} />
          </Box>
        ) : (
          <Box sx={{ textAlign: 'center', mt: 8 }}>
            <CircularProgress sx={{ mb: 2 }} />
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
