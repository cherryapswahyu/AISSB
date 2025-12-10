import { useState, useEffect } from 'react';
import { snapshotAPI } from '../services/api';
import { Box, Typography, Button, Paper, CircularProgress, Alert } from '@mui/material';
import { Refresh, Videocam } from '@mui/icons-material';

const SnapshotViewer = ({ cameraId }) => {
  const [imageUrl, setImageUrl] = useState('');
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');

  const loadSnapshot = () => {
    setLoading(true);
    setError('');
    // Tambahkan timestamp untuk menghindari cache
    const url = snapshotAPI.getSnapshot(cameraId);
    setImageUrl(url);

    // Preload image untuk handle error
    const img = new Image();
    img.onload = () => {
      setLoading(false);
    };
    img.onerror = () => {
      setLoading(false);
      setError('Gagal memuat snapshot dari kamera');
    };
    img.src = url;
  };

  useEffect(() => {
    if (cameraId) {
      loadSnapshot();
      // Auto refresh setiap 5 detik
      const interval = setInterval(loadSnapshot, 5000);
      return () => clearInterval(interval);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [cameraId]);

  return (
    <Box sx={{ p: 2 }}>
      <Box sx={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', mb: 2 }}>
        <Typography variant="h6" component="h3" sx={{ display: 'flex', alignItems: 'center', gap: 1 }}>
          <Videocam />
          Snapshot Kamera ID: {cameraId}
        </Typography>
        <Button variant="outlined" startIcon={<Refresh />} onClick={loadSnapshot} disabled={loading}>
          Refresh
        </Button>
      </Box>

      <Paper elevation={2} sx={{ p: 2, textAlign: 'center', bgcolor: '#000', minHeight: 300, display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
        {loading && (
          <Box>
            <CircularProgress sx={{ color: 'white', mb: 2 }} />
            <Typography variant="body2" sx={{ color: 'white' }}>
              Memuat snapshot...
            </Typography>
          </Box>
        )}
        {error && (
          <Alert severity="error" sx={{ maxWidth: 600, mx: 'auto' }}>
            {error}
          </Alert>
        )}
        {imageUrl && !error && (
          <Box
            component="img"
            src={imageUrl}
            alt={`Snapshot kamera ${cameraId}`}
            onLoad={() => setLoading(false)}
            onError={() => {
              setLoading(false);
              setError('Gagal memuat snapshot dari kamera');
            }}
            sx={{
              maxWidth: '100%',
              height: 'auto',
              display: 'block',
              mx: 'auto',
            }}
          />
        )}
      </Paper>
    </Box>
  );
};

export default SnapshotViewer;
