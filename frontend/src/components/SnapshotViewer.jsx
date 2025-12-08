import { useState, useEffect } from 'react';
import { snapshotAPI } from '../services/api';
import './SnapshotViewer.css';

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
    <div className="snapshot-viewer">
      <h3>Snapshot Kamera ID: {cameraId}</h3>
      <div className="snapshot-container">
        {loading && <div className="loading">Memuat snapshot...</div>}
        {error && <div className="error-message">{error}</div>}
        {imageUrl && !error && (
          <img
            src={imageUrl}
            alt={`Snapshot kamera ${cameraId}`}
            className="snapshot-image"
            onLoad={() => setLoading(false)}
            onError={() => {
              setLoading(false);
              setError('Gagal memuat snapshot dari kamera');
            }}
          />
        )}
      </div>
      <button onClick={loadSnapshot} className="refresh-button">
        Refresh
      </button>
    </div>
  );
};

export default SnapshotViewer;
