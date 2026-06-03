import React, { useState, useEffect } from 'react';
import AnylogJsonTable from '../../components/AnylogJsonTable';
import { 
  getNodeStatus, 
  getProcessesEndpoint, 
  getConnectionsEndpoint
} from './nodecheck_api';
import '../../styles/NodecheckPage.css';

const NodecheckPage = ({ node }) => {
  const [results, setResults] = useState({
    status: null,
    processes: null,
    connections: null
  });
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);

  // Auto-run checks when node changes
  useEffect(() => {
    if (node) {
      runChecks();
    }
  }, [node]);

  const runChecks = async () => {
    if (!node) return;

    setLoading(true);
    setError(null);
    setResults({ status: null, processes: null, connections: null });

    try {
      const request = { connection: node };
      
      const [statusResult, processesResult, connectionsResult] = await Promise.all([
        getNodeStatus(request),
        getProcessesEndpoint(request),
        getConnectionsEndpoint(request)
      ]);

      setResults({
        status: statusResult.success ? statusResult : null,
        processes: processesResult.success ? processesResult : null,
        connections: connectionsResult.success ? connectionsResult : null
      });
    } catch (err) {
      setError(err.message || 'Failed to run checks');
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="nodecheck-page">
      <div className="nodecheck-header">
        <h2>Node Check</h2>
        {node && (
          <div className="selected-node-info">
            <span className="node-label">Checking:</span>
            <span className="node-value">{node}</span>
          </div>
        )}
      </div>

      {loading && (
        <div className="loading-section">
          <div className="loading-spinner"></div>
          <p>Running node checks...</p>
        </div>
      )}

      {error && (
        <div className="error-message">
          <strong>Error:</strong> {error}
        </div>
      )}

      <div className="results-grid">
        {/* Status */}
        <div className="result-card status-card">
          <h3>Status</h3>
          {results.status ? (
            <div className="status-content">
              <pre>{typeof results.status.data === 'string' ? results.status.data : JSON.stringify(results.status.data, null, 2)}</pre>
            </div>
          ) : (
            <div className="no-data">No status data</div>
          )}
        </div>

        {/* Tables Row */}
        <div className="tables-row">
          {/* Processes */}
          <div className="result-card">
            <h3>Processes</h3>
            {results.processes ? (
              results.processes.data && typeof results.processes.data === 'object' && !Array.isArray(results.processes.data) ? (
                <AnylogJsonTable data={results.processes.data} />
              ) : (
                <div className="result-content">
                  <pre>{JSON.stringify(results.processes.data, null, 2)}</pre>
                </div>
              )
            ) : (
              <div className="no-data">No processes data</div>
            )}
          </div>

          {/* Connections */}
          <div className="result-card">
            <h3>Connections</h3>
            {results.connections ? (
              results.connections.data && typeof results.connections.data === 'object' && !Array.isArray(results.connections.data) ? (
                <AnylogJsonTable data={results.connections.data} />
              ) : (
                <div className="result-content">
                  <pre>{JSON.stringify(results.connections.data, null, 2)}</pre>
                </div>
              )
            ) : (
              <div className="no-data">No connections data</div>
            )}
          </div>
        </div>
      </div>
    </div>
  );
};

// Plugin metadata - used by the plugin loader
export const pluginMetadata = {
  name: 'Node Check',
  icon: null // Optional: add an icon emoji here if desired
};

export default NodecheckPage;
