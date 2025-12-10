import { useState, useEffect } from 'react';
import { reportsAPI, cameraAPI, branchAPI } from '../services/api';
import {
  Box,
  Paper,
  Typography,
  Grid,
  Table,
  TableBody,
  TableCell,
  TableContainer,
  TableHead,
  TableRow,
  Chip,
  Select,
  MenuItem,
  FormControl,
  InputLabel,
  TextField,
  Button,
  Card,
  CardContent,
  CircularProgress,
  Alert,
  Tabs,
  Tab,
} from '@mui/material';
import { Assessment, TableRestaurant, People, AccessTime } from '@mui/icons-material';

const Reports = () => {
  const [tabValue, setTabValue] = useState(0);
  const [cameras, setCameras] = useState([]);
  const [branches, setBranches] = useState([]);
  const [selectedCamera, setSelectedCamera] = useState('');
  const [selectedBranch, setSelectedBranch] = useState('');
  const [startDate, setStartDate] = useState('');
  const [endDate, setEndDate] = useState('');
  const [groupBy, setGroupBy] = useState('day');

  // Table occupancy data
  const [tableData, setTableData] = useState(null);
  const [tableLoading, setTableLoading] = useState(false);
  const [tableError, setTableError] = useState('');

  // Queue data
  const [queueData, setQueueData] = useState(null);
  const [queueLoading, setQueueLoading] = useState(false);
  const [queueError, setQueueError] = useState('');

  // Customer data
  const [customerData, setCustomerData] = useState(null);
  const [customerLoading, setCustomerLoading] = useState(false);
  const [customerError, setCustomerError] = useState('');

  useEffect(() => {
    loadCameras();
    loadBranches();
    // Set default date range (hari ini)
    const today = new Date().toISOString().split('T')[0];
    setStartDate(today);
    setEndDate(today);
  }, []);

  useEffect(() => {
    if (tabValue === 0) {
      loadTableReport();
    } else if (tabValue === 1) {
      loadQueueReport();
    } else if (tabValue === 2) {
      loadCustomerReport();
    }
  }, [tabValue, selectedCamera, selectedBranch, startDate, endDate, groupBy]);

  const loadCameras = async () => {
    try {
      const data = await cameraAPI.getAll();
      setCameras(data);
    } catch (error) {
      console.error('Error loading cameras:', error);
    }
  };

  const loadBranches = async () => {
    try {
      const data = await branchAPI.getAll();
      setBranches(data);
    } catch (error) {
      console.error('Error loading branches:', error);
    }
  };

  const loadTableReport = async () => {
    setTableLoading(true);
    setTableError('');
    try {
      const data = await reportsAPI.getTableOccupancy(selectedCamera || null, startDate || null, endDate || null, groupBy);
      setTableData(data);
    } catch (error) {
      setTableError('Gagal memuat laporan meja: ' + (error.response?.data?.detail || error.message));
      setTableData(null);
    } finally {
      setTableLoading(false);
    }
  };

  const loadQueueReport = async () => {
    setQueueLoading(true);
    setQueueError('');
    try {
      const data = await reportsAPI.getQueueReport(selectedCamera || null, startDate || null, endDate || null, groupBy);
      setQueueData(data);
    } catch (error) {
      setQueueError('Gagal memuat laporan antrian: ' + (error.response?.data?.detail || error.message));
      setQueueData(null);
    } finally {
      setQueueLoading(false);
    }
  };

  const loadCustomerReport = async () => {
    setCustomerLoading(true);
    setCustomerError('');
    try {
      const data = await reportsAPI.getCustomerReport(selectedBranch || null, startDate || null, endDate || null, groupBy);
      setCustomerData(data);
    } catch (error) {
      setCustomerError('Gagal memuat laporan pengunjung: ' + (error.response?.data?.detail || error.message));
      setCustomerData(null);
    } finally {
      setCustomerLoading(false);
    }
  };

  return (
    <Box sx={{ width: '100%', p: 3 }}>
      <Typography variant="h4" component="h1" gutterBottom fontWeight="bold">
        <Assessment sx={{ verticalAlign: 'middle', mr: 1 }} />
        Laporan & Analitik
      </Typography>

      {/* Filter Section */}
      <Paper elevation={2} sx={{ p: 2, mb: 3 }}>
        <Grid container spacing={2} alignItems="center">
          {tabValue !== 2 ? (
            <Grid item xs={12} md={2.4}>
              <FormControl fullWidth>
                <InputLabel>Kamera</InputLabel>
                <Select value={selectedCamera} label="Kamera" onChange={(e) => setSelectedCamera(e.target.value)}>
                  <MenuItem value="">Semua Kamera</MenuItem>
                  {cameras.map((cam) => (
                    <MenuItem key={cam.id} value={cam.id}>
                      Camera {cam.id} - {cam.branch_name || 'N/A'}
                    </MenuItem>
                  ))}
                </Select>
              </FormControl>
            </Grid>
          ) : (
            <Grid item xs={12} md={2.4}>
              <FormControl fullWidth>
                <InputLabel>Cabang</InputLabel>
                <Select value={selectedBranch} label="Cabang" onChange={(e) => setSelectedBranch(e.target.value)}>
                  <MenuItem value="">Semua Cabang</MenuItem>
                  {branches.map((branch) => (
                    <MenuItem key={branch.id} value={branch.id}>
                      {branch.name}
                    </MenuItem>
                  ))}
                </Select>
              </FormControl>
            </Grid>
          )}
          <Grid item xs={12} md={2.4}>
            <TextField fullWidth label="Tanggal Mulai" type="date" value={startDate} onChange={(e) => setStartDate(e.target.value)} InputLabelProps={{ shrink: true }} />
          </Grid>
          <Grid item xs={12} md={2.4}>
            <TextField fullWidth label="Tanggal Akhir" type="date" value={endDate} onChange={(e) => setEndDate(e.target.value)} InputLabelProps={{ shrink: true }} />
          </Grid>
          <Grid item xs={12} md={2.4}>
            <FormControl fullWidth>
              <InputLabel>Group By</InputLabel>
              <Select value={groupBy} label="Group By" onChange={(e) => setGroupBy(e.target.value)}>
                <MenuItem value="day">Per Hari</MenuItem>
                <MenuItem value="month">Per Bulan</MenuItem>
              </Select>
            </FormControl>
          </Grid>
          <Grid item xs={12} md={2.4}>
            <Button
              fullWidth
              variant="contained"
              onClick={() => {
                if (tabValue === 0) loadTableReport();
                else if (tabValue === 1) loadQueueReport();
                else if (tabValue === 2) loadCustomerReport();
              }}
              sx={{ height: '56px' }}>
              Refresh
            </Button>
          </Grid>
        </Grid>
      </Paper>

      {/* Tabs */}
      <Paper elevation={2} sx={{ mb: 3 }}>
        <Tabs value={tabValue} onChange={(e, newValue) => setTabValue(newValue)}>
          <Tab icon={<TableRestaurant />} iconPosition="start" label="Laporan Meja Terisi" />
          <Tab icon={<People />} iconPosition="start" label="Laporan Antrian Penuh" />
          <Tab icon={<AccessTime />} iconPosition="start" label="Laporan Pengunjung" />
        </Tabs>
      </Paper>

      {/* Table Occupancy Report */}
      {tabValue === 0 && (
        <Box>
          {tableLoading && (
            <Box sx={{ display: 'flex', justifyContent: 'center', p: 4 }}>
              <CircularProgress />
            </Box>
          )}

          {tableError && (
            <Alert severity="error" sx={{ mb: 2 }}>
              {tableError}
            </Alert>
          )}

          {tableData && !tableLoading && (
            <>
              {/* Summary Cards */}
              <Grid container spacing={2} sx={{ mb: 3 }}>
                <Grid item xs={12} md={3}>
                  <Card>
                    <CardContent>
                      <Typography color="text.secondary" gutterBottom>
                        Total Meja Terisi
                      </Typography>
                      <Typography variant="h4">{tableData.summary.total_tables_occupied}</Typography>
                    </CardContent>
                  </Card>
                </Grid>
                <Grid item xs={12} md={3}>
                  <Card>
                    <CardContent>
                      <Typography color="text.secondary" gutterBottom>
                        Total Sesi
                      </Typography>
                      <Typography variant="h4">{tableData.summary.total_sessions}</Typography>
                    </CardContent>
                  </Card>
                </Grid>
                <Grid item xs={12} md={3}>
                  <Card>
                    <CardContent>
                      <Typography color="text.secondary" gutterBottom>
                        Total Durasi
                      </Typography>
                      <Typography variant="h4">{tableData.summary.total_duration_formatted}</Typography>
                    </CardContent>
                  </Card>
                </Grid>
                <Grid item xs={12} md={3}>
                  <Card>
                    <CardContent>
                      <Typography color="text.secondary" gutterBottom>
                        Rata-rata Durasi
                      </Typography>
                      <Typography variant="h4">{tableData.summary.avg_duration_formatted}</Typography>
                    </CardContent>
                  </Card>
                </Grid>
              </Grid>

              {/* Daily/Monthly Summary */}
              {tableData.daily_summary && tableData.daily_summary.length > 0 && (
                <Paper elevation={2} sx={{ mb: 3 }}>
                  <Box sx={{ p: 2, borderBottom: '1px solid', borderColor: 'divider' }}>
                    <Typography variant="h6">Rekap {groupBy === 'day' ? 'Per Hari' : 'Per Bulan'}</Typography>
                  </Box>
                  <TableContainer sx={{ maxHeight: 400, overflow: 'auto' }}>
                    <Table stickyHeader>
                      <TableHead>
                        <TableRow>
                          <TableCell>
                            <strong>Tanggal</strong>
                          </TableCell>
                          <TableCell align="right">
                            <strong>Total Sesi</strong>
                          </TableCell>
                          <TableCell align="right">
                            <strong>Total Durasi</strong>
                          </TableCell>
                          <TableCell align="right">
                            <strong>Rata-rata Durasi</strong>
                          </TableCell>
                          <TableCell align="right">
                            <strong>Total Meja Terisi</strong>
                          </TableCell>
                        </TableRow>
                      </TableHead>
                      <TableBody>
                        {(tableData.daily_summary || tableData.monthly_summary).map((row, idx) => (
                          <TableRow key={idx} hover>
                            <TableCell>
                              {groupBy === 'day'
                                ? new Date(row.date).toLocaleDateString('id-ID', { day: 'numeric', month: 'short', year: 'numeric' })
                                : new Date(row.date + '-01').toLocaleDateString('id-ID', { month: 'long', year: 'numeric' })}
                            </TableCell>
                            <TableCell align="right">{row.total_sessions}</TableCell>
                            <TableCell align="right">{row.total_duration_formatted}</TableCell>
                            <TableCell align="right">{row.avg_duration_formatted}</TableCell>
                            <TableCell align="right">{row.total_tables_occupied}</TableCell>
                          </TableRow>
                        ))}
                      </TableBody>
                    </Table>
                  </TableContainer>
                </Paper>
              )}

              {/* Table Summary */}
              <Paper elevation={2} sx={{ mb: 3 }}>
                <Box sx={{ p: 2, borderBottom: '1px solid', borderColor: 'divider' }}>
                  <Typography variant="h6">Rekap per Meja</Typography>
                </Box>
                <TableContainer sx={{ maxHeight: 400, overflow: 'auto' }}>
                  <Table stickyHeader>
                    <TableHead>
                      <TableRow>
                        <TableCell>
                          <strong>Nama Meja</strong>
                        </TableCell>
                        <TableCell align="right">
                          <strong>Total Sesi</strong>
                        </TableCell>
                        <TableCell align="right">
                          <strong>Total Durasi</strong>
                        </TableCell>
                        <TableCell align="right">
                          <strong>Rata-rata Durasi</strong>
                        </TableCell>
                      </TableRow>
                    </TableHead>
                    <TableBody>
                      {tableData.table_summary.length === 0 ? (
                        <TableRow>
                          <TableCell colSpan={4} align="center" sx={{ py: 4 }}>
                            <Typography color="text.secondary">Tidak ada data</Typography>
                          </TableCell>
                        </TableRow>
                      ) : (
                        tableData.table_summary.map((summary, idx) => (
                          <TableRow key={idx} hover>
                            <TableCell>
                              <Chip label={summary.zone_name} color="primary" size="small" />
                            </TableCell>
                            <TableCell align="right">{summary.total_sessions}</TableCell>
                            <TableCell align="right">{summary.total_duration_formatted}</TableCell>
                            <TableCell align="right">{summary.avg_duration_formatted}</TableCell>
                          </TableRow>
                        ))
                      )}
                    </TableBody>
                  </Table>
                </TableContainer>
              </Paper>

              {/* Detail Table */}
              <Paper elevation={2}>
                <Box sx={{ p: 2, borderBottom: '1px solid', borderColor: 'divider' }}>
                  <Typography variant="h6">Detail Sesi</Typography>
                </Box>
                <TableContainer sx={{ maxHeight: 600 }}>
                  <Table stickyHeader size="small">
                    <TableHead>
                      <TableRow>
                        <TableCell>
                          <strong>Meja</strong>
                        </TableCell>
                        <TableCell>
                          <strong>Mulai</strong>
                        </TableCell>
                        <TableCell>
                          <strong>Selesai</strong>
                        </TableCell>
                        <TableCell align="right">
                          <strong>Durasi</strong>
                        </TableCell>
                        <TableCell align="right">
                          <strong>Jumlah Orang</strong>
                        </TableCell>
                      </TableRow>
                    </TableHead>
                    <TableBody>
                      {tableData.details.length === 0 ? (
                        <TableRow>
                          <TableCell colSpan={5} align="center" sx={{ py: 4 }}>
                            <Typography color="text.secondary">Tidak ada data</Typography>
                          </TableCell>
                        </TableRow>
                      ) : (
                        tableData.details.map((detail, idx) => (
                          <TableRow key={idx} hover>
                            <TableCell>
                              <Chip label={detail.zone_name} size="small" />
                            </TableCell>
                            <TableCell>{new Date(detail.start_time).toLocaleString('id-ID')}</TableCell>
                            <TableCell>{detail.end_time ? new Date(detail.end_time).toLocaleString('id-ID') : '-'}</TableCell>
                            <TableCell align="right">
                              <Chip label={detail.duration_formatted} size="small" color="primary" />
                            </TableCell>
                            <TableCell align="right">
                              <Chip label={detail.person_count} size="small" color="secondary" />
                            </TableCell>
                          </TableRow>
                        ))
                      )}
                    </TableBody>
                  </Table>
                </TableContainer>
              </Paper>
            </>
          )}
        </Box>
      )}

      {/* Queue Report */}
      {tabValue === 1 && (
        <Box>
          {queueLoading && (
            <Box sx={{ display: 'flex', justifyContent: 'center', p: 4 }}>
              <CircularProgress />
            </Box>
          )}

          {queueError && (
            <Alert severity="error" sx={{ mb: 2 }}>
              {queueError}
            </Alert>
          )}

          {queueData && !queueLoading && (
            <>
              {/* Summary Cards */}
              <Grid container spacing={2} sx={{ mb: 3 }}>
                <Grid item xs={12} md={3}>
                  <Card>
                    <CardContent>
                      <Typography color="text.secondary" gutterBottom>
                        Total Zone Terpengaruh
                      </Typography>
                      <Typography variant="h4">{queueData.summary.total_zones_affected}</Typography>
                    </CardContent>
                  </Card>
                </Grid>
                <Grid item xs={12} md={3}>
                  <Card>
                    <CardContent>
                      <Typography color="text.secondary" gutterBottom>
                        Total Sesi
                      </Typography>
                      <Typography variant="h4">{queueData.summary.total_sessions}</Typography>
                    </CardContent>
                  </Card>
                </Grid>
                <Grid item xs={12} md={3}>
                  <Card>
                    <CardContent>
                      <Typography color="text.secondary" gutterBottom>
                        Total Durasi
                      </Typography>
                      <Typography variant="h4">{queueData.summary.total_duration_formatted}</Typography>
                    </CardContent>
                  </Card>
                </Grid>
                <Grid item xs={12} md={3}>
                  <Card>
                    <CardContent>
                      <Typography color="text.secondary" gutterBottom>
                        Rata-rata Durasi
                      </Typography>
                      <Typography variant="h4">{queueData.summary.avg_duration_formatted}</Typography>
                    </CardContent>
                  </Card>
                </Grid>
              </Grid>

              {/* Daily/Monthly Summary */}
              {(queueData.daily_summary || queueData.monthly_summary) && (queueData.daily_summary || queueData.monthly_summary).length > 0 && (
                <Paper elevation={2} sx={{ mb: 3 }}>
                  <Box sx={{ p: 2, borderBottom: '1px solid', borderColor: 'divider' }}>
                    <Typography variant="h6">Rekap {groupBy === 'day' ? 'Per Hari' : 'Per Bulan'}</Typography>
                  </Box>
                  <TableContainer sx={{ maxHeight: 400, overflow: 'auto' }}>
                    <Table stickyHeader>
                      <TableHead>
                        <TableRow>
                          <TableCell>
                            <strong>Tanggal</strong>
                          </TableCell>
                          <TableCell align="right">
                            <strong>Total Sesi</strong>
                          </TableCell>
                          <TableCell align="right">
                            <strong>Total Durasi</strong>
                          </TableCell>
                          <TableCell align="right">
                            <strong>Rata-rata Durasi</strong>
                          </TableCell>
                          <TableCell align="right">
                            <strong>Max Durasi</strong>
                          </TableCell>
                        </TableRow>
                      </TableHead>
                      <TableBody>
                        {(queueData.daily_summary || queueData.monthly_summary).map((row, idx) => (
                          <TableRow key={idx} hover>
                            <TableCell>
                              {groupBy === 'day'
                                ? new Date(row.date).toLocaleDateString('id-ID', { day: 'numeric', month: 'short', year: 'numeric' })
                                : new Date(row.date + '-01').toLocaleDateString('id-ID', { month: 'long', year: 'numeric' })}
                            </TableCell>
                            <TableCell align="right">{row.total_sessions}</TableCell>
                            <TableCell align="right">{row.total_duration_formatted}</TableCell>
                            <TableCell align="right">{row.avg_duration_formatted}</TableCell>
                            <TableCell align="right">{row.max_duration_formatted}</TableCell>
                          </TableRow>
                        ))}
                      </TableBody>
                    </Table>
                  </TableContainer>
                </Paper>
              )}

              {/* Zone Summary */}
              <Paper elevation={2} sx={{ mb: 3 }}>
                <Box sx={{ p: 2, borderBottom: '1px solid', borderColor: 'divider' }}>
                  <Typography variant="h6">Rekap per Zone</Typography>
                </Box>
                <TableContainer sx={{ maxHeight: 400, overflow: 'auto' }}>
                  <Table stickyHeader>
                    <TableHead>
                      <TableRow>
                        <TableCell>
                          <strong>Nama Zone</strong>
                        </TableCell>
                        <TableCell align="right">
                          <strong>Total Sesi</strong>
                        </TableCell>
                        <TableCell align="right">
                          <strong>Total Durasi</strong>
                        </TableCell>
                        <TableCell align="right">
                          <strong>Rata-rata Durasi</strong>
                        </TableCell>
                        <TableCell align="right">
                          <strong>Max Antrian</strong>
                        </TableCell>
                      </TableRow>
                    </TableHead>
                    <TableBody>
                      {queueData.zone_summary.length === 0 ? (
                        <TableRow>
                          <TableCell colSpan={5} align="center" sx={{ py: 4 }}>
                            <Typography color="text.secondary">Tidak ada data</Typography>
                          </TableCell>
                        </TableRow>
                      ) : (
                        queueData.zone_summary.map((summary, idx) => (
                          <TableRow key={idx} hover>
                            <TableCell>
                              <Chip label={summary.zone_name} color="warning" size="small" />
                            </TableCell>
                            <TableCell align="right">{summary.total_sessions}</TableCell>
                            <TableCell align="right">{summary.total_duration_formatted}</TableCell>
                            <TableCell align="right">{summary.avg_duration_formatted}</TableCell>
                            <TableCell align="right">
                              <Chip label={summary.max_queue_count} size="small" color="error" />
                            </TableCell>
                          </TableRow>
                        ))
                      )}
                    </TableBody>
                  </Table>
                </TableContainer>
              </Paper>

              {/* Detail Table */}
              <Paper elevation={2}>
                <Box sx={{ p: 2, borderBottom: '1px solid', borderColor: 'divider' }}>
                  <Typography variant="h6">Detail Sesi</Typography>
                </Box>
                <TableContainer sx={{ maxHeight: 600 }}>
                  <Table stickyHeader size="small">
                    <TableHead>
                      <TableRow>
                        <TableCell>
                          <strong>Zone</strong>
                        </TableCell>
                        <TableCell>
                          <strong>Mulai</strong>
                        </TableCell>
                        <TableCell>
                          <strong>Selesai</strong>
                        </TableCell>
                        <TableCell align="right">
                          <strong>Durasi</strong>
                        </TableCell>
                        <TableCell align="right">
                          <strong>Max Antrian</strong>
                        </TableCell>
                      </TableRow>
                    </TableHead>
                    <TableBody>
                      {queueData.details.length === 0 ? (
                        <TableRow>
                          <TableCell colSpan={5} align="center" sx={{ py: 4 }}>
                            <Typography color="text.secondary">Tidak ada data</Typography>
                          </TableCell>
                        </TableRow>
                      ) : (
                        queueData.details.map((detail, idx) => (
                          <TableRow key={idx} hover>
                            <TableCell>
                              <Chip label={detail.zone_name} size="small" />
                            </TableCell>
                            <TableCell>{new Date(detail.start_time).toLocaleString('id-ID')}</TableCell>
                            <TableCell>{detail.end_time ? new Date(detail.end_time).toLocaleString('id-ID') : '-'}</TableCell>
                            <TableCell align="right">
                              <Chip label={detail.duration_formatted} size="small" color="warning" />
                            </TableCell>
                            <TableCell align="right">
                              <Chip label={detail.max_queue_count} size="small" color="error" />
                            </TableCell>
                          </TableRow>
                        ))
                      )}
                    </TableBody>
                  </Table>
                </TableContainer>
              </Paper>
            </>
          )}
        </Box>
      )}

      {/* Customer Report */}
      {tabValue === 2 && (
        <Box>
          {customerLoading && (
            <Box sx={{ display: 'flex', justifyContent: 'center', p: 4 }}>
              <CircularProgress />
            </Box>
          )}

          {customerError && (
            <Alert severity="error" sx={{ mb: 2 }}>
              {customerError}
            </Alert>
          )}

          {customerData && !customerLoading && (
            <>
              {/* Summary Cards */}
              <Grid container spacing={2} sx={{ mb: 3 }}>
                <Grid item xs={12} md={3}>
                  <Card>
                    <CardContent>
                      <Typography color="text.secondary" gutterBottom>
                        Total Pengunjung
                      </Typography>
                      <Typography variant="h4">{customerData.summary.total_customers}</Typography>
                    </CardContent>
                  </Card>
                </Grid>
                <Grid item xs={12} md={3}>
                  <Card>
                    <CardContent>
                      <Typography color="text.secondary" gutterBottom>
                        Regular
                      </Typography>
                      <Typography variant="h4" color="success.main">
                        {customerData.summary.regular_customers}
                      </Typography>
                    </CardContent>
                  </Card>
                </Grid>
                <Grid item xs={12} md={3}>
                  <Card>
                    <CardContent>
                      <Typography color="text.secondary" gutterBottom>
                        New
                      </Typography>
                      <Typography variant="h4" color="warning.main">
                        {customerData.summary.new_customers}
                      </Typography>
                    </CardContent>
                  </Card>
                </Grid>
                <Grid item xs={12} md={3}>
                  <Card>
                    <CardContent>
                      <Typography color="text.secondary" gutterBottom>
                        Total Kunjungan
                      </Typography>
                      <Typography variant="h4">{customerData.summary.total_visits}</Typography>
                    </CardContent>
                  </Card>
                </Grid>
              </Grid>

              {/* Daily/Monthly Summary */}
              {(customerData.daily_summary || customerData.monthly_summary) && (customerData.daily_summary || customerData.monthly_summary).length > 0 && (
                <Paper elevation={2} sx={{ mb: 3 }}>
                  <Box sx={{ p: 2, borderBottom: '1px solid', borderColor: 'divider' }}>
                    <Typography variant="h6">Rekap {groupBy === 'day' ? 'Per Hari' : 'Per Bulan'}</Typography>
                  </Box>
                  <TableContainer sx={{ maxHeight: 400, overflow: 'auto' }}>
                    <Table stickyHeader>
                      <TableHead>
                        <TableRow>
                          <TableCell>
                            <strong>Tanggal</strong>
                          </TableCell>
                          <TableCell align="right">
                            <strong>Total Pengunjung</strong>
                          </TableCell>
                          <TableCell align="right">
                            <strong>Regular</strong>
                          </TableCell>
                          <TableCell align="right">
                            <strong>New</strong>
                          </TableCell>
                          <TableCell align="right">
                            <strong>Total Kunjungan</strong>
                          </TableCell>
                        </TableRow>
                      </TableHead>
                      <TableBody>
                        {(customerData.daily_summary || customerData.monthly_summary).map((row, idx) => (
                          <TableRow key={idx} hover>
                            <TableCell>
                              {groupBy === 'day'
                                ? new Date(row.date).toLocaleDateString('id-ID', { day: 'numeric', month: 'short', year: 'numeric' })
                                : new Date(row.date + '-01').toLocaleDateString('id-ID', { month: 'long', year: 'numeric' })}
                            </TableCell>
                            <TableCell align="right">{row.total_customers}</TableCell>
                            <TableCell align="right">
                              <Chip label={row.regular_customers} size="small" color="success" variant="outlined" />
                            </TableCell>
                            <TableCell align="right">
                              <Chip label={row.new_customers} size="small" color="warning" variant="outlined" />
                            </TableCell>
                            <TableCell align="right">{row.visits}</TableCell>
                          </TableRow>
                        ))}
                      </TableBody>
                    </Table>
                  </TableContainer>
                </Paper>
              )}

              {/* Detail Table */}
              <Paper elevation={2}>
                <Box sx={{ p: 2, borderBottom: '1px solid', borderColor: 'divider' }}>
                  <Typography variant="h6">Detail Pengunjung</Typography>
                </Box>
                <TableContainer sx={{ maxHeight: 600 }}>
                  <Table stickyHeader size="small">
                    <TableHead>
                      <TableRow>
                        <TableCell>
                          <strong>Tanggal</strong>
                        </TableCell>
                        <TableCell>
                          <strong>Tipe</strong>
                        </TableCell>
                        <TableCell align="right">
                          <strong>Visit Count</strong>
                        </TableCell>
                        <TableCell>
                          <strong>First Seen</strong>
                        </TableCell>
                        <TableCell>
                          <strong>Last Seen</strong>
                        </TableCell>
                      </TableRow>
                    </TableHead>
                    <TableBody>
                      {customerData.details.length === 0 ? (
                        <TableRow>
                          <TableCell colSpan={5} align="center" sx={{ py: 4 }}>
                            <Typography color="text.secondary">Tidak ada data</Typography>
                          </TableCell>
                        </TableRow>
                      ) : (
                        customerData.details.map((detail, idx) => (
                          <TableRow key={idx} hover>
                            <TableCell>{new Date(detail.date).toLocaleDateString('id-ID')}</TableCell>
                            <TableCell>
                              <Chip label={detail.customer_type === 'regular' ? 'Regular' : 'New'} size="small" color={detail.customer_type === 'regular' ? 'success' : 'warning'} />
                            </TableCell>
                            <TableCell align="right">{detail.visit_count}</TableCell>
                            <TableCell>{new Date(detail.first_seen).toLocaleString('id-ID')}</TableCell>
                            <TableCell>{new Date(detail.last_seen).toLocaleString('id-ID')}</TableCell>
                          </TableRow>
                        ))
                      )}
                    </TableBody>
                  </Table>
                </TableContainer>
              </Paper>
            </>
          )}
        </Box>
      )}
    </Box>
  );
};

export default Reports;
