import { useState, useEffect, useRef } from 'react';
import { useParams } from 'react-router-dom';
import { snapshotAPI, zoneAPI } from '../services/api';
import { useAuth } from '../contexts/AuthContext';
import {
  Box,
  Typography,
  Button,
  Paper,
  Alert,
  CircularProgress,
  Dialog,
  DialogTitle,
  DialogContent,
  DialogActions,
  TextField,
  Select,
  MenuItem,
  FormControl,
  InputLabel,
  Chip,
  List,
  ListItem,
  ListItemText,
  IconButton,
  Divider,
} from '@mui/material';
import { Refresh, Delete, Info, CheckCircle, Warning } from '@mui/icons-material';

const ZoneEditor = ({ cameraId: propCameraId }) => {
  const { id } = useParams(); // Ambil ID kamera dari URL params
  // Gunakan URL params jika ada, jika tidak gunakan props (backward compatibility)
  const cameraId = id ? parseInt(id, 10) : propCameraId;
  const { user, isAdmin } = useAuth();

  const canvasRef = useRef(null);
  const [image, setImage] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [isDrawing, setIsDrawing] = useState(false);
  const [startPos, setStartPos] = useState({ x: 0, y: 0 });
  const [currentRect, setCurrentRect] = useState(null);
  const [savedZones, setSavedZones] = useState([]);
  const [showSaveDialog, setShowSaveDialog] = useState(false);
  const [zoneName, setZoneName] = useState('');
  const [zoneType, setZoneType] = useState('table');
  const [saving, setSaving] = useState(false);

  // Fetch snapshot dari backend
  useEffect(() => {
    if (cameraId) {
      loadSnapshot();
      loadSavedZones();
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [cameraId]);

  const loadSnapshot = async () => {
    try {
      setLoading(true);
      setError('');

      const url = snapshotAPI.getSnapshot(cameraId);
      const img = new Image();
      img.crossOrigin = 'anonymous';

      img.onload = () => {
        setImage(img);
        setLoading(false);
        // Draw canvas setelah image loaded
        setTimeout(() => drawCanvas(), 100);
      };

      img.onerror = () => {
        setError('Gagal memuat snapshot dari kamera');
        setLoading(false);
      };

      img.src = url;
    } catch (err) {
      setError('Gagal memuat snapshot: ' + err.message);
      setLoading(false);
    }
  };

  const loadSavedZones = async () => {
    if (!cameraId) return;
    try {
      const data = await zoneAPI.getByCamera(cameraId);
      setSavedZones(data || []);
    } catch (error) {
      console.error('Gagal memuat zones:', error);
      setError('Gagal memuat zona: ' + (error.response?.data?.detail || error.message));
    }
  };

  // Draw canvas dengan image dan rectangles
  const drawCanvas = () => {
    const canvas = canvasRef.current;
    if (!canvas || !image) return;

    const ctx = canvas.getContext('2d');

    // Set canvas size sesuai image
    canvas.width = image.width;
    canvas.height = image.height;

    // Draw image
    ctx.drawImage(image, 0, 0);

    // Draw saved zones (dalam persentase, konversi ke pixel)
    savedZones.forEach((zone) => {
      if (zone.coords && zone.coords.length === 4) {
        const [x1_pct, y1_pct, x2_pct, y2_pct] = zone.coords;
        const x1 = x1_pct * canvas.width;
        const y1 = y1_pct * canvas.height;
        const x2 = x2_pct * canvas.width;
        const y2 = y2_pct * canvas.height;

        // Tentukan warna berdasarkan tipe zona
        let strokeColor, fillColor;
        if (zone.type === 'table') {
          strokeColor = '#00ff00'; // Hijau untuk Meja
          fillColor = '#00ff00';
        } else if (zone.type === 'gorengan') {
          strokeColor = '#ffa500'; // Oranye untuk Tempat Gorengan
          fillColor = '#ffa500';
        } else if (zone.type === 'kasir') {
          strokeColor = '#0000ff'; // Biru untuk Kasir
          fillColor = '#0000ff';
        } else {
          strokeColor = '#800080'; // Ungu untuk tipe lainnya
          fillColor = '#800080';
        }

        ctx.strokeStyle = strokeColor;
        ctx.lineWidth = 2;
        ctx.strokeRect(x1, y1, x2 - x1, y2 - y1);

        // Draw label
        ctx.fillStyle = fillColor;
        ctx.font = '14px Arial';
        ctx.fillText(zone.name, x1, y1 - 5);
      }
    });

    // Draw current rectangle yang sedang digambar (border merah)
    if (currentRect) {
      ctx.strokeStyle = '#ff0000';
      ctx.lineWidth = 3;
      ctx.setLineDash([5, 5]);
      ctx.strokeRect(currentRect.x, currentRect.y, currentRect.width, currentRect.height);
      ctx.setLineDash([]);
    }
  };

  // Update canvas saat ada perubahan
  useEffect(() => {
    if (image) {
      drawCanvas();
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [image, currentRect, savedZones]);

  // Get mouse position relative to canvas
  const getMousePos = (e) => {
    const canvas = canvasRef.current;
    const rect = canvas.getBoundingClientRect();
    const scaleX = canvas.width / rect.width;
    const scaleY = canvas.height / rect.height;
    return {
      x: (e.clientX - rect.left) * scaleX,
      y: (e.clientY - rect.top) * scaleY,
    };
  };

  // Mouse down - mulai drawing
  const handleMouseDown = (e) => {
    if (showSaveDialog) return;

    const pos = getMousePos(e);
    setIsDrawing(true);
    setStartPos(pos);
    setCurrentRect({ x: pos.x, y: pos.y, width: 0, height: 0 });
  };

  // Mouse move - update rectangle saat drawing
  const handleMouseMove = (e) => {
    if (!isDrawing || !startPos) return;

    const pos = getMousePos(e);
    const x = Math.min(startPos.x, pos.x);
    const y = Math.min(startPos.y, pos.y);
    const width = Math.abs(pos.x - startPos.x);
    const height = Math.abs(pos.y - startPos.y);

    setCurrentRect({ x, y, width, height });
  };

  // Mouse up - selesai drawing, tampilkan dialog save
  const handleMouseUp = () => {
    if (!isDrawing) return;

    setIsDrawing(false);

    // Cek apakah rectangle cukup besar (min 10x10 pixel)
    if (currentRect && currentRect.width > 10 && currentRect.height > 10) {
      setShowSaveDialog(true);
    } else {
      setCurrentRect(null);
    }
  };

  // Handle save zone
  const handleSaveZone = async () => {
    if (!zoneName.trim() || !currentRect) {
      alert('Nama zona harus diisi dan zona harus digambar terlebih dahulu');
      return;
    }

    if (!cameraId) {
      alert('Camera ID tidak valid');
      return;
    }

    // Cek apakah user adalah admin (hanya admin yang bisa save zone)
    if (!isAdmin) {
      const errorMsg = 'Hanya Admin yang dapat menyimpan zona. Role Anda: ' + (user?.role || 'Unknown');
      setError(errorMsg);
      alert(errorMsg);
      return;
    }

    const canvas = canvasRef.current;
    if (!canvas) {
      alert('Canvas tidak tersedia');
      return;
    }

    setSaving(true);
    setError('');

    // Konversi koordinat pixel ke persentase (0.0 - 1.0)
    const x1_pct = currentRect.x / canvas.width;
    const y1_pct = currentRect.y / canvas.height;
    const x2_pct = (currentRect.x + currentRect.width) / canvas.width;
    const y2_pct = (currentRect.y + currentRect.height) / canvas.height;

    try {
      console.log('Saving zone:', {
        camera_id: cameraId,
        name: zoneName.trim(),
        type: zoneType,
        coords: [x1_pct, y1_pct, x2_pct, y2_pct],
      });

      const result = await zoneAPI.create({
        camera_id: cameraId,
        name: zoneName.trim(),
        type: zoneType,
        coords: [x1_pct, y1_pct, x2_pct, y2_pct],
      });

      console.log('Zone saved successfully:', result);

      // Reset form dan reload zones
      setZoneName('');
      setZoneType('table');
      setCurrentRect(null);
      setShowSaveDialog(false);
      await loadSavedZones();

      // Redraw canvas setelah reload zones
      setTimeout(() => {
        if (image) {
          drawCanvas();
        }
      }, 100);
    } catch (error) {
      console.error('Error saving zone:', error);
      const errorMessage = error.response?.data?.detail || error.message || 'Gagal menyimpan zona';
      setError(errorMessage);
      alert('Gagal menyimpan zona: ' + errorMessage);
    } finally {
      setSaving(false);
    }
  };

  const handleCancelSave = () => {
    setCurrentRect(null);
    setShowSaveDialog(false);
    setZoneName('');
    setZoneType('table');
    setError('');
    setSaving(false);
  };

  const handleDeleteZone = async (zoneId) => {
    if (!window.confirm('Apakah Anda yakin ingin menghapus zona ini?')) {
      return;
    }

    try {
      await zoneAPI.delete(zoneId);
      // Reload zones setelah hapus
      await loadSavedZones();
      // Redraw canvas
      setTimeout(() => drawCanvas(), 100);
    } catch (error) {
      console.error('Gagal menghapus zona:', error);
      alert('Gagal menghapus zona. Silakan coba lagi.');
    }
  };

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
        <Typography variant="h6" component="h3" fontWeight="bold" sx={{ flexShrink: 0 }}>
          Atur Zona - Kamera ID: {cameraId}
        </Typography>
        <Button variant="outlined" startIcon={<Refresh />} onClick={loadSnapshot} disabled={loading} sx={{ flexShrink: 0, whiteSpace: 'nowrap' }}>
          Refresh Snapshot
        </Button>
      </Box>

      <Paper elevation={2} sx={{ p: 2, mb: 2, bgcolor: 'info.light', color: 'info.contrastText' }}>
        <Box sx={{ display: 'flex', alignItems: 'center', gap: 1, mb: 1 }}>
          <Info />
          <Typography variant="body2" fontWeight="bold">
            Instruksi:
          </Typography>
        </Box>
        <Typography variant="body2" sx={{ mb: 1 }}>
          Klik dan drag pada gambar untuk membuat zona baru
        </Typography>
        <Box sx={{ display: 'flex', gap: 2, flexWrap: 'wrap' }}>
          <Chip label="Hijau = Meja" size="small" sx={{ bgcolor: '#00ff00', color: 'white' }} />
          <Chip label="Oranye = Tempat Gorengan" size="small" sx={{ bgcolor: '#ffa500', color: 'white' }} />
          <Chip label="Biru = Kasir" size="small" sx={{ bgcolor: '#0000ff', color: 'white' }} />
        </Box>
      </Paper>

      {loading && (
        <Box sx={{ display: 'flex', justifyContent: 'center', alignItems: 'center', minHeight: 200 }}>
          <CircularProgress />
          <Typography variant="body1" sx={{ ml: 2 }}>
            Memuat snapshot...
          </Typography>
        </Box>
      )}

      {error && (
        <Alert severity="error" sx={{ mb: 2 }} onClose={() => setError('')}>
          {error}
        </Alert>
      )}

      <Paper elevation={2} sx={{ p: 2, display: 'flex', justifyContent: 'center', bgcolor: '#000' }}>
        <Box
          component="canvas"
          ref={canvasRef}
          onMouseDown={handleMouseDown}
          onMouseMove={handleMouseMove}
          onMouseUp={handleMouseUp}
          sx={{
            border: '1px solid #ddd',
            cursor: 'crosshair',
            maxWidth: '100%',
            height: 'auto',
            display: image ? 'block' : 'none',
          }}
        />
      </Paper>

      {/* Save Dialog */}
      <Dialog open={showSaveDialog} onClose={handleCancelSave} maxWidth="sm" fullWidth>
        <DialogTitle>Simpan Zona Baru</DialogTitle>
        <DialogContent>
          {error && (
            <Alert severity="error" sx={{ mb: 2 }} onClose={() => setError('')}>
              {error}
            </Alert>
          )}
          {!currentRect && (
            <Alert severity="warning" icon={<Warning />} sx={{ mb: 2 }}>
              Zona belum digambar. Silakan gambar zona terlebih dahulu dengan klik dan drag pada canvas.
            </Alert>
          )}
          {currentRect && (
            <Alert severity="success" icon={<CheckCircle />} sx={{ mb: 2 }}>
              <Typography variant="body2">
                Zona sudah digambar ({Math.round(currentRect.width)}x{Math.round(currentRect.height)} px)
              </Typography>
              <Typography variant="caption" display="block" sx={{ mt: 0.5 }}>
                Camera ID: {cameraId} | User: {user?.username} ({user?.role})
              </Typography>
            </Alert>
          )}
          {!isAdmin && (
            <Alert severity="error" sx={{ mb: 2 }}>
              Hanya Admin yang dapat menyimpan zona. Role Anda: {user?.role || 'Unknown'}
            </Alert>
          )}
          <TextField
            fullWidth
            label="Nama Zona"
            value={zoneName}
            onChange={(e) => {
              setZoneName(e.target.value);
              setError('');
            }}
            placeholder="Contoh: Meja 1"
            autoFocus
            disabled={saving}
            margin="normal"
            required
          />
          <FormControl fullWidth margin="normal" required>
            <InputLabel>Tipe</InputLabel>
            <Select value={zoneType} label="Tipe" onChange={(e) => setZoneType(e.target.value)} disabled={saving}>
              <MenuItem value="table">Meja</MenuItem>
              <MenuItem value="gorengan">Tempat Gorengan</MenuItem>
              <MenuItem value="kasir">Kasir</MenuItem>
              <MenuItem value="dapur">Dapur</MenuItem>
            </Select>
          </FormControl>
        </DialogContent>
        <DialogActions>
          <Button onClick={handleCancelSave} disabled={saving}>
            Batal
          </Button>
          <Button onClick={handleSaveZone} variant="contained" disabled={!zoneName.trim() || saving || !currentRect || !isAdmin} startIcon={saving ? <CircularProgress size={16} /> : null}>
            {saving ? 'Menyimpan...' : 'Simpan'}
          </Button>
        </DialogActions>
      </Dialog>

      {/* List Saved Zones */}
      {savedZones.length > 0 && (
        <Paper elevation={2} sx={{ p: 2, mt: 3 }}>
          <Typography variant="h6" gutterBottom>
            Zona yang Tersimpan
          </Typography>
          <List>
            {savedZones.map((zone) => (
              <ListItem
                key={zone.id}
                sx={{
                  border: '1px solid',
                  borderColor: 'divider',
                  borderRadius: 1,
                  mb: 1,
                  display: 'flex',
                  justifyContent: 'space-between',
                  alignItems: 'center',
                }}>
                <ListItemText
                  primary={
                    <Box sx={{ display: 'flex', alignItems: 'center', gap: 1, flexWrap: 'wrap' }}>
                      <Typography variant="body1" fontWeight="bold">
                        {zone.name}
                      </Typography>
                      <Chip label={zone.type} size="small" color="primary" variant="outlined" />
                    </Box>
                  }
                  secondary={
                    <Typography variant="caption" color="text.secondary">
                      Koordinat: [{zone.coords?.map((c, i) => (i > 0 ? ', ' : '') + c.toFixed(3)).join('')}]
                    </Typography>
                  }
                />
                <IconButton onClick={() => handleDeleteZone(zone.id)} color="error" size="small" title="Hapus zona" sx={{ ml: 2 }}>
                  <Delete />
                </IconButton>
              </ListItem>
            ))}
          </List>
        </Paper>
      )}
    </Box>
  );
};

export default ZoneEditor;
