import { useState, useEffect } from 'react';
import { cameraAPI, zoneAPI, billingAPI, branchAPI } from '../services/api';
import {
  Box,
  Paper,
  Typography,
  Button,
  Grid,
  Card,
  CardContent,
  Table,
  TableBody,
  TableCell,
  TableContainer,
  TableHead,
  TableRow,
  Chip,
  CircularProgress,
  Alert,
  Dialog,
  DialogTitle,
  DialogContent,
  IconButton,
  Divider,
  TextField,
} from '@mui/material';
import { Store, CameraAlt, LocationOn, TrendingUp, Close, Visibility, Add } from '@mui/icons-material';

const BranchManager = () => {
  const [branches, setBranches] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [selectedBranch, setSelectedBranch] = useState(null);
  const [branchDetails, setBranchDetails] = useState(null);
  const [loadingDetails, setLoadingDetails] = useState(false);
  const [showAddForm, setShowAddForm] = useState(false);
  const [newBranch, setNewBranch] = useState({ name: '', address: '', phone: '' });
  const [submitting, setSubmitting] = useState(false);

  useEffect(() => {
    loadBranches();
  }, []);

  const loadBranches = async () => {
    try {
      setLoading(true);
      // Load master branches
      const branchesData = await branchAPI.getAll();

      // Load cameras untuk statistik
      const cameras = await cameraAPI.getAll();

      // Group cameras by branch_id
      const branchMap = {};
      branchesData.forEach((branch) => {
        branchMap[branch.id] = {
          ...branch,
          cameras: [],
          totalZones: 0,
          totalBilling: 0,
        };
      });

      cameras.forEach((cam) => {
        const branchId = cam.branch_id;
        if (branchMap[branchId]) {
          branchMap[branchId].cameras.push(cam);
        }
      });

      // Load zones untuk setiap kamera
      for (const branchId in branchMap) {
        const branch = branchMap[branchId];
        for (const cam of branch.cameras) {
          try {
            const zones = await zoneAPI.getByCamera(cam.id);
            branch.totalZones += zones.length;
          } catch (err) {
            console.error(`Error loading zones for camera ${cam.id}:`, err);
          }
        }
      }

      setBranches(Object.values(branchMap));
      setError('');
    } catch (err) {
      setError('Gagal memuat daftar cabang: ' + (err.response?.data?.detail || err.message));
    } finally {
      setLoading(false);
    }
  };

  const loadBranchDetails = async (branchName) => {
    setLoadingDetails(true);
    try {
      const cameras = await cameraAPI.getAll();
      const branchCameras = cameras.filter((cam) => cam.branch_name === branchName);

      const details = {
        name: branchName,
        cameras: [],
      };

      for (const cam of branchCameras) {
        try {
          const zones = await zoneAPI.getByCamera(cam.id);
          const billing = await billingAPI.getLiveBilling(cam.id);

          details.cameras.push({
            ...cam,
            zones: zones,
            zonesCount: zones.length,
            billingCount: billing.length,
            recentBilling: billing.slice(0, 5), // 5 terakhir
          });
        } catch (err) {
          console.error(`Error loading details for camera ${cam.id}:`, err);
          details.cameras.push({
            ...cam,
            zones: [],
            zonesCount: 0,
            billingCount: 0,
            recentBilling: [],
          });
        }
      }

      setBranchDetails(details);
    } catch (err) {
      setError('Gagal memuat detail cabang: ' + (err.response?.data?.detail || err.message));
    } finally {
      setLoadingDetails(false);
    }
  };

  const handleViewDetails = (branchName) => {
    setSelectedBranch(branchName);
    loadBranchDetails(branchName);
  };

  const handleCloseDetails = () => {
    setSelectedBranch(null);
    setBranchDetails(null);
  };

  const handleAddBranch = async (e) => {
    e.preventDefault();
    setSubmitting(true);
    try {
      await branchAPI.create({
        name: newBranch.name,
        address: newBranch.address,
        phone: newBranch.phone,
      });

      setNewBranch({ name: '', address: '', phone: '' });
      setShowAddForm(false);
      loadBranches();
    } catch (err) {
      setError('Gagal menambah cabang: ' + (err.response?.data?.detail || err.message));
    } finally {
      setSubmitting(false);
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
          Manajemen Cabang
        </Typography>
        <Box sx={{ display: 'flex', gap: 1 }}>
          <Button variant="outlined" onClick={loadBranches}>
            Refresh
          </Button>
          <Button variant="contained" startIcon={<Add />} onClick={() => setShowAddForm(!showAddForm)}>
            {showAddForm ? 'Batal' : 'Tambah Cabang'}
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
            Tambah Cabang Baru
          </Typography>
          <Typography variant="body2" color="text.secondary" sx={{ mb: 2 }}>
            Menambah cabang baru ke master data. Setelah cabang dibuat, Anda bisa menambahkan kamera untuk cabang tersebut di halaman "Kelola Kamera".
          </Typography>
          <Box component="form" onSubmit={handleAddBranch} sx={{ mt: 2 }}>
            <TextField fullWidth label="Nama Cabang" value={newBranch.name} onChange={(e) => setNewBranch({ ...newBranch, name: e.target.value })} required placeholder="Contoh: Cabang Jakarta Pusat" margin="normal" />
            <TextField fullWidth label="Alamat (Opsional)" value={newBranch.address} onChange={(e) => setNewBranch({ ...newBranch, address: e.target.value })} placeholder="Contoh: Jl. Sudirman No. 123" margin="normal" />
            <TextField fullWidth label="Telepon (Opsional)" value={newBranch.phone} onChange={(e) => setNewBranch({ ...newBranch, phone: e.target.value })} placeholder="Contoh: 021-12345678" margin="normal" />
            <Button type="submit" variant="contained" disabled={submitting || !newBranch.name.trim()} sx={{ mt: 2 }}>
              {submitting ? <CircularProgress size={20} /> : 'Simpan'}
            </Button>
          </Box>
        </Paper>
      )}

      {branches.length === 0 ? (
        <Paper elevation={3} sx={{ p: 4, textAlign: 'center' }}>
          <Typography variant="body1" color="text.secondary">
            Belum ada cabang yang terdaftar.
          </Typography>
        </Paper>
      ) : (
        <Grid container spacing={3}>
          {branches.map((branch, index) => (
            <Grid item xs={12} sm={6} md={4} key={index}>
              <Card elevation={3} sx={{ height: '100%', display: 'flex', flexDirection: 'column' }}>
                <CardContent sx={{ flexGrow: 1 }}>
                  <Box sx={{ display: 'flex', alignItems: 'center', mb: 2 }}>
                    <Store sx={{ fontSize: 40, color: 'primary.main', mr: 2 }} />
                    <Typography variant="h6" component="h2" fontWeight="bold">
                      {branch.name}
                    </Typography>
                  </Box>

                  <Box sx={{ mt: 2 }}>
                    <Box sx={{ display: 'flex', alignItems: 'center', mb: 1 }}>
                      <CameraAlt sx={{ fontSize: 20, color: 'text.secondary', mr: 1 }} />
                      <Typography variant="body2" color="text.secondary">
                        {branch.cameras.length} Kamera
                      </Typography>
                    </Box>
                    <Box sx={{ display: 'flex', alignItems: 'center', mb: 1 }}>
                      <LocationOn sx={{ fontSize: 20, color: 'text.secondary', mr: 1 }} />
                      <Typography variant="body2" color="text.secondary">
                        {branch.totalZones} Zona
                      </Typography>
                    </Box>
                  </Box>
                </CardContent>
                <Box sx={{ p: 2, pt: 0 }}>
                  <Button fullWidth variant="contained" startIcon={<Visibility />} onClick={() => handleViewDetails(branch.name)}>
                    Lihat Detail
                  </Button>
                </Box>
              </Card>
            </Grid>
          ))}
        </Grid>
      )}

      {/* Detail Dialog */}
      <Dialog open={!!selectedBranch} onClose={handleCloseDetails} maxWidth="md" fullWidth>
        <DialogTitle>
          <Box sx={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
            <Typography variant="h6">Detail Cabang: {selectedBranch}</Typography>
            <IconButton onClick={handleCloseDetails} size="small">
              <Close />
            </IconButton>
          </Box>
        </DialogTitle>
        <DialogContent>
          {loadingDetails ? (
            <Box sx={{ display: 'flex', justifyContent: 'center', p: 4 }}>
              <CircularProgress />
            </Box>
          ) : branchDetails ? (
            <Box>
              <Typography variant="subtitle1" fontWeight="bold" sx={{ mb: 2 }}>
                Kamera ({branchDetails.cameras.length})
              </Typography>

              {branchDetails.cameras.map((cam) => (
                <Paper key={cam.id} elevation={2} sx={{ p: 2, mb: 2 }}>
                  <Box sx={{ display: 'flex', justifyContent: 'space-between', alignItems: 'start', mb: 2 }}>
                    <Box>
                      <Typography variant="h6" component="h3">
                        Kamera ID: {cam.id}
                      </Typography>
                      <Typography variant="body2" color="text.secondary">
                        RTSP: {cam.rtsp_url}
                      </Typography>
                    </Box>
                    <Chip label={cam.is_active ? 'Aktif' : 'Nonaktif'} color={cam.is_active ? 'success' : 'default'} size="small" />
                  </Box>

                  <Divider sx={{ my: 1 }} />

                  <Grid container spacing={2} sx={{ mt: 1 }}>
                    <Grid item xs={6}>
                      <Box sx={{ textAlign: 'center' }}>
                        <Typography variant="h4" color="primary">
                          {cam.zonesCount}
                        </Typography>
                        <Typography variant="caption" color="text.secondary">
                          Zona
                        </Typography>
                      </Box>
                    </Grid>
                    <Grid item xs={6}>
                      <Box sx={{ textAlign: 'center' }}>
                        <Typography variant="h4" color="success.main">
                          {cam.billingCount}
                        </Typography>
                        <Typography variant="caption" color="text.secondary">
                          Billing Items
                        </Typography>
                      </Box>
                    </Grid>
                  </Grid>

                  {cam.zones.length > 0 && (
                    <Box sx={{ mt: 2 }}>
                      <Typography variant="subtitle2" fontWeight="bold" sx={{ mb: 1 }}>
                        Zona:
                      </Typography>
                      <Box sx={{ display: 'flex', flexWrap: 'wrap', gap: 1 }}>
                        {cam.zones.map((zone) => (
                          <Chip key={zone.id} label={`${zone.name} (${zone.type})`} size="small" variant="outlined" />
                        ))}
                      </Box>
                    </Box>
                  )}

                  {cam.recentBilling.length > 0 && (
                    <Box sx={{ mt: 2 }}>
                      <Typography variant="subtitle2" fontWeight="bold" sx={{ mb: 1 }}>
                        Billing Terbaru:
                      </Typography>
                      <TableContainer>
                        <Table size="small">
                          <TableHead>
                            <TableRow>
                              <TableCell>Zona</TableCell>
                              <TableCell>Item</TableCell>
                              <TableCell align="right">Qty</TableCell>
                            </TableRow>
                          </TableHead>
                          <TableBody>
                            {cam.recentBilling.map((bill, i) => (
                              <TableRow key={i}>
                                <TableCell>{bill.zone}</TableCell>
                                <TableCell>{bill.item}</TableCell>
                                <TableCell align="right">{bill.qty}</TableCell>
                              </TableRow>
                            ))}
                          </TableBody>
                        </Table>
                      </TableContainer>
                    </Box>
                  )}
                </Paper>
              ))}
            </Box>
          ) : (
            <Typography>Data tidak tersedia</Typography>
          )}
        </DialogContent>
      </Dialog>
    </Box>
  );
};

export default BranchManager;
