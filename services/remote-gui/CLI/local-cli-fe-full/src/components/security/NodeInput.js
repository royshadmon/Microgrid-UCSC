import React from 'react';
import '../../styles/security/NodeInput.css';

function NodeInput({ value, onChange }) {
  return (
    <div className="node-input">
      <label>Node Address (IP:Port):</label>
      <input
        type="text"
        value={value}
        onChange={e => onChange(e.target.value)}
        placeholder="e.g. 127.0.0.1:7848"
      />
    </div>
  );
}

export default NodeInput;
