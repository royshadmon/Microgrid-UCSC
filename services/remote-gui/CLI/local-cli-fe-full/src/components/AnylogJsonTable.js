import React, { useState, useMemo } from 'react';
import { filterTableData, hasInternalColumns } from '../utils/tableUtils';
import '../styles/AnylogJsonTable.css';

const AnylogJsonTable = ({ data, className = '' }) => {
  // State for showing/hiding internal columns
  const [showInternalColumns, setShowInternalColumns] = useState(false);

  // Convert the nested object into rows and columns
  const rows = useMemo(() => {
    if (!data || typeof data !== 'object') {
      return [];
    }
    return Object.entries(data).map(([serviceName, serviceData]) => ({
      service: serviceName,
      ...serviceData
    }));
  }, [data]);

  // Check if data has internal columns
  const hasInternal = useMemo(() => hasInternalColumns(rows), [rows]);

  // Filter data based on internal column visibility
  const { data: filteredRows, headers: columns } = useMemo(() => {
    const result = filterTableData(rows, showInternalColumns);
    return {
      data: result.data,
      headers: result.headers.filter(col => col !== 'service') // Remove 'service' from headers as it's handled separately
    };
  }, [rows, showInternalColumns]);

  // If no data, return empty state
  if (!data || typeof data !== 'object') {
    return <div className="anylog-table-empty">No data available</div>;
  }

  // Helper function to render cell content
  const renderCellContent = (value, columnName) => {
    if (value === null || value === undefined) {
      return <span className="anylog-table-null">-</span>;
    }

    // Special styling for Status column
    if (columnName.toLowerCase() === 'status') {
      const statusValue = String(value).toLowerCase();
      let statusClass = 'status-not-declared';
      
      if (statusValue.includes('running')) {
        statusClass = 'status-running';
      } else if (statusValue.includes('stopped') || statusValue.includes('error') || statusValue.includes('failed')) {
        statusClass = 'status-error';
      } else if (statusValue.includes('not declared') || statusValue.includes('not active') || statusValue.includes('disabled')) {
        statusClass = 'status-not-declared';
      } else if (statusValue.includes('warning') || statusValue.includes('pending')) {
        statusClass = 'status-stopped';
      }
      
      return <span className={`status-badge ${statusClass}`}>{value}</span>;
    }

    // Handle arrays
    if (Array.isArray(value)) {
      return <span className="anylog-table-array">{JSON.stringify(value)}</span>;
    }

    // Handle objects
    if (typeof value === 'object') {
      return <span className="anylog-table-object">{JSON.stringify(value)}</span>;
    }

    // Handle strings and numbers
    return <span className="anylog-table-value">{String(value)}</span>;
  };

  return (
    <div className={`anylog-table-wrapper ${className}`}>
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

      <table className="anylog-table">
        <thead>
          <tr>
            <th className="anylog-table-header service-header">Service</th>
            {columns.map(column => (
              <th key={column} className="anylog-table-header">
                {column}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {filteredRows.map((row, index) => (
            <tr key={index} className="anylog-table-row">
              <td className="anylog-table-cell service-cell">
                <span className="service-name">{row.service}</span>
              </td>
              {columns.map(column => (
                <td key={column} className="anylog-table-cell">
                  {renderCellContent(row[column], column)}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
};

export default AnylogJsonTable;
