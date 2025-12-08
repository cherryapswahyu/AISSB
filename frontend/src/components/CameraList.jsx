import { useState, useEffect } from 'react';
import { cameraAPI } from '../services/api';
import ZoneEditor from './ZoneEditor';
import SnapshotViewer from './SnapshotViewer';
import './CameraList.css';

const CameraList = ({ isAdmin }) => {
  const [cameras, setCameras] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [selectedCamera, setSelectedCamera] = useState(null);
  const [viewMode, setViewMode] = useState(null); // 'snapshot' atau 'zone'
  const [showAddForm, setShowAddForm] = useState(false);
  const [newCamera, setNewCamera] = useState({ branch_name: '', rtsp_url: '' });

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
    try {
      await cameraAPI.create(newCamera);
      setNewCamera({ branch_name: '', rtsp_url: '' });
      setShowAddForm(false);
      loadCameras();
    } catch (err) {
      alert('Gagal menambah kamera: ' + (err.response?.data?.detail || err.message));
    }
  };

  if (loading) {
    return <div className="loading">Memuat kamera...</div>;
  }

  return (
    <div className="camera-list">
      <div className="camera-list-header">
        <h2>Daftar Kamera</h2>
        {isAdmin && (
          <button onClick={() => setShowAddForm(!showAddForm)} className="add-button">
            {showAddForm ? 'Batal' : '+ Tambah Kamera'}
          </button>
        )}
      </div>

      {error && <div className="error-message">{error}</div>}

      {showAddForm && isAdmin && (
        <form onSubmit={handleAddCamera} className="add-camera-form">
          <h3>Tambah Kamera Baru</h3>
          <div className="form-group">
            <label>Nama Cabang</label>
            <input type="text" value={newCamera.branch_name} onChange={(e) => setNewCamera({ ...newCamera, branch_name: e.target.value })} required placeholder="Contoh: Cabang Jakarta Pusat" />
          </div>
          <div className="form-group">
            <label>RTSP URL</label>
            <input type="text" value={newCamera.rtsp_url} onChange={(e) => setNewCamera({ ...newCamera, rtsp_url: e.target.value })} required placeholder="Contoh: rtsp://user:pass@ip:port/stream atau 0 untuk webcam" />
          </div>
          <button type="submit" className="submit-button">
            Simpan
          </button>
        </form>
      )}

      {cameras.length === 0 ? (
        <div className="empty-state">
          <p>Belum ada kamera yang terdaftar.</p>
        </div>
      ) : (
        <div className="cameras-grid">
          {cameras.map((camera) => (
            <div key={camera.id} className="camera-card">
              <h3>{camera.branch_name}</h3>
              <p>
                <strong>ID:</strong> {camera.id}
              </p>
              <p>
                <strong>RTSP URL:</strong> {camera.rtsp_url}
              </p>
              <div className="camera-actions">
                <button
                  onClick={() => {
                    setSelectedCamera(camera.id);
                    setViewMode('snapshot');
                  }}
                  className="action-button">
                  Lihat Snapshot
                </button>
                {isAdmin && (
                  <button
                    onClick={() => {
                      setSelectedCamera(camera.id);
                      setViewMode('zone');
                    }}
                    className="action-button">
                    Atur Zona
                  </button>
                )}
              </div>
            </div>
          ))}
        </div>
      )}

      {selectedCamera && (
        <div
          className="modal-overlay"
          onClick={() => {
            setSelectedCamera(null);
            setViewMode(null);
          }}>
          <div className="modal-content" onClick={(e) => e.stopPropagation()}>
            <button
              className="close-button"
              onClick={() => {
                setSelectedCamera(null);
                setViewMode(null);
              }}>
              ✕
            </button>
            {viewMode === 'zone' ? (
              <ZoneEditor
                cameraId={selectedCamera}
                onClose={() => {
                  setSelectedCamera(null);
                  setViewMode(null);
                }}
              />
            ) : (
              <SnapshotViewer cameraId={selectedCamera} />
            )}
          </div>
        </div>
      )}
    </div>
  );
};

export default CameraList;
