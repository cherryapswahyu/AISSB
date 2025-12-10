import axios from 'axios';
import { jwtDecode } from 'jwt-decode';

// Base URL untuk backend API (sesuaikan dengan port FastAPI Anda)
const API_BASE_URL = 'http://localhost:8000';

// Buat instance axios
const api = axios.create({
  baseURL: API_BASE_URL,
  headers: {
    'Content-Type': 'application/json',
  },
});

// Interceptor untuk menambahkan token ke setiap request
api.interceptors.request.use(
  (config) => {
    const token = localStorage.getItem('token');
    if (token) {
      config.headers.Authorization = `Bearer ${token}`;
    }
    return config;
  },
  (error) => {
    return Promise.reject(error);
  }
);

// Interceptor untuk handle error 401 (unauthorized)
api.interceptors.response.use(
  (response) => response,
  (error) => {
    if (error.response?.status === 401) {
      // Token expired atau invalid, hapus token dan redirect ke login
      localStorage.removeItem('token');
      localStorage.removeItem('user');
      window.location.href = '/login';
    }
    return Promise.reject(error);
  }
);

// API Functions
export const authAPI = {
  login: async (username, password) => {
    const formData = new FormData();
    formData.append('username', username);
    formData.append('password', password);

    const response = await api.post('/token', formData, {
      headers: {
        'Content-Type': 'multipart/form-data',
      },
    });

    const { access_token } = response.data;
    localStorage.setItem('token', access_token);

    // Decode token untuk mendapatkan user info
    const decoded = jwtDecode(access_token);
    const userInfo = {
      username: decoded.sub,
      role: decoded.role,
      branch_id: decoded.branch_id,
    };
    localStorage.setItem('user', JSON.stringify(userInfo));

    return { token: access_token, user: userInfo };
  },

  logout: () => {
    localStorage.removeItem('token');
    localStorage.removeItem('user');
  },

  getCurrentUser: () => {
    const userStr = localStorage.getItem('user');
    return userStr ? JSON.parse(userStr) : null;
  },

  getToken: () => {
    return localStorage.getItem('token');
  },

  isAuthenticated: () => {
    const token = localStorage.getItem('token');
    if (!token) return false;

    try {
      const decoded = jwtDecode(token);
      const currentTime = Date.now() / 1000;
      return decoded.exp > currentTime;
    } catch {
      return false;
    }
  },
};

export const cameraAPI = {
  getAll: async () => {
    const response = await api.get('/cameras/');
    return response.data;
  },

  create: async (cameraData) => {
    const response = await api.post('/cameras/', cameraData);
    return response.data;
  },

  delete: async (cameraId) => {
    const response = await api.delete(`/cameras/${cameraId}`);
    return response.data;
  },

  deleteWithoutZones: async () => {
    const response = await api.delete('/cameras/cleanup/no-zones');
    return response.data;
  },
};

export const zoneAPI = {
  create: async (zoneData) => {
    const response = await api.post('/zones/', zoneData);
    return response.data;
  },

  getByCamera: async (camId) => {
    const response = await api.get(`/zones/${camId}`);
    return response.data;
  },

  delete: async (zoneId) => {
    const response = await api.delete(`/zones/${zoneId}`);
    return response.data;
  },
};

export const snapshotAPI = {
  getSnapshot: (camId) => {
    // Return URL untuk snapshot (akan digunakan sebagai src untuk img tag)
    return `${API_BASE_URL}/snapshot/${camId}?t=${Date.now()}`;
  },
  getStream: (camId) => {
    // Return URL untuk MJPEG streaming
    return `${API_BASE_URL}/stream/${camId}`;
  },
};

export const billingAPI = {
  getLiveBilling: async (camId) => {
    const response = await api.get(`/billing/live/${camId}`);
    return response.data;
  },
};

export const detectionAPI = {
  getDetections: async (camId) => {
    const response = await api.get(`/detections/${camId}`);
    return response.data;
  },
};

export const analysisAPI = {
  analyzeCamera: async (cameraId) => {
    const response = await api.post(`/analyze/${cameraId}`);
    return response.data;
  },

  analyzeAll: async () => {
    const response = await api.post('/analyze/all');
    return response.data;
  },
};

export const userAPI = {
  getAll: async () => {
    const response = await api.get('/users/');
    return response.data;
  },

  create: async (userData) => {
    const response = await api.post('/users/', userData);
    return response.data;
  },

  delete: async (userId) => {
    const response = await api.delete(`/users/${userId}`);
    return response.data;
  },
};

export const branchAPI = {
  getAll: async () => {
    const response = await api.get('/branches/');
    return response.data;
  },

  create: async (branchData) => {
    const response = await api.post('/branches/', branchData);
    return response.data;
  },

  getById: async (branchId) => {
    const response = await api.get(`/branches/${branchId}`);
    return response.data;
  },

  delete: async (branchId) => {
    const response = await api.delete(`/branches/${branchId}`);
    return response.data;
  },
};

export const backgroundServiceAPI = {
  getStatus: async () => {
    const response = await api.get('/background-service/status');
    return response.data;
  },

  enable: async () => {
    const response = await api.post('/background-service/enable');
    return response.data;
  },

  disable: async () => {
    const response = await api.post('/background-service/disable');
    return response.data;
  },
};

export const zoneStateAPI = {
  getStates: async (cameraId) => {
    const response = await api.get(`/zones/states/${cameraId}`);
    return response.data;
  },
};

export const eventsAPI = {
  getEvents: async (cameraId) => {
    const response = await api.get(`/events/${cameraId}`);
    return response.data;
  },
};

export const reportsAPI = {
  getTableOccupancy: async (cameraId = null, startDate = null, endDate = null, groupBy = 'day') => {
    const params = new URLSearchParams();
    if (cameraId) params.append('camera_id', cameraId);
    if (startDate) params.append('start_date', startDate);
    if (endDate) params.append('end_date', endDate);
    params.append('group_by', groupBy);

    const response = await api.get(`/reports/table-occupancy?${params.toString()}`);
    return response.data;
  },

  getQueueReport: async (cameraId = null, startDate = null, endDate = null, groupBy = 'day') => {
    const params = new URLSearchParams();
    if (cameraId) params.append('camera_id', cameraId);
    if (startDate) params.append('start_date', startDate);
    if (endDate) params.append('end_date', endDate);
    params.append('group_by', groupBy);

    const response = await api.get(`/reports/queue?${params.toString()}`);
    return response.data;
  },

  getCustomerReport: async (branchId = null, startDate = null, endDate = null, groupBy = 'day') => {
    const params = new URLSearchParams();
    if (branchId) params.append('branch_id', branchId);
    if (startDate) params.append('start_date', startDate);
    if (endDate) params.append('end_date', endDate);
    params.append('group_by', groupBy);
    const response = await api.get(`/reports/customers?${params.toString()}`);
    return response.data;
  },
};

export const customerAPI = {
  getStats: async () => {
    const response = await api.get('/customers/stats');
    return response.data;
  },
};

export const staffFaceAPI = {
  upload: async (file, staffName) => {
    const formData = new FormData();
    formData.append('file', file);
    formData.append('staff_name', staffName);
    const response = await api.post('/staff-faces/upload', formData, {
      headers: {
        'Content-Type': 'multipart/form-data',
      },
    });
    return response.data;
  },

  list: async () => {
    const response = await api.get('/staff-faces/');
    return response.data;
  },

  delete: async (filename) => {
    const response = await api.delete(`/staff-faces/${filename}`);
    return response.data;
  },

  reload: async () => {
    const response = await api.post('/staff-faces/reload');
    return response.data;
  },
};

export default api;
