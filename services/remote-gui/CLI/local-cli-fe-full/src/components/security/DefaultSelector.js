import React, { useState } from 'react';
import '../../styles/security/DefaultSelector.css';

function DefaultSelector({ defaults, onSelectDefault, currentFormData }) {
  const [selectedDefault, setSelectedDefault] = useState('');

  if (!defaults || Object.keys(defaults).length === 0) {
    return null;
  }

  const handleDefaultSelect = (defaultKey) => {
    if (!defaultKey) return;
    
    const defaultConfig = defaults[defaultKey];
    if (defaultConfig && defaultConfig.values) {
      // Replace all form data with only the default values (clear previous values)
      onSelectDefault(defaultConfig.values);
      setSelectedDefault(defaultKey);
    }
  };

  const handleClearDefaults = () => {
    onSelectDefault({});
    setSelectedDefault('');
  };

  return (
    <div className="default-selector">
      <div className="default-selector-header">
        <h4>Quick Setup</h4>
        <p>Select a predefined configuration to auto-fill the form:</p>
      </div>
      
      <div className="default-options">
        {Object.entries(defaults).map(([key, config]) => (
          <div 
            key={key} 
            className={`default-option ${selectedDefault === key ? 'selected' : ''}`}
            onClick={() => handleDefaultSelect(key)}
          >
            <div className="default-option-header">
              <h5>{config.name}</h5>
              <span className="default-option-badge">Default</span>
            </div>
            <p className="default-option-description">{config.description}</p>
            <div className="default-option-preview">
              <strong>Will set:</strong>
              <ul>
                {Object.entries(config.values || {}).map(([field, value]) => (
                  <li key={field}>
                    <code>{field}</code>: {typeof value === 'object' ? JSON.stringify(value).substring(0, 50) + '...' : String(value)}
                  </li>
                ))}
              </ul>
            </div>
          </div>
        ))}
      </div>

      {selectedDefault && (
        <div className="default-actions">
          <button 
            className="clear-defaults-btn"
            onClick={handleClearDefaults}
          >
            Clear Default Values
          </button>
          <span className="default-applied">
            ✓ Applied: {defaults[selectedDefault].name}
          </span>
        </div>
      )}
    </div>
  );
}

export default DefaultSelector; 