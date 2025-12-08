import { createContext, useContext, useState, useEffect, useCallback } from 'react';
import { jwtDecode } from 'jwt-decode';
import axios from 'axios';

const AuthContext = createContext(null);

// Base URL untuk backend API
const API_BASE_URL = 'http://localhost:8000';

export const AuthProvider = ({ children }) => {
  const [user, setUser] = useState(null);
  const [loading, setLoading] = useState(true);

  // Fungsi untuk decode token dan mendapatkan data user
  const decodeToken = (token) => {
    try {
      const decoded = jwtDecode(token);
      return {
        username: decoded.sub,
        role: decoded.role,
        branch_id: decoded.branch_id,
      };
    } catch (error) {
      console.error('Error decoding token:', error);
      return null;
    }
  };

  // Fungsi untuk cek apakah token expired
  const isTokenExpired = (token) => {
    try {
      const decoded = jwtDecode(token);
      const currentTime = Date.now() / 1000;
      return decoded.exp < currentTime;
    } catch {
      return true;
    }
  };

  // Fungsi logout
  const logout = useCallback(() => {
    localStorage.removeItem('token');
    setUser(null);
  }, []);

  // Load user dari token di localStorage saat aplikasi pertama kali load
  useEffect(() => {
    const token = localStorage.getItem('token');

    if (token) {
      // Cek apakah token expired
      if (isTokenExpired(token)) {
        // Token expired, hapus dan logout
        localStorage.removeItem('token');
        // eslint-disable-next-line react-compiler/react-compiler
        setUser(null);
        // eslint-disable-next-line react-compiler/react-compiler
        setLoading(false);
        return;
      }

      // Token masih valid, decode dan set user
      const userData = decodeToken(token);
      if (userData) {
        // eslint-disable-next-line react-compiler/react-compiler
        setUser(userData);
      } else {
        // Gagal decode, hapus token
        localStorage.removeItem('token');
        // eslint-disable-next-line react-compiler/react-compiler
        setUser(null);
      }
    }

    // eslint-disable-next-line react-compiler/react-compiler
    setLoading(false);
  }, []);

  // Auto-logout jika token expired (cek setiap menit)
  useEffect(() => {
    const checkTokenExpiry = () => {
      const token = localStorage.getItem('token');
      if (token && isTokenExpired(token)) {
        // Token expired, logout
        logout();
      }
    };

    // Cek setiap 60 detik
    const interval = setInterval(checkTokenExpiry, 60000);

    return () => clearInterval(interval);
  }, [logout]);

  // Fungsi login
  const login = async (username, password) => {
    try {
      const formData = new FormData();
      formData.append('username', username);
      formData.append('password', password);

      const response = await axios.post(`${API_BASE_URL}/token`, formData, {
        headers: {
          'Content-Type': 'multipart/form-data',
        },
      });

      const { access_token } = response.data;

      // Simpan token di localStorage
      localStorage.setItem('token', access_token);

      // Decode token untuk mendapatkan data user
      const userData = decodeToken(access_token);
      if (userData) {
        setUser(userData);
        return { success: true };
      } else {
        return {
          success: false,
          error: 'Gagal memproses token',
        };
      }
    } catch (error) {
      return {
        success: false,
        error: error.response?.data?.detail || 'Login gagal. Periksa username dan password.',
      };
    }
  };

  const value = {
    user,
    login,
    logout,
    isAuthenticated: !!user,
    isAdmin: user?.role === 'admin',
    isStaff: user?.role === 'staff',
    loading,
  };

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
};

export const useAuth = () => {
  const context = useContext(AuthContext);
  if (!context) {
    throw new Error('useAuth must be used within AuthProvider');
  }
  return context;
};
