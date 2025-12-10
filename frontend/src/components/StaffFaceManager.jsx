import React, { useState, useEffect } from 'react';
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
  IconButton,
  Dialog,
  DialogTitle,
  DialogContent,
  DialogActions,
  TextField,
  Alert,
  CircularProgress,
  Grid,
  Card,
  CardMedia,
  CardContent,
  CardActions,
} from '@mui/material';
import { Upload, Delete, Refresh, Person, CloudUpload, CheckCircle, Error as ErrorIcon } from '@mui/icons-material';
import { staffFaceAPI } from '../services/api';

const StaffFaceManager = () => {
  const [staffFaces, setStaffFaces] = useState([]);
  const [loading, setLoading] = useState(false);
  const [uploading, setUploading] = useState(false);
  const [error, setError] = useState(null);
  const [success, setSuccess] = useState(null);
  const [uploadDialogOpen, setUploadDialogOpen] = useState(false);
  const [selectedFile, setSelectedFile] = useState(null);
  const [preview, setPreview] = useState(null);
  const [staffName, setStaffName] = useState('');
  const [deleteDialogOpen, setDeleteDialogOpen] = useState(false);
  const [fileToDelete, setFileToDelete] = useState(null);

  useEffect(() => {
    loadStaffFaces();
  }, []);

  const loadStaffFaces = async () => {
    setLoading(true);
    setError(null);
    try {
      const data = await staffFaceAPI.list();
      setStaffFaces(data.staff_faces || []);
    } catch (err) {
      setError(err.response?.data?.detail || 'Gagal memuat daftar staff');
    } finally {
      setLoading(false);
    }
  };

  const handleFileSelect = (event) => {
    const file = event.target.files[0];
    if (file) {
      // Validasi ekstensi
      const allowedTypes = ['image/jpeg', 'image/jpg', 'image/png'];
      if (!allowedTypes.includes(file.type)) {
        setError('Format file tidak didukung. Gunakan JPG atau PNG');
        return;
      }

      // Validasi ukuran (max 5MB)
      if (file.size > 5 * 1024 * 1024) {
        setError('Ukuran file terlalu besar. Maksimal 5MB');
        return;
      }

      setSelectedFile(file);
      setError(null);

      // Auto-fill nama staff dari filename jika belum diisi
      if (!staffName) {
        const nameFromFile = file.name.replace(/\.[^/.]+$/, '').split('_')[0];
        setStaffName(nameFromFile);
      }

      // Preview gambar
      const reader = new FileReader();
      reader.onloadend = () => {
        setPreview(reader.result);
      };
      reader.readAsDataURL(file);
    }
  };

  const handleUpload = async () => {
    if (!selectedFile) {
      setError('Pilih file terlebih dahulu');
      return;
    }

    if (!staffName || staffName.trim() === '') {
      setError('Masukkan nama staff terlebih dahulu');
      return;
    }

    setUploading(true);
    setError(null);
    setSuccess(null);

    try {
      const result = await staffFaceAPI.upload(selectedFile, staffName.trim());
      setSuccess(`Foto staff "${result.staff_name}" berhasil diupload!`);
      setUploadDialogOpen(false);
      setSelectedFile(null);
      setPreview(null);
      setStaffName('');
      await loadStaffFaces();

      // Auto reload known faces
      try {
        await staffFaceAPI.reload();
      } catch (err) {
        console.warn('Failed to reload faces:', err);
      }
    } catch (err) {
      setError(err.response?.data?.detail || 'Gagal upload foto');
    } finally {
      setUploading(false);
    }
  };

  const handleDeleteClick = (filename) => {
    setFileToDelete(filename);
    setDeleteDialogOpen(true);
  };

  const handleDeleteConfirm = async () => {
    if (!fileToDelete) return;

    setLoading(true);
    setError(null);
    setSuccess(null);

    try {
      await staffFaceAPI.delete(fileToDelete);
      setSuccess('Foto staff berhasil dihapus');
      setDeleteDialogOpen(false);
      setFileToDelete(null);
      await loadStaffFaces();

      // Auto reload known faces
      try {
        await staffFaceAPI.reload();
      } catch (err) {
        console.warn('Failed to reload faces:', err);
      }
    } catch (err) {
      setError(err.response?.data?.detail || 'Gagal menghapus foto');
    } finally {
      setLoading(false);
    }
  };

  const handleReload = async () => {
    setLoading(true);
    setError(null);
    setSuccess(null);

    try {
      const result = await staffFaceAPI.reload();
      setSuccess(`Staff faces berhasil di-reload. Total: ${result.total_staff} staff`);
      await loadStaffFaces();
    } catch (err) {
      setError(err.response?.data?.detail || 'Gagal reload staff faces');
    } finally {
      setLoading(false);
    }
  };

  return (
    <Box sx={{ p: 3 }}>
      <Paper sx={{ p: 3 }}>
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
          <Typography variant="h5" component="h1" sx={{ mb: { xs: 0, sm: 0 }, flexShrink: 0 }}>
            <Person sx={{ mr: 1, verticalAlign: 'middle' }} />
            Manajemen Foto Staff
          </Typography>
          <Box sx={{ display: 'flex', gap: 1, flexWrap: { xs: 'wrap', sm: 'nowrap' }, width: { xs: '100%', sm: 'auto' }, justifyContent: { xs: 'flex-end', sm: 'flex-start' }, flexShrink: 0, minWidth: 0 }}>
            <Button variant="outlined" startIcon={<Refresh />} onClick={handleReload} disabled={loading} size="medium" sx={{ flexShrink: 0, whiteSpace: 'nowrap' }}>
              Reload
            </Button>
            <Button variant="contained" startIcon={<Upload />} onClick={() => setUploadDialogOpen(true)} size="medium" sx={{ flexShrink: 0, whiteSpace: 'nowrap' }}>
              Upload Foto Staff
            </Button>
          </Box>
        </Box>

        {error && (
          <Alert severity="error" sx={{ mb: 2 }} onClose={() => setError(null)}>
            {error}
          </Alert>
        )}

        {success && (
          <Alert severity="success" sx={{ mb: 2 }} onClose={() => setSuccess(null)}>
            {success}
          </Alert>
        )}

        {loading && !uploading ? (
          <Box sx={{ display: 'flex', justifyContent: 'center', p: 3 }}>
            <CircularProgress />
          </Box>
        ) : (
          <>
            {staffFaces.length === 0 ? (
              <Box sx={{ textAlign: 'center', p: 5 }}>
                <Person sx={{ fontSize: 64, color: 'text.secondary', mb: 2 }} />
                <Typography variant="h6" color="text.secondary" gutterBottom>
                  Belum ada foto staff terdaftar
                </Typography>
                <Typography variant="body2" color="text.secondary" sx={{ mb: 3 }}>
                  Upload foto staff untuk memulai face recognition
                </Typography>
                <Button variant="contained" startIcon={<CloudUpload />} onClick={() => setUploadDialogOpen(true)}>
                  Upload Foto Pertama
                </Button>
              </Box>
            ) : (
              <Grid container spacing={2}>
                {staffFaces.map((staff) => (
                  <Grid item xs={12} sm={6} md={4} key={staff.filename}>
                    <Card>
                      <CardMedia
                        component="img"
                        height="200"
                        image={`http://localhost:8000/staff-faces/${encodeURIComponent(staff.filename)}`}
                        alt={staff.staff_name}
                        sx={{ objectFit: 'cover' }}
                        onError={(e) => {
                          e.target.src =
                            'data:image/svg+xml;base64,PHN2ZyB3aWR0aD0iMjAwIiBoZWlnaHQ9IjIwMCIgeG1sbnM9Imh0dHA6Ly93d3cudzMub3JnLzIwMDAvc3ZnIj48cmVjdCB3aWR0aD0iMjAwIiBoZWlnaHQ9IjIwMCIgZmlsbD0iI2RkZCIvPjx0ZXh0IHg9IjUwJSIgeT0iNTAlIiBmb250LWZhbWlseT0iQXJpYWwiIGZvbnQtc2l6ZT0iMTQiIGZpbGw9IiM5OTkiIHRleHQtYW5jaG9yPSJtaWRkbGUiIGR5PSIuM2VtIj5ObyBJbWFnZTwvdGV4dD48L3N2Zz4=';
                        }}
                      />
                      <CardContent>
                        <Typography variant="h6" component="div">
                          {staff.staff_name}
                        </Typography>
                        <Typography variant="body2" color="text.secondary">
                          {staff.filename}
                        </Typography>
                        <Typography variant="caption" color="text.secondary">
                          {staff.size_mb} MB
                        </Typography>
                      </CardContent>
                      <CardActions>
                        <IconButton color="error" onClick={() => handleDeleteClick(staff.filename)} size="small">
                          <Delete />
                        </IconButton>
                      </CardActions>
                    </Card>
                  </Grid>
                ))}
              </Grid>
            )}
          </>
        )}
      </Paper>

      {/* Upload Dialog */}
      <Dialog open={uploadDialogOpen} onClose={() => !uploading && setUploadDialogOpen(false)} maxWidth="sm" fullWidth>
        <DialogTitle>Upload Foto Staff</DialogTitle>
        <DialogContent>
          <Box sx={{ mt: 2 }}>
            <TextField fullWidth label="Nama Staff" value={staffName} onChange={(e) => setStaffName(e.target.value)} placeholder="Contoh: Budi Santoso" required sx={{ mb: 2 }} disabled={uploading} />

            <input accept="image/jpeg,image/jpg,image/png" style={{ display: 'none' }} id="upload-file" type="file" onChange={handleFileSelect} />
            <label htmlFor="upload-file">
              <Button variant="outlined" component="span" startIcon={<CloudUpload />} fullWidth sx={{ mb: 2 }} disabled={uploading}>
                Pilih Foto
              </Button>
            </label>

            {preview && (
              <Box sx={{ mt: 2, textAlign: 'center' }}>
                <img
                  src={preview}
                  alt="Preview"
                  style={{
                    maxWidth: '100%',
                    maxHeight: '300px',
                    borderRadius: '8px',
                  }}
                />
                {selectedFile && (
                  <Typography variant="body2" color="text.secondary" sx={{ mt: 1 }}>
                    {selectedFile.name} ({(selectedFile.size / 1024).toFixed(2)} KB)
                  </Typography>
                )}
              </Box>
            )}

            <Alert severity="info" sx={{ mt: 2 }}>
              <Typography variant="body2">
                <strong>Tips:</strong>
                <br />• Masukkan nama staff yang akan digunakan untuk identifikasi
                <br />• Gunakan foto dengan wajah jelas dan terlihat penuh
                <br />• Satu foto hanya boleh berisi satu wajah
                <br />• Format: JPG atau PNG (maksimal 5MB)
              </Typography>
            </Alert>
          </Box>
        </DialogContent>
        <DialogActions>
          <Button
            onClick={() => {
              setUploadDialogOpen(false);
              setSelectedFile(null);
              setPreview(null);
              setStaffName('');
            }}
            disabled={uploading}>
            Batal
          </Button>
          <Button onClick={handleUpload} variant="contained" disabled={!selectedFile || !staffName || staffName.trim() === '' || uploading} startIcon={uploading ? <CircularProgress size={20} /> : <Upload />}>
            {uploading ? 'Uploading...' : 'Upload'}
          </Button>
        </DialogActions>
      </Dialog>

      {/* Delete Confirmation Dialog */}
      <Dialog open={deleteDialogOpen} onClose={() => setDeleteDialogOpen(false)}>
        <DialogTitle>Hapus Foto Staff?</DialogTitle>
        <DialogContent>
          <Typography>
            Apakah Anda yakin ingin menghapus foto <strong>{fileToDelete}</strong>?
            <br />
            Tindakan ini tidak dapat dibatalkan.
          </Typography>
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setDeleteDialogOpen(false)}>Batal</Button>
          <Button onClick={handleDeleteConfirm} color="error" variant="contained">
            Hapus
          </Button>
        </DialogActions>
      </Dialog>
    </Box>
  );
};

export default StaffFaceManager;
