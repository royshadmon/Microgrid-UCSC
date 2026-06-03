import React, { useState, useEffect } from 'react';
import { sendCommand } from '../services/api';
import '../styles/BlockchainManager.css';

const BlockchainManager = ({ node }) => {
  const [selectedGetOption, setSelectedGetOption] = useState('');
  const [nameInput, setNameInput] = useState('');
  const [query, setQuery] = useState('');
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);
  const [results, setResults] = useState([]);
  const [filteredResults, setFilteredResults] = useState([]);
  const [searchFilter, setSearchFilter] = useState('');

  const getOptions = [
    { value: '*', label: 'All' },
    { value: 'operator', label: 'Operator' },
    { value: 'query', label: 'Query' },
    { value: 'master', label: 'Master' },
    { value: 'cluster', label: 'Cluster' },
    { value: 'table', label: 'Table' }
  ];

  // Update query when inputs change
  useEffect(() => {
    if (selectedGetOption) {
      if (nameInput.trim()) {
        const newQuery = `blockchain get ${selectedGetOption} where name=${nameInput}`;
        setQuery(newQuery);
      } else {
        const newQuery = `blockchain get ${selectedGetOption}`;
        setQuery(newQuery);
      }
    } else {
      setQuery('');
    }
  }, [selectedGetOption, nameInput]);

  // Filter results based on search input
  useEffect(() => {
    if (searchFilter) {
      const filtered = results.filter(item => 
        JSON.stringify(item).toLowerCase().includes(searchFilter.toLowerCase())
      );
      setFilteredResults(filtered);
    } else {
      setFilteredResults(results);
    }
  }, [results, searchFilter]);

  const handleExecuteQuery = async () => {
    if (!node) {
      setError('No node selected. Please select a node first.');
      return;
    }

    if (!selectedGetOption) {
      setError('Please select a get option.');
      return;
    }

    setLoading(true);
    setError(null);

    try {
      const response = await sendCommand({
        connectInfo: node,
        method: 'GET',
        command: query
      });

      if (response && response.data) {
        // Handle different response formats
        let parsedResults = [];
        if (Array.isArray(response.data)) {
          parsedResults = response.data;
        } else if (typeof response.data === 'object') {
          parsedResults = [response.data];
        } else if (typeof response.data === 'string') {
          try {
            parsedResults = JSON.parse(response.data);
            if (!Array.isArray(parsedResults)) {
              parsedResults = [parsedResults];
            }
          } catch (e) {
            parsedResults = [{ raw: response.data }];
          }
        }

        // Handle different response structures more flexibly
        const extractedResults = [];
        parsedResults.forEach(item => {
          // If the item is already a flat object with the data we need, use it directly
          if (typeof item === 'object' && item !== null) {
            // Check if this looks like a direct policy object (has common blockchain fields)
            const hasBlockchainFields = ['id', 'name', 'type', 'status', 'created', 'updated'].some(field => 
              item.hasOwnProperty(field)
            );
            
            if (hasBlockchainFields) {
              // This is likely a direct policy object, use it as-is
              extractedResults.push(item);
            } else {
              // This might be a wrapper object, try to extract nested data
              const nestedKeys = Object.keys(item).filter(key => 
                typeof item[key] === 'object' && item[key] !== null
              );
              
              if (nestedKeys.length === 1) {
                // Single nested object, extract it
                extractedResults.push(item[nestedKeys[0]]);
              } else if (nestedKeys.length > 1) {
                // Multiple nested objects, flatten them or use the first one
                // For now, let's flatten all nested objects into one
                const flattened = { ...item };
                nestedKeys.forEach(key => {
                  if (typeof item[key] === 'object' && item[key] !== null) {
                    Object.assign(flattened, item[key]);
                  }
                });
                extractedResults.push(flattened);
              } else {
                // No nested objects, use the item as-is
                extractedResults.push(item);
              }
            }
          } else {
            // Non-object item, wrap it
            extractedResults.push({ value: item });
          }
        });

        setResults(extractedResults);
        setFilteredResults(extractedResults);
      } else {
        setResults([]);
        setFilteredResults([]);
      }
    } catch (err) {
      setError(`Error executing query: ${err.message}`);
      setResults([]);
      setFilteredResults([]);
    } finally {
      setLoading(false);
    }
  };

  const handleDeleteItem = async (item, index) => {
    if (!node) {
      setError('No node selected. Please select a node first.');
      return;
    }

    if (!window.confirm('Are you sure you want to delete this item?')) {
      return;
    }

    setLoading(true);
    setError(null);

    try {
      // Construct delete command using the correct format
      const itemId = item.id || item.key || item.name || `item_${index}`;
      const deleteCommand = `blockchain delete policy where id=${itemId} and master=!ledger_conn`;

      const response = await sendCommand({
        connectInfo: node,
        method: 'POST',
        command: deleteCommand
      });

      if (response && response.success !== false) {
        // Remove the item from results
        const updatedResults = results.filter((_, i) => i !== index);
        setResults(updatedResults);
        setFilteredResults(updatedResults.filter(item => 
          !searchFilter || JSON.stringify(item).toLowerCase().includes(searchFilter.toLowerCase())
        ));
      } else {
        setError('Failed to delete item. Please try again.');
      }
    } catch (err) {
      setError(`Error deleting item: ${err.message}`);
    } finally {
      setLoading(false);
    }
  };

  const clearResults = () => {
    setResults([]);
    setFilteredResults([]);
    setSearchFilter('');
  };

  const formatValue = (value) => {
    if (value === null || value === undefined) {
      return 'N/A';
    }
    if (typeof value === 'boolean') {
      return value ? 'Yes' : 'No';
    }
    if (typeof value === 'string' && value.match(/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}/)) {
      try {
        return new Date(value).toLocaleString();
      } catch (e) {
        return value;
      }
    }
    if (typeof value === 'object') {
      return JSON.stringify(value, null, 2);
    }
    return String(value);
  };

  const getItemTitle = (item) => {
    // Try to find a good title from common fields
    const titleFields = ['name', 'id', 'title', 'key', 'label', 'description'];
    for (const field of titleFields) {
      if (item[field] && typeof item[field] === 'string') {
        return item[field];
      }
    }
    return `${selectedGetOption} ${results.indexOf(item) + 1}`;
  };

  const getItemSubtitle = (item) => {
    // Try to find a subtitle from other common fields
    const subtitleFields = ['company', 'type', 'status', 'category', 'hostname'];
    for (const field of subtitleFields) {
      if (item[field] && typeof item[field] === 'string') {
        return item[field];
      }
    }
    return null;
  };

  const renderJsonCard = (item, index) => {
    const title = getItemTitle(item);
    const subtitle = getItemSubtitle(item);
    
    // Group fields by category for better organization
    const fieldGroups = {
      'Basic Information': [],
      'Network & Connection': [],
      'Configuration': [],
      'Location & Geography': [],
      'Metadata': [],
      'Other': []
    };

    // Categorize fields with more flexible matching
    Object.entries(item).forEach(([key, value]) => {
      const lowerKey = key.toLowerCase();
      
      // Basic Information - common identifiers and descriptions
      if (['name', 'id', 'title', 'label', 'description', 'company', 'type', 'status', 'category', 'policy', 'rule'].includes(lowerKey) ||
          lowerKey.includes('name') || lowerKey.includes('title') || lowerKey.includes('description')) {
        fieldGroups['Basic Information'].push([key, value]);
      } 
      // Network & Connection - network-related fields
      else if (['ip', 'hostname', 'port', 'rest_port', 'broker_port', 'url', 'endpoint', 'address', 'host', 'server'].includes(lowerKey) ||
               lowerKey.includes('port') || lowerKey.includes('host') || lowerKey.includes('ip') || lowerKey.includes('url')) {
        fieldGroups['Network & Connection'].push([key, value]);
      } 
      // Configuration - settings and config fields
      else if (['config', 'settings', 'options', 'parameters', 'properties', 'value', 'data', 'content'].includes(lowerKey) ||
               lowerKey.includes('config') || lowerKey.includes('setting') || lowerKey.includes('param')) {
        fieldGroups['Configuration'].push([key, value]);
      } 
      // Metadata - timestamps, IDs, and blockchain-specific fields
      else if (['date', 'created', 'updated', 'timestamp', 'cluster', 'ledger', 'member', 'hash', 'block', 'transaction'].includes(lowerKey) ||
               lowerKey.includes('id') || lowerKey.includes('time') || lowerKey.includes('date') || lowerKey.includes('hash')) {
        fieldGroups['Metadata'].push([key, value]);
      } 
      // Location & Geography - location-related fields
      else if (['location', 'country', 'state', 'city', 'region', 'zone', 'area', 'coordinates', 'lat', 'lng', 'loc'].includes(lowerKey) ||
               lowerKey.includes('location') || lowerKey.includes('country') || lowerKey.includes('city')) {
        fieldGroups['Location & Geography'].push([key, value]);
      }
      // Other - everything else
      else {
        fieldGroups['Other'].push([key, value]);
      }
    });

    // Remove empty groups
    Object.keys(fieldGroups).forEach(group => {
      if (fieldGroups[group].length === 0) {
        delete fieldGroups[group];
      }
    });

    return (
      <div key={index} className="json-card">
        <div className="json-header">
          <div className="json-title">
            <h3>{title}</h3>
            {subtitle && <p className="json-subtitle">{subtitle}</p>}
          </div>
          <button
            onClick={() => handleDeleteItem(item, index)}
            className="btn btn-danger btn-small"
            disabled={loading}
            title="Delete this item"
          >
            Delete
          </button>
        </div>
        
        <div className="json-details">
          {Object.entries(fieldGroups).map(([groupName, fields]) => (
            <div key={groupName} className="detail-section">
              <h4>{groupName}</h4>
              <div className="detail-grid">
                {fields.map(([key, value]) => (
                  <div key={key} className="detail-item">
                    <span className="detail-label">{key.replace(/_/g, ' ').replace(/\b\w/g, l => l.toUpperCase())}:</span>
                    <span className={`detail-value ${typeof value === 'object' ? 'json-object' : ''} ${key.toLowerCase().includes('id') ? 'id-field' : ''}`}>
                      {formatValue(value)}
                    </span>
                  </div>
                ))}
              </div>
            </div>
          ))}
        </div>
      </div>
    );
  };

  return (
    <div className="blockchain-manager">
      <div className="blockchain-header">
        <h2>Blockchain Manager</h2>
        <p>Query and manage blockchain policies. Select a get option and optionally specify a name to filter results.</p>
      </div>

      <div className="blockchain-controls">
        <div className="query-builder">
          <div className="form-group">
            <label htmlFor="get-option">Get Option:</label>
            <select
              id="get-option"
              value={selectedGetOption}
              onChange={(e) => setSelectedGetOption(e.target.value)}
              className="form-select"
            >
              <option value="">Select an option</option>
              {getOptions.map(option => (
                <option key={option.value} value={option.value}>
                  {option.label}
                </option>
              ))}
            </select>
          </div>

          <div className="form-group">
            <label htmlFor="name-input">Name (optional):</label>
            <input
              id="name-input"
              type="text"
              value={nameInput}
              onChange={(e) => setNameInput(e.target.value)}
              placeholder="Enter name (e.g., demo1-operator2) - leave empty for all"
              className="form-input"
            />
          </div>

          <div className="query-preview">
            <label>Query Preview:</label>
            <div className="query-display">
              {query || 'blockchain get [option] [where name=[name]]'}
            </div>
          </div>

          <div className="button-group">
            <button
              onClick={handleExecuteQuery}
              disabled={!selectedGetOption || loading}
              className="btn btn-primary"
            >
              {loading ? 'Executing...' : 'Execute Query'}
            </button>
            <button
              onClick={clearResults}
              disabled={results.length === 0}
              className="btn btn-secondary"
            >
              Clear Results
            </button>
          </div>
        </div>
      </div>

      {error && (
        <div className="error-message">
          <strong>Error:</strong> {error}
        </div>
      )}

      {results.length > 0 && (
        <div className="results-section">
          <div className="results-header">
            <h2>Results ({filteredResults.length} of {results.length})</h2>
            <div className="search-filter">
              <input
                type="text"
                value={searchFilter}
                onChange={(e) => setSearchFilter(e.target.value)}
                placeholder="Filter results..."
                className="form-input"
              />
            </div>
          </div>

          <div className="results-container">
            {filteredResults.length === 0 ? (
              <div className="no-results">
                No results match your filter criteria.
              </div>
            ) : (
              <div className="results-grid">
                {filteredResults.map((item, index) => renderJsonCard(item, index))}
              </div>
            )}
          </div>
        </div>
      )}

      {!node && (
        <div className="no-node-warning">
          <p>⚠️ No node selected. Please select a node from the top bar to use the Blockchain Manager.</p>
        </div>
      )}
    </div>
  );
};

export default BlockchainManager;
