import { useState, useEffect, useRef } from 'react';
import { snapshotAPI, billingAPI, detectionAPI, zoneAPI, zoneStateAPI } from '../services/api';
import { Box, Grid, Paper, Typography, Table, TableBody, TableCell, TableContainer, TableHead, TableRow, CircularProgress, Alert, Chip, Accordion, AccordionSummary, AccordionDetails } from '@mui/material';
import { Videocam, Receipt, ExpandMore, LocationOn, Warning, CheckCircle, Person, TableRestaurant, Queue } from '@mui/icons-material';

const LiveMonitor = ({ branchId }) => {
  const [imageUrl, setImageUrl] = useState('');
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [billingData, setBillingData] = useState([]);
  const [detections, setDetections] = useState([]);
  const [frameSize, setFrameSize] = useState({ width: 0, height: 0 });
  const [savedZones, setSavedZones] = useState([]);
  const [zoneStates, setZoneStates] = useState({});
  const videoRef = useRef(null);
  const canvasRef = useRef(null);
  const wsRef = useRef(null);
  const wsDataRef = useRef(null);

  // Setup streaming video (MJPEG)
  useEffect(() => {
    if (branchId) {
      const streamUrl = snapshotAPI.getStream(branchId);
      setImageUrl(streamUrl);
      setLoading(true);
      setError('');
    }
  }, [branchId]);

  // Load billing data dari API
  const loadBillingData = async () => {
    try {
      const data = await billingAPI.getLiveBilling(branchId);
      setBillingData(data);
    } catch (err) {
      console.error('Gagal memuat billing data:', err);
      setBillingData([]);
    }
  };

  // Load detections dari API (fallback jika WebSocket tidak tersedia)
  const loadDetections = async () => {
    try {
      const data = await detectionAPI.getDetections(branchId);
      setDetections(data.detections || []);
      setFrameSize(data.frame_size || { width: 0, height: 0 });
      // Debug: log detections untuk memastikan data ter-load
      if (data.detections && data.detections.length > 0) {
        console.log('Detections loaded:', data.detections.length, 'items');
      }
    } catch (err) {
      console.error('Gagal memuat detections:', err);
      setDetections([]);
    }
  };

  // Load saved zones dari API
  const loadSavedZones = async () => {
    try {
      const data = await zoneAPI.getByCamera(branchId);
      setSavedZones(data || []);
    } catch (err) {
      console.error('Gagal memuat zones:', err);
      setSavedZones([]);
    }
  };

  // Load zone states dari API
  const loadZoneStates = async () => {
    try {
      const data = await zoneStateAPI.getStates(branchId);
      setZoneStates(data.zone_states || {});
    } catch (err) {
      console.error('Gagal memuat zone states:', err);
      setZoneStates({});
    }
  };

  // Helper function untuk interpretasi status meja
  const getTableStatusInfo = (zoneState) => {
    if (!zoneState) return null;

    // Handle backward compatibility (jika masih integer)
    if (typeof zoneState === 'number') {
      if (zoneState === 0) return { label: 'Bersih', color: 'success', icon: <CheckCircle /> };
      if (zoneState > 3) return { label: `Kotor (${zoneState * 5}s)`, color: 'error', icon: <Warning /> };
      return { label: 'Unknown', color: 'default', icon: null };
    }

    // Handle new format (object)
    if (typeof zoneState === 'object' && zoneState.status) {
      const statusMap = {
        TERISI: { label: 'Terisi', color: 'info', icon: <Person />, description: `${zoneState.person_count} orang, ${zoneState.item_count} items` },
        KOTOR: {
          label: zoneState.needs_cleaning ? `Kotor - Perlu Dibersihkan!` : `Kotor (${zoneState.timer * 5}s)`,
          color: zoneState.needs_cleaning ? 'error' : 'warning',
          icon: <Warning />,
          description: `${zoneState.item_count} items tersisa`,
        },
        BERSIH: { label: 'Bersih', color: 'success', icon: <CheckCircle />, description: 'Siap digunakan' },
      };

      return statusMap[zoneState.status] || { label: zoneState.status, color: 'default', icon: null, description: '' };
    }

    return null;
  };

  // Helper function untuk interpretasi status antrian
  const getQueueStatusInfo = (zoneState) => {
    if (!zoneState) return null;

    if (typeof zoneState === 'number') {
      const count = zoneState;
      if (count > 4) return { label: `Penuh (${count} orang)`, color: 'error', icon: <Warning /> };
      if (count > 0) return { label: `${count} orang`, color: 'warning', icon: <Person /> };
      return { label: 'Kosong', color: 'success', icon: <CheckCircle /> };
    }

    if (typeof zoneState === 'object' && zoneState.person_count !== undefined) {
      const count = zoneState.person_count;
      if (count > 4) return { label: `Penuh (${count} orang)`, color: 'error', icon: <Warning /> };
      if (count > 0) return { label: `${count} orang`, color: 'warning', icon: <Person /> };
      return { label: 'Kosong', color: 'success', icon: <CheckCircle /> };
    }

    return null;
  };

  // Draw detections overlay on canvas
  useEffect(() => {
    const drawOverlay = () => {
      if (!canvasRef.current || !videoRef.current) return;

      const canvas = canvasRef.current;
      const video = videoRef.current;
      const ctx = canvas.getContext('2d');

      // Set canvas size to match video display size
      const videoWidth = video.offsetWidth || video.clientWidth || video.naturalWidth;
      const videoHeight = video.offsetHeight || video.clientHeight || video.naturalHeight;

      if (videoWidth === 0 || videoHeight === 0) return;

      // Set canvas size (important: set both width/height and style)
      canvas.width = videoWidth;
      canvas.height = videoHeight;

      // Clear canvas
      ctx.clearRect(0, 0, canvas.width, canvas.height);

      // Draw saved zones terlebih dahulu (garis meja/refill)
      if (savedZones.length > 0 && frameSize.width && frameSize.height) {
        savedZones.forEach((zone) => {
          if (zone.coords && zone.coords.length === 4) {
            const [x1_pct, y1_pct, x2_pct, y2_pct] = zone.coords;
            const x1 = x1_pct * canvas.width;
            const y1 = y1_pct * canvas.height;
            const x2 = x2_pct * canvas.width;
            const y2 = y2_pct * canvas.height;
            const width = x2 - x1;
            const height = y2 - y1;

            // Draw zone rectangle
            ctx.strokeStyle = zone.type === 'table' ? '#00ff00' : '#ff0000';
            ctx.lineWidth = 2;
            ctx.strokeRect(x1, y1, width, height);

            // Draw zone label background
            ctx.fillStyle = zone.type === 'table' ? 'rgba(0, 255, 0, 0.7)' : 'rgba(255, 0, 0, 0.7)';
            ctx.font = 'bold 12px Arial';
            const textWidth = ctx.measureText(zone.name).width;
            ctx.fillRect(x1, y1 - 18, textWidth + 8, 18);

            // Draw zone label text
            ctx.fillStyle = '#ffffff';
            ctx.fillText(zone.name, x1 + 4, y1 - 4);
          }
        });
      }

      // Jika tidak ada detections atau frameSize, skip drawing detections
      if (!frameSize.width || !frameSize.height) {
        return;
      }

      // Draw bounding boxes dan labels untuk detections
      detections.forEach((detection) => {
        if (!detection.bbox) return;

        const bbox = detection.bbox;
        // Gunakan koordinat pixel langsung dari API atau konversi dari persentase
        const x1 = bbox.x1_pct !== undefined ? bbox.x1_pct * canvas.width : (bbox.x1 / frameSize.width) * canvas.width;
        const y1 = bbox.y1_pct !== undefined ? bbox.y1_pct * canvas.height : (bbox.y1 / frameSize.height) * canvas.height;
        const x2 = bbox.x2_pct !== undefined ? bbox.x2_pct * canvas.width : (bbox.x2 / frameSize.width) * canvas.width;
        const y2 = bbox.y2_pct !== undefined ? bbox.y2_pct * canvas.height : (bbox.y2 / frameSize.height) * canvas.height;
        const width = x2 - x1;
        const height = y2 - y1;

        // Draw bounding box
        ctx.strokeStyle = detection.zone ? '#4caf50' : '#ff9800';
        ctx.lineWidth = 3;
        ctx.strokeRect(x1, y1, width, height);

        // Draw label background
        const label = `${detection.name} (${(detection.confidence * 100).toFixed(0)}%)`;
        ctx.font = 'bold 14px Arial';
        ctx.fillStyle = detection.zone ? 'rgba(76, 175, 80, 0.9)' : 'rgba(255, 152, 0, 0.9)';
        const textWidth = ctx.measureText(label).width;
        ctx.fillRect(x1, y1 - 22, textWidth + 10, 22);

        // Draw label text
        ctx.fillStyle = '#ffffff';
        ctx.fillText(label, x1 + 5, y1 - 6);

        // Draw centroid point
        const cx = detection.centroid.x_pct !== undefined ? detection.centroid.x_pct * canvas.width : (detection.centroid.x / frameSize.width) * canvas.width;
        const cy = detection.centroid.y_pct !== undefined ? detection.centroid.y_pct * canvas.height : (detection.centroid.y / frameSize.height) * canvas.height;
        ctx.fillStyle = '#ff0000';
        ctx.beginPath();
        ctx.arc(cx, cy, 5, 0, 2 * Math.PI);
        ctx.fill();

        // Draw zone info if available
        if (detection.zone) {
          ctx.fillStyle = 'rgba(76, 175, 80, 0.9)';
          ctx.font = '12px Arial';
          ctx.fillText(`Zone: ${detection.zone}`, x1, y2 + 18);
        }
      });
    };

    // Draw immediately
    drawOverlay();

    // Re-draw when video loads or resizes
    const video = videoRef.current;
    if (video) {
      const handleLoad = () => {
        setTimeout(drawOverlay, 100); // Small delay to ensure dimensions are set
      };
      const handleResize = () => {
        setTimeout(drawOverlay, 100);
      };

      video.addEventListener('load', handleLoad);
      window.addEventListener('resize', handleResize);

      return () => {
        video.removeEventListener('load', handleLoad);
        window.removeEventListener('resize', handleResize);
      };
    }
  }, [detections, frameSize, savedZones]);

  // WebSocket connection untuk deteksi real-time
  useEffect(() => {
    if (!branchId) return;

    // Connect ke WebSocket untuk detections
    const wsUrl = `ws://localhost:8000/ws/detections/${branchId}`;
    const ws = new WebSocket(wsUrl);
    wsRef.current = ws;

    ws.onopen = () => {
      console.log('[WebSocket] Connected for real-time detections');
    };

    ws.onmessage = (event) => {
      try {
        const data = JSON.parse(event.data);
        setDetections(data.detections || []);
        setFrameSize(data.frame_size || { width: 0, height: 0 });
      } catch (err) {
        console.error('Error parsing WebSocket message:', err);
      }
    };

    ws.onerror = (error) => {
      console.error('[WebSocket] Error:', error);
      // Fallback ke HTTP polling jika WebSocket error
      loadDetections();
    };

    ws.onclose = () => {
      console.log('[WebSocket] Disconnected');
      // Reconnect setelah 3 detik
      setTimeout(() => {
        if (wsRef.current === ws) {
          // Reconnect akan dilakukan oleh useEffect saat branchId masih sama
        }
      }, 3000);
    };

    // Cleanup
    return () => {
      if (ws) {
        ws.close();
      }
      wsRef.current = null;
    };
  }, [branchId]);

  // WebSocket connection untuk zone states, billing, dan alerts real-time
  useEffect(() => {
    if (!branchId) return;

    // Connect ke WebSocket untuk data (zone states, billing, alerts)
    const wsDataUrl = `ws://localhost:8000/ws/data/${branchId}`;
    const wsData = new WebSocket(wsDataUrl);
    wsDataRef.current = wsData;

    wsData.onopen = () => {
      console.log('[WebSocket] Connected for real-time data (zone states, billing, alerts)');
    };

    wsData.onmessage = (event) => {
      try {
        const data = JSON.parse(event.data);
        if (data.type === 'data_update') {
          // Update zone_states hanya jika ada data (tidak replace dengan empty object)
          if (data.zone_states && Object.keys(data.zone_states).length > 0) {
            setZoneStates(data.zone_states);
          }
          // Update billing hanya jika ada data
          if (data.billing && Array.isArray(data.billing)) {
            setBillingData(data.billing);
          }
        }
      } catch (err) {
        console.error('Error parsing WebSocket data message:', err);
      }
    };

    wsData.onerror = (error) => {
      console.error('[WebSocket Data] Error:', error);
      // Fallback ke HTTP polling jika WebSocket error
      loadZoneStates();
      loadBillingData();
    };

    wsData.onclose = () => {
      console.log('[WebSocket Data] Disconnected');
      // Reconnect setelah 3 detik
      setTimeout(() => {
        if (wsDataRef.current === wsData) {
          // Reconnect akan dilakukan oleh useEffect saat branchId masih sama
        }
      }, 3000);
    };

    // Cleanup
    return () => {
      if (wsData) {
        wsData.close();
      }
      wsDataRef.current = null;
    };
  }, [branchId]);

  useEffect(() => {
    if (branchId) {
      loadSavedZones(); // Load zones saat branchId berubah (hanya sekali, tidak perlu real-time)
      // Zone states dan billing sekarang via WebSocket (real-time)
      // Hanya load sekali untuk initial data
      loadBillingData();
      loadZoneStates();
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [branchId]);

  return (
    <Box sx={{ width: '100%', px: 0 }}>
      <Typography variant="h5" component="h2" gutterBottom fontWeight="bold">
        Live Monitor - Cabang ID: {branchId}
      </Typography>

      <Grid container spacing={2} sx={{ mt: 1, width: '100%' }}>
        {/* Video Feed Section */}
        <Grid item xs={12} lg={8}>
          <Paper elevation={3} sx={{ p: 1, height: 'fit-content' }}>
            <Box sx={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', mb: 2 }}>
              <Box sx={{ display: 'flex', alignItems: 'center', gap: 1 }}>
                <Videocam color="primary" />
                <Typography variant="h6" component="h3">
                  Video Feed
                </Typography>
              </Box>
              <Chip label="Streaming: MJPEG" size="small" color="primary" variant="outlined" />
            </Box>

            <Box
              sx={{
                position: 'relative',
                width: '100%',
                backgroundColor: '#000',
                borderRadius: 2,
                overflow: 'hidden',
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'center',
                minHeight: 400,
              }}>
              {loading && !error && (
                <Box sx={{ textAlign: 'center', py: 8 }}>
                  <CircularProgress />
                  <Typography variant="body2" color="text.secondary" sx={{ mt: 2 }}>
                    Memuat snapshot...
                  </Typography>
                </Box>
              )}

              {error && (
                <Alert severity="error" sx={{ m: 2 }}>
                  {error}
                  <Typography variant="body2" sx={{ mt: 1 }}>
                    Pastikan backend FastAPI berjalan di http://localhost:8000
                  </Typography>
                </Alert>
              )}

              {imageUrl && !error && (
                <Box
                  sx={{
                    position: 'relative',
                    width: '100%',
                    display: 'flex',
                    alignItems: 'center',
                    justifyContent: 'center',
                  }}>
                  <img
                    ref={videoRef}
                    src={imageUrl}
                    alt={`Live monitor cabang ${branchId}`}
                    style={{
                      width: '100%',
                      height: 'auto',
                      display: 'block',
                      objectFit: 'contain',
                      imageRendering: 'auto', // Smooth rendering
                      willChange: 'contents', // Hint browser untuk optimasi
                      backfaceVisibility: 'hidden', // Mencegah flickering
                      transform: 'translateZ(0)', // Force hardware acceleration
                    }}
                    onLoad={() => {
                      setLoading(false);
                      setError('');
                    }}
                    onError={(e) => {
                      console.error('Stream error:', e);
                      setLoading(false);
                      setError('Gagal memuat stream. Periksa koneksi kamera atau backend.');
                    }}
                  />
                  <canvas
                    ref={canvasRef}
                    style={{
                      position: 'absolute',
                      top: 0,
                      left: 0,
                      width: '100%',
                      height: '100%',
                      pointerEvents: 'none', // Tidak memblokir klik - hanya untuk overlay drawing
                      zIndex: 10,
                    }}
                  />
                </Box>
              )}
            </Box>

            {/* Detections Info */}
            {detections.length > 0 && (
              <Accordion sx={{ mt: 2 }}>
                <AccordionSummary expandIcon={<ExpandMore />}>
                  <Box sx={{ display: 'flex', alignItems: 'center', gap: 1 }}>
                    <LocationOn color="primary" />
                    <Typography variant="subtitle1">Object Detections ({detections.length})</Typography>
                  </Box>
                </AccordionSummary>
                <AccordionDetails>
                  <TableContainer>
                    <Table size="small">
                      <TableHead>
                        <TableRow>
                          <TableCell>
                            <strong>Object</strong>
                          </TableCell>
                          <TableCell>
                            <strong>Confidence</strong>
                          </TableCell>
                          <TableCell>
                            <strong>Koordinat</strong>
                          </TableCell>
                          <TableCell>
                            <strong>Zone</strong>
                          </TableCell>
                        </TableRow>
                      </TableHead>
                      <TableBody>
                        {detections.map((det, idx) => (
                          <TableRow key={idx}>
                            <TableCell>
                              <Chip label={det.name} size="small" color="primary" />
                            </TableCell>
                            <TableCell>{(det.confidence * 100).toFixed(1)}%</TableCell>
                            <TableCell>
                              <Typography variant="caption" component="div">
                                Centroid: ({det.centroid.x.toFixed(0)}, {det.centroid.y.toFixed(0)})
                              </Typography>
                              <Typography variant="caption" component="div" color="text.secondary">
                                BBox: ({det.bbox.x1.toFixed(0)}, {det.bbox.y1.toFixed(0)}) - ({det.bbox.x2.toFixed(0)}, {det.bbox.y2.toFixed(0)})
                              </Typography>
                            </TableCell>
                            <TableCell>
                              {det.zone ? (
                                <Chip label={det.zone} size="small" color="success" />
                              ) : (
                                <Typography variant="caption" color="text.secondary">
                                  Tidak ada
                                </Typography>
                              )}
                            </TableCell>
                          </TableRow>
                        ))}
                      </TableBody>
                    </Table>
                  </TableContainer>
                </AccordionDetails>
              </Accordion>
            )}
          </Paper>
        </Grid>

        {/* Right Panel: Zone States, Antrian Kasir, and Billing */}
        <Grid item xs={12} lg={4}>
          <Box sx={{ display: 'flex', flexDirection: 'column', gap: 2 }}>
            {/* Zone States Section */}
            <Paper elevation={3} sx={{ p: 2 }}>
              <Box sx={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', mb: 2 }}>
                <Box sx={{ display: 'flex', alignItems: 'center', gap: 1 }}>
                  <TableRestaurant color="primary" />
                  <Typography variant="h6" component="h3">
                    Status Zona
                  </Typography>
                </Box>
                <Chip label="Real-time" size="small" color="primary" variant="outlined" />
              </Box>

              {Object.keys(zoneStates).length === 0 ? (
                <Typography variant="body2" color="text.secondary" sx={{ textAlign: 'center', py: 2 }}>
                  Belum ada data status zona
                </Typography>
              ) : (
                <Box sx={{ display: 'flex', flexDirection: 'column', gap: 1 }}>
                  {Object.entries(zoneStates).map(([zoneName, zoneState]) => {
                    const zoneType = zoneState.zone_type || 'unknown';
                    let statusInfo = null;

                    // Hanya tampilkan zone dengan tipe 'table' di Status Zona
                    // Zone 'kasir' dan 'queue' ditampilkan di panel Antrian Kasir
                    if (zoneType === 'table') {
                      statusInfo = getTableStatusInfo(zoneState);
                    }

                    // Jika bukan table, skip (tidak tampilkan di Status Zona)
                    if (zoneType !== 'table') {
                      return null;
                    }

                    // Jika statusInfo null, gunakan default status
                    if (!statusInfo) {
                      statusInfo = {
                        label: 'Unknown',
                        color: 'default',
                        icon: <Warning />,
                        description: 'Status tidak diketahui',
                      };
                    }

                    return (
                      <Box key={zoneName} sx={{ p: 1.5, border: '1px solid', borderColor: 'divider', borderRadius: 1 }}>
                        <Box sx={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', mb: 0.5 }}>
                          <Typography variant="subtitle2" fontWeight="bold">
                            {zoneName}
                          </Typography>
                          <Chip icon={statusInfo.icon} label={statusInfo.label} color={statusInfo.color} size="small" variant="outlined" />
                        </Box>
                        {statusInfo.description && (
                          <Typography variant="caption" color="text.secondary">
                            {statusInfo.description}
                          </Typography>
                        )}
                      </Box>
                    );
                  })}
                </Box>
              )}
            </Paper>

            {/* Billing Table Section */}
            <Paper elevation={3} sx={{ p: 2 }}>
              <Box sx={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', mb: 2 }}>
                <Box sx={{ display: 'flex', alignItems: 'center', gap: 1 }}>
                  <Receipt color="secondary" />
                  <Typography variant="h6" component="h3">
                    Tagihan Realtime
                  </Typography>
                </Box>
                <Chip label="Real-time" size="small" color="secondary" variant="outlined" />
              </Box>

              <TableContainer sx={{ maxHeight: 400 }}>
                <Table size="small" stickyHeader>
                  <TableHead>
                    <TableRow>
                      <TableCell>
                        <strong>Zona (Meja)</strong>
                      </TableCell>
                      <TableCell>
                        <strong>Item</strong>
                      </TableCell>
                      <TableCell align="right">
                        <strong>Qty</strong>
                      </TableCell>
                    </TableRow>
                  </TableHead>
                  <TableBody>
                    {billingData.length === 0 ? (
                      <TableRow>
                        <TableCell colSpan={3} align="center" sx={{ py: 4 }}>
                          <Typography variant="body2" color="text.secondary">
                            Belum ada data tagihan
                          </Typography>
                        </TableCell>
                      </TableRow>
                    ) : (
                      billingData.map((row, index) => (
                        <TableRow key={index} hover>
                          <TableCell>{row.zone}</TableCell>
                          <TableCell>{row.item}</TableCell>
                          <TableCell align="right">
                            <Chip label={row.qty} size="small" color="primary" />
                          </TableCell>
                        </TableRow>
                      ))
                    )}
                  </TableBody>
                </Table>
              </TableContainer>
            </Paper>

            {/* Antrian Kasir Section */}
            <Paper elevation={3} sx={{ p: 2 }}>
              <Box sx={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', mb: 2 }}>
                <Box sx={{ display: 'flex', alignItems: 'center', gap: 1 }}>
                  <Queue color="primary" />
                  <Typography variant="h6" component="h3">
                    Antrian Kasir
                  </Typography>
                </Box>
                <Chip label="Real-time" size="small" color="primary" variant="outlined" />
              </Box>

              {(() => {
                // Ambil zone dengan tipe 'kasir' atau 'queue' dari zoneStates
                const queueZones = Object.entries(zoneStates).filter(([zoneName, zoneState]) => {
                  const zoneType = zoneState.zone_type || 'unknown';
                  return zoneType === 'kasir' || zoneType === 'queue';
                });

                if (queueZones.length === 0) {
                  return (
                    <Typography variant="body2" color="text.secondary" sx={{ textAlign: 'center', py: 2 }}>
                      Belum ada zona kasir/antrian
                    </Typography>
                  );
                }

                return (
                  <Box sx={{ display: 'flex', flexDirection: 'column', gap: 1 }}>
                    {queueZones.map(([zoneName, zoneState]) => {
                      const statusInfo = getQueueStatusInfo(zoneState);
                      if (!statusInfo) return null;

                      return (
                        <Box key={zoneName} sx={{ p: 1.5, border: '1px solid', borderColor: 'divider', borderRadius: 1 }}>
                          <Box sx={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', mb: 0.5 }}>
                            <Typography variant="subtitle2" fontWeight="bold">
                              {zoneName}
                            </Typography>
                            <Chip icon={statusInfo.icon} label={statusInfo.label} color={statusInfo.color} size="small" variant="outlined" />
                          </Box>
                          {statusInfo.description && (
                            <Typography variant="caption" color="text.secondary">
                              {statusInfo.description}
                            </Typography>
                          )}
                          {typeof zoneState === 'object' && zoneState.person_count !== undefined && (
                            <Typography variant="body2" sx={{ mt: 0.5 }}>
                              <strong>{zoneState.person_count}</strong> orang dalam antrian
                            </Typography>
                          )}
                        </Box>
                      );
                    })}
                  </Box>
                );
              })()}
            </Paper>
          </Box>
        </Grid>
      </Grid>
    </Box>
  );
};

export default LiveMonitor;
