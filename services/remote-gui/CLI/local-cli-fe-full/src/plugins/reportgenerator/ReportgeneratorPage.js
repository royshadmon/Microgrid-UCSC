import React, { useState, useEffect, useCallback } from 'react';
import '../../styles/ReportgeneratorPage.css';

// Plugin metadata - used by the plugin loader
export const pluginMetadata = {
  name: 'Report Generator',
  icon: null // Optional: add an icon emoji here if desired
};

const ReportgeneratorPage = ({ node }) => {
  const [reports, setReports] = useState([]);
  const [selectedReport, setSelectedReport] = useState('');
  const [selectedReportConfig, setSelectedReportConfig] = useState(null); // Store full config for selected report
  const [monitorIds, setMonitorIds] = useState([]);
  const [selectedMonitorId, setSelectedMonitorId] = useState('');
  
  // Report parameters
  const [incrementUnit, setIncrementUnit] = useState('hour');
  const [incrementValue, setIncrementValue] = useState(1);
  const [timeColumn, setTimeColumn] = useState('timestamp');
  const [startTime, setStartTime] = useState('');
  const [endTime, setEndTime] = useState('');
  const [pageOrientation, setPageOrientation] = useState('portrait');
  
  // UI state
  const [loading, setLoading] = useState(false);
  const [loadingReports, setLoadingReports] = useState(false);
  const [loadingMonitorIds, setLoadingMonitorIds] = useState(false);
  const [error, setError] = useState(null);
  const [success, setSuccess] = useState(null);
  const [pdfUrl, setPdfUrl] = useState(null);
  const [pdfFilename, setPdfFilename] = useState(null);
  
  // Import/Export state
  const [importFiles, setImportFiles] = useState([]);
  const [importPreview, setImportPreview] = useState(null);
  const [importing, setImporting] = useState(false);
  const [conflictingFiles, setConflictingFiles] = useState([]);
  const [currentConflictIndex, setCurrentConflictIndex] = useState(0);
  const [filesToOverwrite, setFilesToOverwrite] = useState(new Set());
  const [replaceAll, setReplaceAll] = useState(false);

  // Helper function to convert Date to date format (YYYY-MM-DD)
  const formatDateForInput = (date) => {
    const year = date.getFullYear();
    const month = String(date.getMonth() + 1).padStart(2, '0');
    const day = String(date.getDate()).padStart(2, '0');
    return `${year}-${month}-${day}`;
  };

  // Helper function to convert date format to backend format (YYYY-MM-DD 00:00:00)
  const convertToBackendFormat = (dateString) => {
    if (!dateString) return '';
    // date format: YYYY-MM-DD
    // backend format: YYYY-MM-DD 00:00:00
    return `${dateString} 00:00:00`;
  };

  // Set default date values
  useEffect(() => {
    const now = new Date();
    const yesterday = new Date(now);
    yesterday.setDate(yesterday.getDate() - 1);

    if (!startTime) {
      setStartTime(formatDateForInput(yesterday));
    }
    if (!endTime) {
      setEndTime(formatDateForInput(now));
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []); // Only run on mount to set initial default values

  // Cleanup blob URL when component unmounts or PDF changes
  useEffect(() => {
    return () => {
      if (pdfUrl) {
        window.URL.revokeObjectURL(pdfUrl);
      }
    };
  }, [pdfUrl]);

  const handleDownload = () => {
    if (pdfUrl && pdfFilename) {
      const link = document.createElement('a');
      link.href = pdfUrl;
      link.download = pdfFilename;
      document.body.appendChild(link);
      link.click();
      document.body.removeChild(link);
    }
  };

  const fetchReports = async () => {
    try {
      setLoadingReports(true);
      const API_URL = window._env_?.REACT_APP_API_URL || "http://localhost:8000";
      const response = await fetch(`${API_URL}/reportgenerator/list-reports/`, {
        method: 'GET',
        headers: {
          'Content-Type': 'application/json',
        },
      });

      if (!response.ok) {
        throw new Error('Failed to fetch reports');
      }

      const data = await response.json();
      setReports(data.reports || []);
    } catch (err) {
      setError(err.message);
    } finally {
      setLoadingReports(false);
    }
  };

  const fetchMonitorIds = useCallback(async () => {
    if (!selectedReport || !node) return;

    try {
      setLoadingMonitorIds(true);
      const API_URL = window._env_?.REACT_APP_API_URL || "http://localhost:8000";
      const response = await fetch(`${API_URL}/reportgenerator/monitor-ids-by-report/`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({
          connection: node,
          report_config_name: selectedReport,
        }),
      });

      if (!response.ok) {
        throw new Error('Failed to fetch monitor IDs');
      }

      const data = await response.json();
      // Parse response to extract monitor IDs
      const ids = data.monitor_ids?.map(id => {
        if (typeof id === 'string') return id;
        if (id.monitor_id) return id.monitor_id;
        return id;
      }) || [];
      setMonitorIds(ids);
    } catch (err) {
      setError(err.message);
      setMonitorIds([]);
    } finally {
      setLoadingMonitorIds(false);
    }
  }, [selectedReport, node]);

  // Fetch available reports on component mount
  useEffect(() => {
    if (node) {
      fetchReports();
    }
  }, [node]);

  // Fetch monitor IDs when report is selected (only if monitor_id not in config)
  useEffect(() => {
    if (selectedReport && node) {
      // Find the selected report config
      const report = reports.find(r => r.name === selectedReport);
      if (report) {
        setSelectedReportConfig(report);
        // Only fetch monitor IDs if monitor_id is not configured in the report
        if (!report.monitor_id) {
          fetchMonitorIds();
        } else {
          // Monitor ID is configured, clear monitor IDs and use the one from config
          setMonitorIds([]);
          setSelectedMonitorId(report.monitor_id);
        }
      }
    } else {
      setSelectedReportConfig(null);
      setMonitorIds([]);
      setSelectedMonitorId('');
    }
  }, [selectedReport, node, reports, fetchMonitorIds]);

  const handleGenerateReport = async () => {
    // Check if monitor_id is required (not in config)
    const monitorIdRequired = !selectedReportConfig || !selectedReportConfig.monitor_id;
    const effectiveMonitorId = selectedReportConfig?.monitor_id || selectedMonitorId;
    
    if (!node || !selectedReport || (monitorIdRequired && !effectiveMonitorId)) {
      setError('Please select Report' + (monitorIdRequired ? ' and Monitor ID' : ''));
      return;
    }

    if (!startTime || !endTime) {
      setError('Please provide both start and end times');
      return;
    }

    setLoading(true);
    setError(null);
    setSuccess(null);

    try {
      // Convert datetime-local format to backend format
      const backendStartTime = convertToBackendFormat(startTime);
      const backendEndTime = convertToBackendFormat(endTime);

      const request = {
        connection: node,
        report_config_name: selectedReport,
        increment_unit: incrementUnit,
        increment_value: incrementValue,
        time_column: timeColumn,
        start_time: backendStartTime,
        end_time: backendEndTime,
        monitor_id: effectiveMonitorId, // Use from config if available, otherwise from selection
        page_orientation: pageOrientation
      };

      const API_URL = window._env_?.REACT_APP_API_URL || "http://localhost:8000";
      const url = `${API_URL}/reportgenerator/generate-report`;
      
      // Make request to get PDF file
      const response = await fetch(url, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify(request)
      });

      if (!response.ok) {
        const errorData = await response.json().catch(() => ({}));
        throw new Error(errorData.detail || `HTTP error! status: ${response.status}`);
      }

      // Get the PDF blob
      const blob = await response.blob();
      
      // Create a blob URL for viewing in browser
      const blobUrl = window.URL.createObjectURL(blob);
      const filename = `power_monitoring_report_${new Date().getTime()}.pdf`;
      
      // Store the PDF URL and filename for display
      setPdfUrl(blobUrl);
      setPdfFilename(filename);
      setSuccess('Report generated successfully! View it below or download using the button.');
    } catch (err) {
      setError(err.message || 'Failed to generate report');
    } finally {
      setLoading(false);
    }
  };

  // Import functionality
  const handleFileUpload = (event) => {
    const files = Array.from(event.target.files);
    if (!files || files.length === 0) return;

    // Validate file types
    const validFiles = files.filter(file => {
      const isZip = file.name.endsWith('.zip');
      const isJson = file.name.endsWith('.json');
      const isYaml = file.name.endsWith('.yaml') || file.name.endsWith('.yml');
      return isZip || isJson || isYaml;
    });

    if (validFiles.length === 0) {
      setError("Please select valid files (.zip, .json, .yaml, or .yml)");
      return;
    }

    if (validFiles.length < files.length) {
      setError(`Some files were skipped. Only .zip, .json, .yaml, and .yml files are supported.`);
    }

    setImportFiles(validFiles);
    setError("");
    setSuccess(null);

    // Preview: Try to read first JSON file if available, or show file list
    const firstJsonFile = validFiles.find(f => f.name.endsWith('.json'));
    if (firstJsonFile && !validFiles.find(f => f.name.endsWith('.zip'))) {
      const reader = new FileReader();
      reader.onload = (e) => {
        try {
          const jsonData = JSON.parse(e.target.result);
          setImportPreview(jsonData);
          
          // Validate structure
          if (jsonData.db_name || jsonData.title) {
            setSuccess(`Single config file detected. ${validFiles.length} file(s) selected.`);
          } else {
            setSuccess(`${validFiles.length} file(s) selected.`);
            setImportPreview(null);
          }
        } catch (parseError) {
          setSuccess(`${validFiles.length} file(s) selected.`);
          setImportPreview(null);
        }
      };
      reader.readAsText(firstJsonFile);
    } else {
      // ZIP or multiple files - just show file list
      setSuccess(`${validFiles.length} file(s) selected${validFiles.find(f => f.name.endsWith('.zip')) ? ' (ZIP archive)' : ''}`);
      setImportPreview(null);
    }
  };

  const handleImport = async () => {
    if (!importFiles || importFiles.length === 0) {
      setError("Please select file(s) to import");
      return;
    }

    setImporting(true);
    setError("");
    setSuccess(null);

    try {
      const API_URL = window._env_?.REACT_APP_API_URL || "http://localhost:8000";
      
      // Step 1: Check for conflicts
      const checkFormData = new FormData();
      importFiles.forEach(file => {
        checkFormData.append('files', file);
      });

      const checkResponse = await fetch(`${API_URL}/reportgenerator/import-config-check`, {
        method: 'POST',
        body: checkFormData,
      });

      if (!checkResponse.ok) {
        const errorData = await checkResponse.json().catch(() => ({}));
        throw new Error(errorData.detail || `HTTP error! status: ${checkResponse.status}`);
      }

      const checkData = await checkResponse.json();
      
      // Step 2: Handle conflicts if any
      if (checkData.has_conflicts && checkData.conflicting_files.length > 0) {
        setConflictingFiles(checkData.conflicting_files);
        setCurrentConflictIndex(0);
        setFilesToOverwrite(new Set());
        setReplaceAll(false);
        setImporting(false);
        return; // Will resume after user makes choices
      }

      // Step 3: No conflicts, proceed with import
      await performImport(new Set());
    } catch (err) {
      setError(`Import failed: ${err.message}`);
      setImporting(false);
    }
  };

  const handleConflictChoice = (choice) => {
    const currentFile = conflictingFiles[currentConflictIndex];
    
    if (choice === 'replace-all') {
      // Add all remaining conflicts to overwrite set
      const allConflicts = new Set(conflictingFiles);
      setFilesToOverwrite(allConflicts);
      setReplaceAll(true);
      // Proceed with import
      performImport(allConflicts);
    } else if (choice === 'replace') {
      // Add current file to overwrite set
      const newSet = new Set(filesToOverwrite);
      newSet.add(currentFile);
      setFilesToOverwrite(newSet);
      
      // Move to next conflict or proceed with import
      if (currentConflictIndex < conflictingFiles.length - 1) {
        setCurrentConflictIndex(currentConflictIndex + 1);
      } else {
        // All conflicts handled, proceed with import
        performImport(newSet);
      }
    } else if (choice === 'skip') {
      // Don't add to overwrite set, move to next or proceed
      if (currentConflictIndex < conflictingFiles.length - 1) {
        setCurrentConflictIndex(currentConflictIndex + 1);
      } else {
        // All conflicts handled, proceed with import
        performImport(filesToOverwrite);
      }
    } else if (choice === 'cancel') {
      // Cancel import
      handleCancelImport();
      setConflictingFiles([]);
      setCurrentConflictIndex(0);
    }
  };

  const performImport = async (overwriteSet) => {
    setImporting(true);
    setError("");
    setSuccess(null);

    try {
      const API_URL = window._env_?.REACT_APP_API_URL || "http://localhost:8000";
      const formData = new FormData();
      
      // Append all files
      importFiles.forEach(file => {
        formData.append('files', file);
      });
      
      // Send files to overwrite as JSON string
      if (overwriteSet.size > 0) {
        formData.append('overwrite_files', JSON.stringify(Array.from(overwriteSet)));
      }

      const response = await fetch(`${API_URL}/reportgenerator/import-config`, {
        method: 'POST',
        body: formData,
      });

      if (!response.ok) {
        const errorData = await response.json().catch(() => ({}));
        throw new Error(errorData.detail || `HTTP error! status: ${response.status}`);
      }

      const data = await response.json();
      
      if (data.errors && data.errors.length > 0) {
        setError(`${data.message}. Errors: ${data.errors.join('; ')}`);
      } else {
        setSuccess(data.message || `Successfully imported ${data.count || 1} config(s)!`);
      }
      
      // Reload reports list
      await fetchReports();

      // Clear everything after successful import (or even if there were errors)
      setTimeout(() => {
        setImportFiles([]);
        setImportPreview(null);
        setConflictingFiles([]);
        setCurrentConflictIndex(0);
        setFilesToOverwrite(new Set());
        setReplaceAll(false);
        // Reset file input
        const fileInput = document.querySelector('#config-file-input');
        if (fileInput) fileInput.value = '';
        // Only clear success/error messages if import was successful
        if (!data.errors || data.errors.length === 0) {
          setError("");
          setSuccess(null);
        }
      }, 3000);
    } catch (err) {
      setError(`Import failed: ${err.message}`);
    } finally {
      setImporting(false);
    }
  };

  const handleCancelImport = () => {
    setImportFiles([]);
    setImportPreview(null);
    setConflictingFiles([]);
    setCurrentConflictIndex(0);
    setFilesToOverwrite(new Set());
    setReplaceAll(false);
    setError("");
    setSuccess(null);
    // Reset file input
    const fileInput = document.querySelector('#config-file-input');
    if (fileInput) fileInput.value = '';
  };

  // Export functionality
  const handleExport = async () => {
    if (reports.length === 0) {
      setError("No report configs to export");
      return;
    }

    try {
      const API_URL = window._env_?.REACT_APP_API_URL || "http://localhost:8000";
      const response = await fetch(`${API_URL}/reportgenerator/export-configs`, {
        method: 'GET',
      });

      if (!response.ok) {
        const errorData = await response.json().catch(() => ({}));
        throw new Error(errorData.detail || `HTTP error! status: ${response.status}`);
      }

      // Get the ZIP file blob
      const blob = await response.blob();
      
      // Get filename from Content-Disposition header or use default
      const contentDisposition = response.headers.get('Content-Disposition');
      let filename = `report-configs-export-${new Date().toISOString().split('T')[0]}.zip`;
      if (contentDisposition) {
        const filenameMatch = contentDisposition.match(/filename="?(.+)"?/i);
        if (filenameMatch) {
          filename = filenameMatch[1];
        }
      }
      
      // Create download link
      const url = URL.createObjectURL(blob);
      const link = document.createElement('a');
      link.href = url;
      link.download = filename;
      document.body.appendChild(link);
      link.click();
      document.body.removeChild(link);
      URL.revokeObjectURL(url);

      setSuccess(`Exported ${reports.length} report config(s) as ZIP file`);
    } catch (err) {
      setError(`Export failed: ${err.message}`);
    }
  };

  // Check if monitor_id is required (not in config)
  const monitorIdFromConfig = selectedReportConfig?.monitor_id;
  const hasMonitorId = monitorIdFromConfig || selectedMonitorId;
  const canGenerateReport = node && selectedReport && hasMonitorId && startTime && endTime;

  return (
    <div className="reportgenerator-page">
      <div className="reportgenerator-header">
        <h2>Report Generator</h2>
        {node && (
          <div className="selected-node-info">
            <span className="node-label">Node:</span>
            <span className="node-value">{node}</span>
          </div>
        )}
      </div>

      {/* Import/Export Section */}
      <section className="import-section">
        <h2>📁 Import Report Configs from JSON</h2>
        <div className="import-container">
          <div className="import-export-actions">
            <input
              id="config-file-input"
              type="file"
              accept=".zip,.json,.yaml,.yml"
              multiple
              onChange={handleFileUpload}
              disabled={importing}
              className="file-input"
            />
            <button 
              onClick={handleExport} 
              disabled={reports.length === 0}
              className="export-btn"
              title="Export all report configs as JSON"
            >
              📤 Export All Configs
            </button>
          </div>
          {importFiles.length > 0 && (
            <div className="file-info">
              <p>Selected {importFiles.length} file(s):</p>
              <ul style={{ listStyle: 'none', padding: 0, margin: '0.5rem 0' }}>
                {importFiles.map((file, index) => (
                  <li key={index} style={{ padding: '0.25rem 0', color: '#495057', fontSize: '0.9rem' }}>
                    {file.name} {file.name.endsWith('.zip') && '(ZIP archive)'}
                  </li>
                ))}
              </ul>
              {importPreview && (
                <div className="import-preview">
                  <h4>Preview (first JSON file):</h4>
                  <ul>
                    <li>
                      <strong>{importPreview.title || importPreview.display_name || 'Unnamed Config'}</strong>
                      {importPreview.db_name && ` - Database: ${importPreview.db_name}`}
                    </li>
                  </ul>
                </div>
              )}
              <div className="import-actions">
                <button 
                  onClick={handleImport} 
                  disabled={importing || conflictingFiles.length > 0}
                  className="import-btn"
                >
                  {importing ? "Importing..." : "Import"}
                </button>
                <button 
                  onClick={handleCancelImport} 
                  disabled={importing}
                  className="cancel-btn"
                >
                  Cancel
                </button>
              </div>
            </div>
          )}

          {/* Conflict Resolution Dialog */}
          {conflictingFiles.length > 0 && currentConflictIndex < conflictingFiles.length && !replaceAll && (
            <div className="file-info" style={{ marginTop: '1rem', border: '2px solid #ffc107', backgroundColor: '#fff3cd' }}>
              <h4 style={{ margin: '0 0 1rem 0', color: '#856404' }}>
                File Already Exists ({currentConflictIndex + 1} of {conflictingFiles.length})
              </h4>
              <p style={{ margin: '0 0 1rem 0', fontWeight: 'bold', color: '#856404' }}>
                {conflictingFiles[currentConflictIndex]}
              </p>
              <p style={{ margin: '0 0 1rem 0', color: '#856404' }}>
                This file already exists. What would you like to do?
              </p>
              <div className="import-actions">
                <button 
                  onClick={() => handleConflictChoice('replace')}
                  className="import-btn"
                  style={{ backgroundColor: '#28a745' }}
                >
                  Replace
                </button>
                <button 
                  onClick={() => handleConflictChoice('skip')}
                  className="cancel-btn"
                  style={{ backgroundColor: '#6c757d' }}
                >
                  Skip
                </button>
                <button 
                  onClick={() => handleConflictChoice('replace-all')}
                  className="import-btn"
                  style={{ backgroundColor: '#17a2b8', marginLeft: 'auto' }}
                >
                  Replace All
                </button>
                <button 
                  onClick={() => handleConflictChoice('cancel')}
                  className="cancel-btn"
                  style={{ backgroundColor: '#dc3545' }}
                >
                  Cancel Import
                </button>
              </div>
            </div>
          )}
        </div>
      </section>

      {error && (
        <div className="error-message">
          <strong>Error:</strong> {error}
        </div>
      )}

      {success && (
        <div className="success-message">
          <strong>Success:</strong> {success}
        </div>
      )}

      <div className="reportgenerator-form">
        {/* Report Selection */}
        <div className="form-section">
          <h3>Step 1: Select Report</h3>
          <div className="form-group">
            <label htmlFor="report-select">Report Type *</label>
            <select
              id="report-select"
              className="form-control"
              value={selectedReport}
              onChange={(e) => setSelectedReport(e.target.value)}
              disabled={loadingReports}
            >
              <option value="">-- Select Report --</option>
              {reports.map((report, idx) => (
                <option key={idx} value={report.name}>
                  {report.display_name || report.title || report.name}
                </option>
              ))}
            </select>
            {loadingReports && <div className="loading-indicator">Loading reports...</div>}
          </div>
        </div>

        {/* Monitor ID Selection - Only show if not configured in report */}
        {selectedReport && !selectedReportConfig?.monitor_id && (
          <div className="form-section">
            <h3>Step 2: Select Monitor ID</h3>
            <div className="form-group">
              <label htmlFor="monitor-select">Monitor ID *</label>
              <select
                id="monitor-select"
                className="form-control"
                value={selectedMonitorId}
                onChange={(e) => setSelectedMonitorId(e.target.value)}
                disabled={loadingMonitorIds}
              >
                <option value="">-- Select Monitor ID --</option>
                {monitorIds.map((id, idx) => (
                  <option key={idx} value={id}>
                    {id}
                  </option>
                ))}
              </select>
              {loadingMonitorIds && <div className="loading-indicator">Loading monitor IDs...</div>}
            </div>
          </div>
        )}
        
        {/* Show configured monitor ID if present */}
        {selectedReport && selectedReportConfig?.monitor_id && (
          <div className="form-section">
            <h3>Step 2: Monitor ID</h3>
            <div className="form-group">
              <label>Monitor ID (from config)</label>
              <div className="config-monitor-id-display">
                {selectedReportConfig.monitor_id}
              </div>
              <small className="form-text text-muted">
                This monitor ID is configured in the report and will be used automatically.
              </small>
            </div>
          </div>
        )}

        {/* Report Parameters */}
        {selectedReport && hasMonitorId && (
          <div className="form-section">
            <h3>Step 3: Configure Report Parameters</h3>
            
            <div className="form-row">
              <div className="form-group">
                <label htmlFor="increment-unit">Increment Unit</label>
                <select
                  id="increment-unit"
                  className="form-control"
                  value={incrementUnit}
                  onChange={(e) => setIncrementUnit(e.target.value)}
                >
                  <option value="minute">Minute</option>
                  <option value="hour">Hour</option>
                  <option value="day">Day</option>
                </select>
              </div>

              <div className="form-group">
                <label htmlFor="increment-value">Increment Value</label>
                <input
                  id="increment-value"
                  type="number"
                  className="form-control"
                  value={incrementValue}
                  onChange={(e) => setIncrementValue(parseInt(e.target.value) || 1)}
                  min="1"
                />
              </div>
            </div>

            <div className="form-group">
              <label htmlFor="time-column">Time Column</label>
              <input
                id="time-column"
                type="text"
                className="form-control"
                value={timeColumn}
                onChange={(e) => setTimeColumn(e.target.value)}
                placeholder="timestamp"
              />
            </div>

            <div className="form-row">
              <div className="form-group">
                <label htmlFor="start-time">Start Date *</label>
                <input
                  id="start-time"
                  type="date"
                  className="form-control"
                  value={startTime}
                  onChange={(e) => setStartTime(e.target.value)}
                />
                <small className="form-help">Time will be set to 00:00:00</small>
              </div>

              <div className="form-group">
                <label htmlFor="end-time">End Date *</label>
                <input
                  id="end-time"
                  type="date"
                  className="form-control"
                  value={endTime}
                  onChange={(e) => setEndTime(e.target.value)}
                />
                <small className="form-help">Time will be set to 00:00:00</small>
              </div>
            </div>

            <div className="form-group">
              <label htmlFor="page-orientation">Page Orientation</label>
              <select
                id="page-orientation"
                className="form-control"
                value={pageOrientation}
                onChange={(e) => setPageOrientation(e.target.value)}
              >
                <option value="landscape">Landscape</option>
                <option value="portrait">Portrait</option>
              </select>
            </div>
          </div>
        )}

        {/* Generate Button */}
        {canGenerateReport && (
          <div className="form-section">
            <button
              className="generate-button"
              onClick={handleGenerateReport}
              disabled={loading}
            >
              {loading ? 'Generating Report...' : 'Generate Report'}
            </button>
          </div>
        )}
      </div>

      {/* PDF Viewer Section */}
      {pdfUrl && (
        <div className="pdf-viewer-section">
          <div className="pdf-viewer-header">
            <h3>Generated Report</h3>
            <button
              className="download-button"
              onClick={handleDownload}
            >
              📥 Download PDF
            </button>
          </div>
          <div className="pdf-viewer-container">
            <iframe
              src={pdfUrl}
              title="Generated Report"
              className="pdf-iframe"
            />
          </div>
        </div>
      )}
    </div>
  );
};

export default ReportgeneratorPage;

