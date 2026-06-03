import React, { useState, useMemo } from 'react';
import { filterTableData, hasInternalColumns } from '../utils/tableUtils';
import '../styles/MonitorTable.css'; 

const MonitorTable = ({ data }) => {
  // Load thresholds from localStorage on component mount
  const [thresholds, setThresholds] = useState(() => {
    const saved = localStorage.getItem('monitor-thresholds');
    return saved ? JSON.parse(saved) : [];
  });
  
  const [newThreshold, setNewThreshold] = useState({
    column: '',
    operator: 'greater',
    value: ''
  });
  const [editingThreshold, setEditingThreshold] = useState(null);
  
  // State for showing/hiding internal columns
  const [showInternalColumns, setShowInternalColumns] = useState(false);

  // Check if data has internal columns
  const hasInternal = useMemo(() => hasInternalColumns(data), [data]);

  // Filter data based on internal column visibility
  const { data: filteredData, headers } = useMemo(() => {
    return filterTableData(data, showInternalColumns);
  }, [data, showInternalColumns]);

  // If no data or empty array, render a message
  if (!data || data.length === 0) {
    return <div>No data available.</div>;
  }

  // Save thresholds to localStorage whenever they change
  const saveThresholds = (newThresholds) => {
    setThresholds(newThresholds);
    localStorage.setItem('monitor-thresholds', JSON.stringify(newThresholds));
  };

  // Function to check if a cell value exceeds threshold
  const checkThreshold = (value, threshold) => {
    const numValue = parseFloat(value);
    const numThreshold = parseFloat(threshold.value);
    
    if (isNaN(numValue) || isNaN(numThreshold)) return false;
    
    switch (threshold.operator) {
      case 'greater':
        return numValue > numThreshold;
      case 'less':
        return numValue < numThreshold;
      case 'greaterEqual':
        return numValue >= numThreshold;
      case 'lessEqual':
        return numValue <= numThreshold;
      case 'equal':
        return numValue === numThreshold;
      default:
        return false;
    }
  };

  // Function to add a new threshold or update existing one
  const addThreshold = () => {
    if (newThreshold.column && newThreshold.value) {
      console.log("addThreshold called - editingThreshold:", editingThreshold);
      console.log("newThreshold:", newThreshold);
      
      if (editingThreshold) {
        // We're editing an existing threshold
        console.log("Updating existing threshold with ID:", editingThreshold);
        const updatedThresholds = thresholds.map(t => 
          t.id === editingThreshold 
            ? { ...newThreshold, id: editingThreshold }
            : t
        );
        saveThresholds(updatedThresholds);
        setEditingThreshold(null); // Exit edit mode
        console.log("Threshold updated, exiting edit mode");
      } else {
        // Check if threshold for this column already exists (only when adding new)
        const existingThreshold = thresholds.find(t => t.column === newThreshold.column);
        console.log("Adding new threshold - existingThreshold:", existingThreshold);
        
        if (existingThreshold) {
          // Update existing threshold by column
          console.log("Updating existing threshold by column:", newThreshold.column);
          const updatedThresholds = thresholds.map(t => 
            t.column === newThreshold.column 
              ? { ...newThreshold, id: existingThreshold.id }
              : t
          );
          saveThresholds(updatedThresholds);
        } else {
          // Add new threshold
          console.log("Adding completely new threshold");
          saveThresholds([...thresholds, { ...newThreshold, id: Date.now() }]);
        }
      }
      setNewThreshold({ column: '', operator: 'greater', value: '' });
    }
  };

  // Function to remove a threshold
  const removeThreshold = (id) => {
    const updatedThresholds = thresholds.filter(t => t.id !== id);
    saveThresholds(updatedThresholds);
  };

  // Function to edit a threshold
  const editThreshold = (threshold) => {
    console.log("Editing threshold:", threshold);
    setNewThreshold({
      column: threshold.column,
      operator: threshold.operator,
      value: threshold.value
    });
    setEditingThreshold(threshold.id);
    console.log("Set editing threshold ID:", threshold.id);
  };

  // Function to cancel editing
  const cancelEdit = () => {
    setNewThreshold({ column: '', operator: 'greater', value: '' });
    setEditingThreshold(null);
    console.log("Edit cancelled");
  };

  // Function to get cell styling based on thresholds
  const getCellStyle = (value, header) => {
    const exceededThresholds = thresholds.filter(t => 
      t.column === header && checkThreshold(value, t)
    );
    
    if (exceededThresholds.length > 0) {
      return { backgroundColor: '#ffebee', color: '#c62828', fontWeight: 'bold' };
    }
    return {};
  };

  return (
    <div className="monitor-table-container">
      {/* Threshold Form */}
      <div className="threshold-form">
        <h3>{editingThreshold ? 'Edit Threshold Monitor' : 'Add Threshold Monitor'}</h3>
        <div className="form-row">
          <select
            value={newThreshold.column}
            onChange={(e) => setNewThreshold({...newThreshold, column: e.target.value})}
            placeholder="Select Column"
          >
            <option value="">Select Column</option>
            {headers.map((header, idx) => (
              <option key={`option-${idx}`} value={header}>{header}</option>
            ))}
          </select>
          
          <select
            value={newThreshold.operator}
            onChange={(e) => setNewThreshold({...newThreshold, operator: e.target.value})}
          >
            <option value="greater">&gt;</option>
            <option value="less">&lt;</option>
            <option value="greaterEqual">&gt;=</option>
            <option value="lessEqual">&lt;=</option>
            <option value="equal">=</option>
          </select>
          
          <input
            type="number"
            value={newThreshold.value}
            onChange={(e) => setNewThreshold({...newThreshold, value: e.target.value})}
            placeholder="Threshold Value"
          />
          
          <button onClick={addThreshold} className="add-threshold-btn">
            {editingThreshold ? 'Update Threshold' : 'Add Threshold'}
          </button>
          
          {editingThreshold && (
            <button onClick={cancelEdit} className="cancel-edit-btn">
              Cancel Edit
            </button>
          )}
        </div>
        {editingThreshold && (
          <div style={{ 
            marginTop: '10px', 
            padding: '10px', 
            backgroundColor: '#fff3cd', 
            border: '1px solid #ffeaa7',
            borderRadius: '4px',
            fontSize: '14px'
          }}>
            <strong>Editing:</strong> You're currently editing a threshold. Changes will update the existing threshold instead of creating a new one.
          </div>
        )}
      </div>

      {/* Active Thresholds */}
      {thresholds.length > 0 && (
        <div className="active-thresholds">
          <h4>Active Thresholds:</h4>
          <div className="threshold-list">
            {thresholds.map((threshold) => (
              <div key={threshold.id} className="threshold-item">
                <span>{threshold.column} {threshold.operator} {threshold.value}</span>
                <div className="threshold-actions">
                  <button 
                    onClick={() => editThreshold(threshold)}
                    className="edit-threshold-btn"
                    title="Edit threshold"
                  >
                    ✏️
                  </button>
                  <button 
                    onClick={() => removeThreshold(threshold.id)}
                    className="remove-threshold-btn"
                    title="Remove threshold"
                  >
                    ×
                  </button>
                </div>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Toggle button for internal columns (only show if internal columns exist) */}
      {hasInternal && (
        <div className="internal-columns-toggle" style={{ marginBottom: '10px' }}>
          <button
            className="toggle-internal-columns"
            onClick={() => setShowInternalColumns(!showInternalColumns)}
            style={{
              padding: '8px 16px',
              backgroundColor: showInternalColumns ? '#007bff' : '#6c757d',
              color: 'white',
              border: 'none',
              borderRadius: '4px',
              cursor: 'pointer',
              fontSize: '14px'
            }}
          >
            {showInternalColumns ? 'Hide Internal Rows' : 'Show Internal Rows'}
          </button>
        </div>
      )}

      {/* Data Table */}
      <table className="data-table">
        <thead>
          <tr>
            {headers.map((header, idx) => (
              <th key={`header-${idx}`}>{header}</th>
            ))}
          </tr>
        </thead>
        <tbody>
          {filteredData.map((row, rowIndex) => (
            <tr key={`row-${rowIndex}`}>
              {headers.map((header, cellIndex) => (
                <td 
                  key={`cell-${rowIndex}-${cellIndex}`}
                  style={getCellStyle(row[header], header)}
                >
                  {row[header]}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
};

export default MonitorTable;
