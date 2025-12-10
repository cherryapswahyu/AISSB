import { useState, useEffect } from 'react';
import { cameraAPI, branchAPI, analysisAPI } from '../services/api';
import ZoneEditor from './ZoneEditor';
import {
  Box,
  Paper,
  Typography,
  Button,
  Table,
  TableBody,
  TableCell,
  TableContainer,
  TableHead,
  TableRow,
  TextField,
  Dialog,
  DialogTitle,
  DialogContent,
  IconButton,
  Alert,
  CircularProgress,
  Chip,
  MenuItem,
  Select,
  FormControl,
  InputLabel,
} from '@mui/material';
import { Add, Settings, Videocam, Close, Delete, DeleteSweep, Analytics, PlayArrow } from '@mui/icons-material';

const CameraManager = ({ onSetupZona }) => {
  const [cameras, setCameras] = useState([]);
  const [branches, setBranches] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [showAddForm, setShowAddForm] = useState(false);
  const [newCamera, setNewCamera] = useState({ branch_id: '', rtsp_url: '' });
  const [selectedCameraId, setSelectedCameraId] = useState(null);
  const [submitting, setSubmitting] = useState(false);
  const [deleteConfirm, setDeleteConfirm] = useState(null);
  const [deleting, setDeleting] = useState(false);
  const [analyzingCamera, setAnalyzingCamera] = useState(null);

  useEffect(() => {
    loadCameras();
    loadBranches();
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

  const loadBranches = async () => {
    try {
      const data = await branchAPI.getAll();
      setBranches(data);
    } catch (err) {
      console.error('Gagal memuat daftar cabang:', err);
    }
  };

  const handleAddCamera = async (e) => {
    e.preventDefault();
    if (!newCamera.branch_id) {
      setError('Pilih cabang terlebih dahulu');
      return;
    }

    setSubmitting(true);
    try {
      await cameraAPI.create({
        branch_id: parseInt(newCamera.branch_id),
        rtsp_url: newCamera.rtsp_url,
      });

      setNewCamera({ branch_id: '', rtsp_url: '' });
      setShowAddForm(false);
      loadCameras();
    } catch (err) {
      setError('Gagal menambah kamera: ' + (err.response?.data?.detail || err.message));
    } finally {
      setSubmitting(false);
    }
  };

  const handleSetupZona = (cameraId) => {
    setSelectedCameraId(cameraId);
  };

  const handleCloseZoneEditor = () => {
    setSelectedCameraId(null);
  };

  const handleDeleteCamera = async (cameraId, branchName) => {
    setDeleteConfirm({ id: cameraId, name: branchName });
  };

  const confirmDelete = async () => {
    if (!deleteConfirm) return;

    setDeleting(true);
    try {
      await cameraAPI.delete(deleteConfirm.id);
      setDeleteConfirm(null);
      loadCameras();
    } catch (err) {
      setError('Gagal menghapus kamera: ' + (err.response?.data?.detail || err.message));
    } finally {
      setDeleting(false);
    }
  };

  const handleCleanupNoZones = async () => {
    if (!window.confirm('Yakin ingin menghapus semua kamera yang belum memiliki zona? Tindakan ini tidak dapat dibatalkan.')) {
      return;
    }

    setDeleting(true);
    try {
      const result = await cameraAPI.deleteWithoutZones();
      alert(`Berhasil menghapus ${result.deleted_count} kamera tanpa zona.`);
      loadCameras();
    } catch (err) {
      setError('Gagal menghapus kamera: ' + (err.response?.data?.detail || err.message));
    } finally {
      setDeleting(false);
    }
  };

  const handleAnalyzeCamera = async (cameraId) => {
    setAnalyzingCamera(cameraId);
    try {
      const result = await analysisAPI.analyzeCamera(cameraId);
      alert(`Analisis selesai!\nBilling events: ${result.billing_events_count}\nAlerts: ${result.alerts_count}`);
    } catch (err) {
      alert('Gagal menjalankan analisis: ' + (err.response?.data?.detail || err.message));
    } finally {
      setAnalyzingCamera(null);
    }
  };

  if (loading) {
    return (
      <Box sx={{ display: 'flex', justifyContent: 'center', alignItems: 'center', minHeight: 400 }}>
        <CircularProgress />
      </Box>
    );
  }

  return (
    <Box>
      <Box
        sx={{
          display: 'flex',
          justifyContent: 'space-between',
          alignItems: { xs: 'flex-start', sm: 'center' },
          mb: 3,
          flexDirection: { xs: 'column', sm: 'row' },
          gap: { xs: 2, sm: 2 },
          flexWrap: { xs: 'nowrap', sm: 'nowrap' },
        }}>
        <Typography variant="h5" component="h2" fontWeight="bold" sx={{ mb: { xs: 0, sm: 0 }, flexShrink: 0 }}>
          Kelola Kamera
        </Typography>
        <Box sx={{ display: 'flex', gap: 1, flexWrap: { xs: 'wrap', sm: 'nowrap' }, width: { xs: '100%', sm: 'auto' }, justifyContent: { xs: 'flex-end', sm: 'flex-start' }, flexShrink: 0, minWidth: 0 }}>
          <Button variant="outlined" color="error" startIcon={<DeleteSweep />} onClick={handleCleanupNoZones} disabled={deleting || cameras.length === 0} size="medium" sx={{ flexShrink: 0, whiteSpace: 'nowrap' }}>
            Hapus Tanpa Zona
          </Button>
          <Button variant="contained" startIcon={<Add />} onClick={() => setShowAddForm(!showAddForm)} size="medium" sx={{ flexShrink: 0, whiteSpace: 'nowrap' }}>
            {showAddForm ? 'Batal' : 'Tambah Kamera'}
          </Button>
        </Box>
      </Box>

      {error && (
        <Alert severity="error" sx={{ mb: 2 }} onClose={() => setError('')}>
          {error}
        </Alert>
      )}

      {showAddForm && (
        <Paper elevation={3} sx={{ p: 3, mb: 3 }}>
          <Typography variant="h6" gutterBottom>
            Tambah Kamera Baru
          </Typography>
          <Box component="form" onSubmit={handleAddCamera} sx={{ mt: 2 }}>
            <FormControl fullWidth margin="normal" required>
              <InputLabel>Nama Cabang</InputLabel>
              <Select value={newCamera.branch_id} label="Nama Cabang" onChange={(e) => setNewCamera({ ...newCamera, branch_id: e.target.value })}>
                {branches.length === 0 ? (
                  <MenuItem disabled>Belum ada cabang. Tambah cabang terlebih dahulu.</MenuItem>
                ) : (
                  branches.map((branch) => (
                    <MenuItem key={branch.id} value={branch.id}>
                      {branch.name}
                    </MenuItem>
                  ))
                )}
              </Select>
            </FormControl>
            <TextField
              fullWidth
              label="RTSP URL"
              value={newCamera.rtsp_url}
              onChange={(e) => setNewCamera({ ...newCamera, rtsp_url: e.target.value })}
              required
              placeholder="Contoh: rtsp://user:pass@ip:port/stream atau 0 untuk webcam"
              margin="normal"
            />
            <Button type="submit" variant="contained" disabled={submitting || !newCamera.branch_id} sx={{ mt: 2 }}>
              {submitting ? <CircularProgress size={20} /> : 'Simpan'}
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
        <TableContainer component={Paper} elevation={3} sx={{ maxHeight: 'calc(100vh - 300px)', overflow: 'auto' }}>
          <Table stickyHeader>
            <TableHead>
              <TableRow>
                <TableCell>
                  <strong>ID</strong>
                </TableCell>
                <TableCell>
                  <strong>Nama Cabang</strong>
                </TableCell>
                <TableCell>
                  <strong>RTSP URL</strong>
                </TableCell>
                <TableCell align="center">
                  <strong>Action</strong>
                </TableCell>
              </TableRow>
            </TableHead>
            <TableBody>
              {cameras.map((camera) => (
                <TableRow key={camera.id} hover>
                  <TableCell>{camera.id}</TableCell>
                  <TableCell>{camera.branch_name}</TableCell>
                  <TableCell>
                    <Chip label={camera.rtsp_url} size="small" variant="outlined" />
                  </TableCell>
                  <TableCell>
                    <Box sx={{ display: 'flex', gap: 1, justifyContent: 'center', flexWrap: 'wrap' }}>
                      <Button variant="outlined" size="small" startIcon={<Settings />} onClick={() => handleSetupZona(camera.id)}>
                        Setup Zona
                      </Button>
                      {onSetupZona && (
                        <Button variant="contained" size="small" startIcon={<Videocam />} onClick={() => onSetupZona(camera.id)}>
                          Live Monitor
                        </Button>
                      )}
                      <Button
                        variant="outlined"
                        color="success"
                        size="small"
                        startIcon={analyzingCamera === camera.id ? <CircularProgress size={16} /> : <Analytics />}
                        onClick={() => handleAnalyzeCamera(camera.id)}
                        disabled={analyzingCamera === camera.id || deleting}>
                        {analyzingCamera === camera.id ? 'Analisis...' : 'Analisis'}
                      </Button>
                      <Button variant="outlined" color="error" size="small" startIcon={<Delete />} onClick={() => handleDeleteCamera(camera.id, camera.branch_name)} disabled={deleting}>
                        Hapus
                      </Button>
                    </Box>
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </TableContainer>
      )}

      <Dialog open={!!selectedCameraId} onClose={handleCloseZoneEditor} maxWidth="lg" fullWidth>
        <DialogTitle>
          <Box sx={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
            <Typography variant="h6">Setup Zona - Kamera ID: {selectedCameraId}</Typography>
            <IconButton onClick={handleCloseZoneEditor} size="small">
              <Close />
            </IconButton>
          </Box>
        </DialogTitle>
        <DialogContent>
          <ZoneEditor cameraId={selectedCameraId} />
        </DialogContent>
      </Dialog>

      <Dialog open={!!deleteConfirm} onClose={() => setDeleteConfirm(null)}>
        <DialogTitle>Konfirmasi Hapus Kamera</DialogTitle>
        <DialogContent>
          <Typography>
            Yakin ingin menghapus kamera <strong>"{deleteConfirm?.name}"</strong> (ID: {deleteConfirm?.id})?
            <br />
            <br />
            Tindakan ini akan menghapus kamera beserta semua zona yang terkait. Tindakan ini tidak dapat dibatalkan.
          </Typography>
        </DialogContent>
        <Box sx={{ p: 2, display: 'flex', gap: 1, justifyContent: 'flex-end' }}>
          <Button onClick={() => setDeleteConfirm(null)} disabled={deleting}>
            Batal
          </Button>
          <Button variant="contained" color="error" onClick={confirmDelete} disabled={deleting} startIcon={deleting ? <CircularProgress size={20} /> : <Delete />}>
            {deleting ? 'Menghapus...' : 'Hapus'}
          </Button>
        </Box>
      </Dialog>
    </Box>
  );
};

export default CameraManager;
