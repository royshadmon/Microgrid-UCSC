

import React, { useState, useRef, useEffect } from 'react';
import MonitorTable from '../components/MonitorTable';
import { monitor } from '../services/api'; // Ensure your API is set up correctly
import '../styles/Monitor.css';

const Monitor = ({ node }) => {
  console.log("Monitor node: ", node);
  const [data, setData] = useState([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);
  
  // Rerun rate in seconds: must be 0 or a multiple of 20.
  const [rerunRate, setRerunRate] = useState(20);
  const [inputError, setInputError] = useState(null);
  const [isMonitoring, setIsMonitoring] = useState(false);
  
  // Ref to store the polling interval
  const intervalRef = useRef(null);

  // Function to fetch monitoring data from the API using the current node.
  const fetchMonitoringData = async () => {
    setLoading(true);
    setError(null);
    try {
      // Pass the node parameter as needed.
      const result = await monitor({ node });
      console.log("Monitoring result:", result);
      // Assume API returns result.data (an array of objects)
      setData(result.data);
    } catch (err) {
      setError("Error occurred while monitoring: " + (err.message || err));
    }
    setLoading(false);
  };

  // Start monitoring: fetch data immediately and, if rerunRate is greater than 0, set up an interval.
  const handleStartMonitoring = () => {
    setIsMonitoring(true);
    fetchMonitoringData();
    // Clear any existing interval.
    if (intervalRef.current) {
      clearInterval(intervalRef.current);
    }
    // If the rerunRate is greater than 0, set an interval.
    if (rerunRate > 0) {
      intervalRef.current = setInterval(() => {
        fetchMonitoringData();
      }, rerunRate * 1000);
    }
  };

  // Stop monitoring by clearing the interval.
  const handleStopMonitoring = () => {
    setIsMonitoring(false);
    if (intervalRef.current) {
      clearInterval(intervalRef.current);
      intervalRef.current = null;
    }
  };

  // Clear the interval when the component unmounts.
  useEffect(() => {
    return () => {
      if (intervalRef.current) {
        clearInterval(intervalRef.current);
      }
    };
  }, []);

  // Auto-dismiss error messages after 5 seconds
  useEffect(() => {
    if (inputError) {
      const timer = setTimeout(() => {
        setInputError(null);
      }, 5000);
      return () => clearTimeout(timer);
    }
  }, [inputError]);

  useEffect(() => {
    if (error) {
      const timer = setTimeout(() => {
        setError(null);
      }, 5000);
      return () => clearTimeout(timer);
    }
  }, [error]);

  // Handle changes to the rerun rate input.
  const handleRerunRateChange = (e) => {
    const newRate = parseInt(e.target.value, 10);
    if (isNaN(newRate)) {
      setInputError("Please enter a valid number.");
      return;
    }
    // Check if newRate is 0 or a multiple of 20.
    if (newRate % 20 !== 0) {
      setInputError("Rerun rate must be 0 or a multiple of 20.");
      return;
    }
    setInputError(null);
    setRerunRate(newRate);
    // If monitoring is running, reset the interval with the new rate.
    if (intervalRef.current) {
      handleStopMonitoring();
      // Only restart if newRate is greater than 0; if it's 0, just run once.
      if (newRate > 0) {
        handleStartMonitoring();
      }
    }
  };

  return (
    <div className="monitor-container">
      <h2>Monitor Node Section</h2>
      <div style={{ marginBottom: '10px' }}>
        <p>
          <strong>Connected Node:</strong> {node}
        </p>
        <div style={{ display: 'flex', alignItems: 'center', gap: '10px', marginBottom: '10px' }}>
          <label htmlFor="rerunRate">
            {isMonitoring ? 'Refresh Rate (seconds):' : 'Refresh Paused:'}
          </label>
          <input
            id="rerunRate"
            type="number"
            min="0"
            step="20"
            value={rerunRate}
            onChange={handleRerunRateChange}
            style={{ 
              width: '100px', 
              backgroundColor: isMonitoring ? 'white' : '#f5f5f5',
              color: isMonitoring ? 'black' : '#666'
            }}
            disabled={!isMonitoring}
          />
          {inputError && <span style={{ color: 'red' }}>{inputError}</span>}
          {isMonitoring && (
            <span style={{ 
              color: '#28a745', 
              fontSize: '14px',
              fontWeight: 'bold',
              display: 'flex',
              alignItems: 'center',
              gap: '5px'
            }}>
              <span style={{ 
                width: '8px', 
                height: '8px', 
                backgroundColor: '#28a745', 
                borderRadius: '50%',
                animation: 'pulse 2s infinite'
              }}></span>
              Monitoring Active
            </span>
          )}
          {!isMonitoring && (
            <span style={{ 
              color: '#dc3545', 
              fontSize: '14px',
              fontWeight: 'bold',
              display: 'flex',
              alignItems: 'center',
              gap: '5px'
            }}>
              <span style={{ 
                width: '8px', 
                height: '8px', 
                backgroundColor: '#dc3545', 
                borderRadius: '50%'
              }}></span>
              Monitoring Paused
            </span>
          )}
        </div>
      </div>
      <div style={{ marginBottom: '10px' }}>
        <button 
          onClick={handleStartMonitoring}
          className="monitor-button start-monitoring-btn"
          disabled={loading}
        >
          {loading ? 'Monitoring...' : 'Start Monitoring'}
        </button>
        <button 
          onClick={handleStopMonitoring} 
          className="monitor-button stop-monitoring-btn"
          style={{ marginLeft: '10px' }}
          disabled={!isMonitoring}
        >
          Stop Monitoring
        </button>
      </div>
      {error && <p style={{ color: 'red' }}>{error}</p>}
      {data && data.length > 0 && <MonitorTable data={data} />}
    </div>
  );
};

export default Monitor;
