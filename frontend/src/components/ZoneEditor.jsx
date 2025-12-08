import { useState, useEffect, useRef } from 'react';
import { useParams } from 'react-router-dom';
import { snapshotAPI, zoneAPI } from '../services/api';
import './ZoneEditor.css';

const ZoneEditor = ({ cameraId: propCameraId }) => {
  const { id } = useParams(); // Ambil ID kamera dari URL params
  // Gunakan URL params jika ada, jika tidak gunakan props (backward compatibility)
  const cameraId = id ? parseInt(id, 10) : propCameraId;

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
    try {
      const data = await zoneAPI.getByCamera(cameraId);
      setSavedZones(data || []);
    } catch (error) {
      console.error('Gagal memuat zones:', error);
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

        ctx.strokeStyle = zone.type === 'table' ? '#00ff00' : '#ff0000';
        ctx.lineWidth = 2;
        ctx.strokeRect(x1, y1, x2 - x1, y2 - y1);

        // Draw label
        ctx.fillStyle = zone.type === 'table' ? '#00ff00' : '#ff0000';
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
    if (!zoneName.trim() || !currentRect) return;

    const canvas = canvasRef.current;
    if (!canvas) return;

    // Konversi koordinat pixel ke persentase (0.0 - 1.0)
    const x1_pct = currentRect.x / canvas.width;
    const y1_pct = currentRect.y / canvas.height;
    const x2_pct = (currentRect.x + currentRect.width) / canvas.width;
    const y2_pct = (currentRect.y + currentRect.height) / canvas.height;

    try {
      await zoneAPI.create({
        camera_id: cameraId,
        name: zoneName.trim(),
        type: zoneType,
        coords: [x1_pct, y1_pct, x2_pct, y2_pct],
      });

      // Reset form dan reload zones
      setZoneName('');
      setZoneType('table');
      setCurrentRect(null);
      setShowSaveDialog(false);
      loadSavedZones();
    } catch (error) {
      alert('Gagal menyimpan zona: ' + (error.response?.data?.detail || error.message));
    }
  };

  const handleCancelSave = () => {
    setCurrentRect(null);
    setShowSaveDialog(false);
    setZoneName('');
    setZoneType('table');
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
    <div className="zone-editor">
      <h3>Atur Zona - Kamera ID: {cameraId}</h3>

      <div className="zone-editor-controls">
        <button onClick={loadSnapshot} className="refresh-button">
          Refresh Snapshot
        </button>
        <div className="zone-info">
          <p>
            <strong>Instruksi:</strong> Klik dan drag pada gambar untuk membuat zona baru
          </p>
          <p>Hijau = Meja (Table), Merah = Refill</p>
        </div>
      </div>

      {loading && <div className="loading">Memuat snapshot...</div>}
      {error && <div className="error-message">{error}</div>}

      <div className="canvas-container">
        <canvas
          ref={canvasRef}
          onMouseDown={handleMouseDown}
          onMouseMove={handleMouseMove}
          onMouseUp={handleMouseUp}
          style={{
            border: '1px solid #ddd',
            cursor: 'crosshair',
            maxWidth: '100%',
            height: 'auto',
            display: image ? 'block' : 'none',
          }}
        />
      </div>

      {/* Save Dialog */}
      {showSaveDialog && (
        <div className="save-dialog-overlay" onClick={handleCancelSave}>
          <div className="save-dialog" onClick={(e) => e.stopPropagation()}>
            <h4>Simpan Zona Baru</h4>
            <div className="form-group">
              <label htmlFor="zone-name">Nama Zona</label>
              <input type="text" id="zone-name" value={zoneName} onChange={(e) => setZoneName(e.target.value)} placeholder="Contoh: Meja 1" autoFocus />
            </div>
            <div className="form-group">
              <label htmlFor="zone-type">Tipe</label>
              <select id="zone-type" value={zoneType} onChange={(e) => setZoneType(e.target.value)}>
                <option value="table">Table (Meja)</option>
                <option value="refill">Refill</option>
              </select>
            </div>
            <div className="dialog-actions">
              <button onClick={handleSaveZone} className="save-button" disabled={!zoneName.trim()}>
                Simpan
              </button>
              <button onClick={handleCancelSave} className="cancel-button">
                Batal
              </button>
            </div>
          </div>
        </div>
      )}

      {/* List Saved Zones */}
      {savedZones.length > 0 && (
        <div className="zones-list">
          <h4>Zona yang Tersimpan</h4>
          <ul>
            {savedZones.map((zone) => (
              <li key={zone.id}>
                <div className="zone-item">
                  <div className="zone-info">
                    <strong>{zone.name}</strong> - {zone.type} (Koordinat: [{zone.coords?.map((c, i) => (i > 0 ? ', ' : '') + c.toFixed(3)).join('')}])
                  </div>
                  <button onClick={() => handleDeleteZone(zone.id)} className="delete-zone-button" title="Hapus zona">
                    🗑️ Hapus
                  </button>
                </div>
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
};

export default ZoneEditor;
