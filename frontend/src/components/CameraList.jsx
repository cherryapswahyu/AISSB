import { useState, useEffect } from 'react';
import { cameraAPI } from '../services/api';
import ZoneEditor from './ZoneEditor';
import SnapshotViewer from './SnapshotViewer';
import { Box, Paper, Typography, Button, Grid, Card, CardContent, CardActions, TextField, Dialog, DialogTitle, DialogContent, DialogActions, IconButton, Alert, CircularProgress } from '@mui/material';
import { Add, Videocam, Settings, Close } from '@mui/icons-material';

const CameraList = ({ isAdmin }) => {
  const [cameras, setCameras] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [selectedCamera, setSelectedCamera] = useState(null);
  const [viewMode, setViewMode] = useState(null); // 'snapshot' atau 'zone'
  const [showAddForm, setShowAddForm] = useState(false);
  const [newCamera, setNewCamera] = useState({ branch_name: '', rtsp_url: '' });

  useEffect(() => {
    loadCameras();
  }, []);

  const loadCameras = async () => {
    try {
      setLoading(true);
      const data = await cameraAPI.getAll();
      setCameras(data);
      setError('');
    } catch (err) {
      setError('Gagal memuat daftar kamera: ' + (err.response?.data?.detail || err.message));
    } finally {
      setLoading(false);
    }
  };

  const handleAddCamera = async (e) => {
    e.preventDefault();
    try {
      await cameraAPI.create(newCamera);
      setNewCamera({ branch_name: '', rtsp_url: '' });
      setShowAddForm(false);
      loadCameras();
    } catch (err) {
      alert('Gagal menambah kamera: ' + (err.response?.data?.detail || err.message));
    }
  };

  if (loading) {
    return (
      <Box sx={{ display: 'flex', justifyContent: 'center', alignItems: 'center', minHeight: 400 }}>
        <CircularProgress />
        <Typography variant="body1" sx={{ ml: 2 }}>
          Memuat kamera...
        </Typography>
      </Box>
    );
  }

  return (
    <Box>
      <Box
        sx={{
          display: 'flex',
          justifyContent: 'space-between',
          alignItems: 'center',
          mb: 3,
          flexDirection: { xs: 'column', sm: 'row' },
          gap: { xs: 2, sm: 2 },
          flexWrap: { xs: 'nowrap', sm: 'nowrap' },
        }}>
        <Typography variant="h5" component="h2" fontWeight="bold" sx={{ flexShrink: 0 }}>
          Daftar Kamera
        </Typography>
        {isAdmin && (
          <Button variant="contained" startIcon={<Add />} onClick={() => setShowAddForm(!showAddForm)} sx={{ flexShrink: 0, whiteSpace: 'nowrap' }}>
            {showAddForm ? 'Batal' : 'Tambah Kamera'}
          </Button>
        )}
      </Box>

      {error && (
        <Alert severity="error" sx={{ mb: 2 }} onClose={() => setError('')}>
          {error}
        </Alert>
      )}

      {showAddForm && isAdmin && (
        <Paper elevation={3} sx={{ p: 3, mb: 3 }}>
          <Typography variant="h6" gutterBottom>
            Tambah Kamera Baru
          </Typography>
          <Box component="form" onSubmit={handleAddCamera} sx={{ mt: 2 }}>
            <TextField fullWidth label="Nama Cabang" value={newCamera.branch_name} onChange={(e) => setNewCamera({ ...newCamera, branch_name: e.target.value })} required placeholder="Contoh: Cabang Jakarta Pusat" margin="normal" />
            <TextField
              fullWidth
              label="RTSP URL"
              value={newCamera.rtsp_url}
              onChange={(e) => setNewCamera({ ...newCamera, rtsp_url: e.target.value })}
              required
              placeholder="Contoh: rtsp://user:pass@ip:port/stream atau 0 untuk webcam"
              margin="normal"
            />
            <Button type="submit" variant="contained" sx={{ mt: 2 }}>
              Simpan
            </Button>
          </Box>
        </Paper>
      )}

      {cameras.length === 0 ? (
        <Paper elevation={3} sx={{ p: 4, textAlign: 'center' }}>
          <Typography variant="body1" color="text.secondary">
            Belum ada kamera yang terdaftar.
          </Typography>
        </Paper>
      ) : (
        <Grid container spacing={2}>
          {cameras.map((camera) => (
            <Grid item xs={12} sm={6} md={4} key={camera.id}>
              <Card elevation={3}>
                <CardContent>
                  <Typography variant="h6" component="h3" gutterBottom>
                    {camera.branch_name}
                  </Typography>
                  <Typography variant="body2" color="text.secondary" paragraph>
                    <strong>ID:</strong> {camera.id}
                  </Typography>
                  <Typography variant="body2" color="text.secondary" paragraph>
                    <strong>RTSP URL:</strong> {camera.rtsp_url}
                  </Typography>
                </CardContent>
                <CardActions sx={{ flexDirection: 'column', gap: 1, p: 2, pt: 0 }}>
                  <Button
                    fullWidth
                    variant="outlined"
                    startIcon={<Videocam />}
                    onClick={() => {
                      setSelectedCamera(camera.id);
                      setViewMode('snapshot');
                    }}>
                    Lihat Snapshot
                  </Button>
                  {isAdmin && (
                    <Button
                      fullWidth
                      variant="outlined"
                      startIcon={<Settings />}
                      onClick={() => {
                        setSelectedCamera(camera.id);
                        setViewMode('zone');
                      }}>
                      Atur Zona
                    </Button>
                  )}
                </CardActions>
              </Card>
            </Grid>
          ))}
        </Grid>
      )}

      <Dialog
        open={!!selectedCamera}
        onClose={() => {
          setSelectedCamera(null);
          setViewMode(null);
        }}
        maxWidth="lg"
        fullWidth>
        <DialogTitle>
          <Box sx={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
            <Typography variant="h6">{viewMode === 'zone' ? 'Atur Zona' : 'Snapshot Kamera'}</Typography>
            <IconButton
              onClick={() => {
                setSelectedCamera(null);
                setViewMode(null);
              }}
              size="small">
              <Close />
            </IconButton>
          </Box>
        </DialogTitle>
        <DialogContent>
          {viewMode === 'zone' ? (
            <ZoneEditor
              cameraId={selectedCamera}
              onClose={() => {
                setSelectedCamera(null);
                setViewMode(null);
              }}
            />
          ) : (
            <SnapshotViewer cameraId={selectedCamera} />
          )}
        </DialogContent>
      </Dialog>
    </Box>
  );
};

export default CameraList;
