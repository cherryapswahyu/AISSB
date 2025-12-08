import { useState, useEffect } from 'react';
import { userAPI, branchAPI } from '../services/api';
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
import { Add, Delete, Close, Person } from '@mui/icons-material';

const UserManager = () => {
  const [users, setUsers] = useState([]);
  const [branches, setBranches] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [showAddForm, setShowAddForm] = useState(false);
  const [newUser, setNewUser] = useState({
    username: '',
    password: '',
    role: 'staff',
    branch_id: null,
  });
  const [submitting, setSubmitting] = useState(false);
  const [deleteConfirm, setDeleteConfirm] = useState(null);
  const [deleting, setDeleting] = useState(false);

  useEffect(() => {
    loadUsers();
    loadBranches();
  }, []);

  const loadUsers = async () => {
    try {
      setLoading(true);
      const data = await userAPI.getAll();
      setUsers(data);
      setError('');
    } catch (err) {
      setError('Gagal memuat daftar user: ' + (err.response?.data?.detail || err.message));
    } finally {
      setLoading(false);
    }
  };

  const loadBranches = async () => {
    try {
      const data = await branchAPI.getAll();
      setBranches(data);
    } catch (err) {
      console.error('Gagal memuat cabang:', err);
    }
  };

  const handleAddUser = async (e) => {
    e.preventDefault();
    setSubmitting(true);
    try {
      await userAPI.create({
        username: newUser.username,
        password: newUser.password,
        role: newUser.role,
        branch_id: newUser.role === 'staff' ? newUser.branch_id : null,
      });

      setNewUser({ username: '', password: '', role: 'staff', branch_id: null });
      setShowAddForm(false);
      loadUsers();
    } catch (err) {
      setError('Gagal menambah user: ' + (err.response?.data?.detail || err.message));
    } finally {
      setSubmitting(false);
    }
  };

  const handleDeleteUser = async (userId, username) => {
    setDeleteConfirm({ id: userId, name: username });
  };

  const confirmDelete = async () => {
    if (!deleteConfirm) return;

    setDeleting(true);
    try {
      await userAPI.delete(deleteConfirm.id);
      setDeleteConfirm(null);
      loadUsers();
    } catch (err) {
      setError('Gagal menghapus user: ' + (err.response?.data?.detail || err.message));
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
          Kelola User
        </Typography>
        <Button variant="contained" startIcon={<Add />} onClick={() => setShowAddForm(!showAddForm)}>
          {showAddForm ? 'Batal' : 'Tambah User'}
        </Button>
      </Box>

      {error && (
        <Alert severity="error" sx={{ mb: 2 }} onClose={() => setError('')}>
          {error}
        </Alert>
      )}

      {showAddForm && (
        <Paper elevation={3} sx={{ p: 3, mb: 3 }}>
          <Typography variant="h6" gutterBottom>
            Tambah User Baru
          </Typography>
          <Box component="form" onSubmit={handleAddUser} sx={{ mt: 2 }}>
            <TextField fullWidth label="Username" value={newUser.username} onChange={(e) => setNewUser({ ...newUser, username: e.target.value })} required placeholder="Contoh: budi_staff" margin="normal" />
            <TextField fullWidth label="Password" type="password" value={newUser.password} onChange={(e) => setNewUser({ ...newUser, password: e.target.value })} required placeholder="Minimal 6 karakter" margin="normal" />
            <FormControl fullWidth margin="normal">
              <InputLabel>Role</InputLabel>
              <Select value={newUser.role} label="Role" onChange={(e) => setNewUser({ ...newUser, role: e.target.value, branch_id: null })}>
                <MenuItem value="admin">Admin</MenuItem>
                <MenuItem value="staff">Staff</MenuItem>
              </Select>
            </FormControl>
            {newUser.role === 'staff' && (
              <FormControl fullWidth margin="normal" required>
                <InputLabel>Cabang</InputLabel>
                <Select value={newUser.branch_id || ''} label="Cabang" onChange={(e) => setNewUser({ ...newUser, branch_id: e.target.value })}>
                  {branches.length === 0 ? (
                    <MenuItem disabled>Belum ada cabang. Tambah cabang terlebih dahulu di halaman "Manajemen Cabang".</MenuItem>
                  ) : (
                    branches.map((branch) => (
                      <MenuItem key={branch.id} value={branch.id}>
                        {branch.name}
                      </MenuItem>
                    ))
                  )}
                </Select>
              </FormControl>
            )}
            <Button type="submit" variant="contained" disabled={submitting} sx={{ mt: 2 }}>
              {submitting ? <CircularProgress size={20} /> : 'Simpan'}
            </Button>
          </Box>
        </Paper>
      )}

      {users.length === 0 ? (
        <Paper elevation={3} sx={{ p: 4, textAlign: 'center' }}>
          <Typography variant="body1" color="text.secondary">
            Belum ada user yang terdaftar.
          </Typography>
        </Paper>
      ) : (
        <TableContainer component={Paper} elevation={3}>
          <Table>
            <TableHead>
              <TableRow>
                <TableCell>
                  <strong>ID</strong>
                </TableCell>
                <TableCell>
                  <strong>Username</strong>
                </TableCell>
                <TableCell>
                  <strong>Role</strong>
                </TableCell>
                <TableCell>
                  <strong>Cabang</strong>
                </TableCell>
                <TableCell align="center">
                  <strong>Action</strong>
                </TableCell>
              </TableRow>
            </TableHead>
            <TableBody>
              {users.map((user) => (
                <TableRow key={user.id} hover>
                  <TableCell>{user.id}</TableCell>
                  <TableCell>
                    <Box sx={{ display: 'flex', alignItems: 'center', gap: 1 }}>
                      <Person fontSize="small" />
                      {user.username}
                    </Box>
                  </TableCell>
                  <TableCell>
                    <Chip label={user.role} color={user.role === 'admin' ? 'primary' : 'default'} size="small" />
                  </TableCell>
                  <TableCell>
                    {user.branch_id ? (
                      (() => {
                        const branch = branches.find((b) => b.id === user.branch_id);
                        return branch ? <Chip label={branch.name} size="small" variant="outlined" color="primary" /> : <Chip label={`ID: ${user.branch_id}`} size="small" variant="outlined" />;
                      })()
                    ) : (
                      <Typography variant="body2" color="text.secondary">
                        -
                      </Typography>
                    )}
                  </TableCell>
                  <TableCell>
                    <Box sx={{ display: 'flex', gap: 1, justifyContent: 'center' }}>
                      <Button variant="outlined" color="error" size="small" startIcon={<Delete />} onClick={() => handleDeleteUser(user.id, user.username)} disabled={deleting}>
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

      <Dialog open={!!deleteConfirm} onClose={() => setDeleteConfirm(null)}>
        <DialogTitle>Konfirmasi Hapus User</DialogTitle>
        <DialogContent>
          <Typography>
            Yakin ingin menghapus user <strong>"{deleteConfirm?.name}"</strong> (ID: {deleteConfirm?.id})?
            <br />
            <br />
            Tindakan ini tidak dapat dibatalkan.
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

export default UserManager;
