import { useState, useEffect } from 'react';
import { cameraAPI } from '../services/api';
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
} from '@mui/material';
import {
  Add,
  Settings,
  Videocam,
  Close,
  Delete,
  DeleteSweep,
} from '@mui/icons-material';

const CameraManager = ({ onSetupZona }) => {
  const [cameras, setCameras] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [showAddForm, setShowAddForm] = useState(false);
  const [newCamera, setNewCamera] = useState({ branch_name: '', rtsp_url: '' });
  const [selectedCameraId, setSelectedCameraId] = useState(null);
  const [submitting, setSubmitting] = useState(false);
  const [deleteConfirm, setDeleteConfirm] = useState(null);
  const [deleting, setDeleting] = useState(false);

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
    setSubmitting(true);
    try {
      await cameraAPI.create({
        branch_name: newCamera.branch_name,
        rtsp_url: newCamera.rtsp_url,
      });

      setNewCamera({ branch_name: '', rtsp_url: '' });
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

  if (loading) {
    return (
      <Box sx={{ display: 'flex', justifyContent: 'center', alignItems: 'center', minHeight: 400 }}>
        <CircularProgress />
      </Box>
    );
  }

  return (
    <Box>
      <Box sx={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', mb: 3 }}>
        <Typography variant="h5" component="h2" fontWeight="bold">
          Kelola Kamera
        </Typography>
        <Box sx={{ display: 'flex', gap: 1 }}>
          <Button
            variant="outlined"
            color="error"
            startIcon={<DeleteSweep />}
            onClick={handleCleanupNoZones}
            disabled={deleting || cameras.length === 0}
          >
            Hapus Tanpa Zona
          </Button>
          <Button
            variant="contained"
            startIcon={<Add />}
            onClick={() => setShowAddForm(!showAddForm)}
          >
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
            <TextField
              fullWidth
              label="Nama Cabang"
              value={newCamera.branch_name}
              onChange={(e) => setNewCamera({ ...newCamera, branch_name: e.target.value })}
              required
              placeholder="Contoh: Cabang Jakarta Pusat"
              margin="normal"
            />
            <TextField
              fullWidth
              label="RTSP URL"
              value={newCamera.rtsp_url}
              onChange={(e) => setNewCamera({ ...newCamera, rtsp_url: e.target.value })}
              required
              placeholder="Contoh: rtsp://user:pass@ip:port/stream atau 0 untuk webcam"
              margin="normal"
            />
            <Button
              type="submit"
              variant="contained"
              disabled={submitting}
              sx={{ mt: 2 }}
            >
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
        <TableContainer component={Paper} elevation={3}>
          <Table>
            <TableHead>
              <TableRow>
                <TableCell><strong>ID</strong></TableCell>
                <TableCell><strong>Nama Cabang</strong></TableCell>
                <TableCell><strong>RTSP URL</strong></TableCell>
                <TableCell align="center"><strong>Action</strong></TableCell>
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
                    <Box sx={{ display: 'flex', gap: 1, justifyContent: 'center' }}>
                      <Button
                        variant="outlined"
                        size="small"
                        startIcon={<Settings />}
                        onClick={() => handleSetupZona(camera.id)}
                      >
                        Setup Zona
                      </Button>
                      {onSetupZona && (
                        <Button
                          variant="contained"
                          size="small"
                          startIcon={<Videocam />}
                          onClick={() => onSetupZona(camera.id)}
                        >
                          Live Monitor
                        </Button>
                      )}
                      <Button
                        variant="outlined"
                        color="error"
                        size="small"
                        startIcon={<Delete />}
                        onClick={() => handleDeleteCamera(camera.id, camera.branch_name)}
                        disabled={deleting}
                      >
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

      <Dialog
        open={!!selectedCameraId}
        onClose={handleCloseZoneEditor}
        maxWidth="lg"
        fullWidth
      >
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

      <Dialog
        open={!!deleteConfirm}
        onClose={() => setDeleteConfirm(null)}
      >
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
          <Button
            onClick={() => setDeleteConfirm(null)}
            disabled={deleting}
          >
            Batal
          </Button>
          <Button
            variant="contained"
            color="error"
            onClick={confirmDelete}
            disabled={deleting}
            startIcon={deleting ? <CircularProgress size={20} /> : <Delete />}
          >
            {deleting ? 'Menghapus...' : 'Hapus'}
          </Button>
        </Box>
      </Dialog>
    </Box>
  );
};

export default CameraManager;
