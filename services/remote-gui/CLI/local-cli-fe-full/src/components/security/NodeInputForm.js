import React, { useState } from 'react';
import { pingBackend } from '../../services/security_api'; // Adjust the import path as necessary
import '../../styles/security/NodeInputForm.css'; // Adjust the path as necessary

function NodeInputForm() {
  const [nodeAddress, setNodeAddress] = useState('');
  const [selectedOption, setSelectedOption] = useState('');
  const [pingResult, setPingResult] = useState(null);

  const handleInputChange = (event) => {
    setNodeAddress(event.target.value);
  };

  const handleDropdownChange = (event) => {
    setSelectedOption(event.target.value);
  };

  const handlePingClick = async () => {
    const result = await pingBackend();
    setPingResult(result ? result.message : 'Error');
  };

  return (
    <div className="node-input-form">
      <h2>Connect to AnyLog Node</h2>

      <div className="field">
        <label>Node Address (IP:Port):</label>
        <input
          type="text"
          value={nodeAddress}
          onChange={handleInputChange}
          placeholder="e.g. 127.0.0.1:7848"
        />
      </div>

      <div className="field">
        <label>Select Policy Type:</label>
        <select
          value={selectedOption}
          onChange={handleDropdownChange}
        >
          <option value="">-- Choose Policy Type --</option>
          <option value="config">Configuration Policy</option>
          <option value="security">Security Policy</option>
        </select>
      </div>

      <button onClick={handlePingClick} className="button">
        Ping Backend
      </button>

      {pingResult && (
        <div className="preview">
          <p><strong>Backend Response:</strong> {pingResult}</p>
        </div>
      )}
    </div>
  );
}

export default NodeInputForm;
