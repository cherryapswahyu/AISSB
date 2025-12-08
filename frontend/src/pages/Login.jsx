import { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { useAuth } from '../contexts/AuthContext';
import axios from 'axios';
import { Container, Paper, Box, TextField, Button, Typography, Alert, CircularProgress } from '@mui/material';
import { LockOutlined } from '@mui/icons-material';

const Login = () => {
  const [username, setUsername] = useState('');
  const [password, setPassword] = useState('');
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(false);
  const { login } = useAuth();
  const navigate = useNavigate();

  const handleSubmit = async (e) => {
    e.preventDefault();
    setError('');
    setLoading(true);

    try {
      // Buat FormData untuk FastAPI OAuth2
      const formData = new FormData();
      formData.append('username', username);
      formData.append('password', password);

      // POST ke endpoint token dengan FormData
      const response = await axios.post('http://127.0.0.1:8000/token', formData, {
        headers: {
          'Content-Type': 'multipart/form-data',
        },
      });

      // Jika sukses, dapat access_token
      const { access_token } = response.data;

      if (access_token) {
        // Simpan token di localStorage
        localStorage.setItem('token', access_token);

        // Panggil fungsi login dari AuthContext
        const result = await login(username, password);

        if (result.success) {
          // Redirect ke dashboard
          navigate('/dashboard');
        } else {
          setError(result.error || 'Login gagal');
        }
      }
    } catch (err) {
      setError(err.response?.data?.detail || 'Login gagal. Periksa username dan password.');
    } finally {
      setLoading(false);
    }
  };

  return (
    <Box
      sx={{
        width: '100vw',
        height: '100vh',
        display: 'flex',
        justifyContent: 'center',
        alignItems: 'center',
        background: 'linear-gradient(135deg, #667eea 0%, #764ba2 100%)',
        padding: 2,
        margin: 0,
        position: 'fixed',
        top: 0,
        left: 0,
        right: 0,
        bottom: 0,
      }}>
      <Container
        maxWidth="sm"
        sx={{
          width: '100%',
        }}>
        <Paper
          elevation={3}
          sx={{
            padding: 4,
            width: '100%',
            display: 'flex',
            flexDirection: 'column',
            alignItems: 'center',
          }}>
          <Box
            sx={{
              display: 'flex',
              alignItems: 'center',
              gap: 1,
              mb: 3,
            }}>
            <LockOutlined color="primary" sx={{ fontSize: 40 }} />
            <Typography variant="h4" component="h1" fontWeight="bold">
              CCTV Analytics
            </Typography>
          </Box>

          <Typography variant="h5" component="h2" gutterBottom color="text.secondary">
            Login
          </Typography>

          <Box component="form" onSubmit={handleSubmit} sx={{ width: '100%', mt: 3 }}>
            <TextField fullWidth label="Username" id="username" value={username} onChange={(e) => setUsername(e.target.value)} required autoComplete="username" margin="normal" disabled={loading} />
            <TextField fullWidth label="Password" id="password" type="password" value={password} onChange={(e) => setPassword(e.target.value)} required autoComplete="current-password" margin="normal" disabled={loading} />

            {error && (
              <Alert severity="error" sx={{ mt: 2 }}>
                {error}
              </Alert>
            )}

            <Button type="submit" fullWidth variant="contained" size="large" disabled={loading} sx={{ mt: 3, mb: 2 }}>
              {loading ? (
                <>
                  <CircularProgress size={20} sx={{ mr: 1 }} />
                  Memproses...
                </>
              ) : (
                'Login'
              )}
            </Button>
          </Box>
        </Paper>
      </Container>
    </Box>
  );
};

export default Login;
