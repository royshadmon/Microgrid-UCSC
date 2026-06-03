import React, { useEffect, useState } from 'react';
import { fetchPolicyTypes } from '../../services/security_api';
import '../../styles/security/PolicySelector.css';

function PolicySelector({ value, onChange, allowedPolicyTypes }) {
  const [types, setTypes] = useState([]);

  useEffect(() => {
    console.log('Fetching policy types...');
    fetchPolicyTypes().then(result => {
      console.log('Fetched policy types:', result);
      setTypes(result);
    });
  }, []);

  useEffect(() => {
    console.log("PolicySelector types:", types);
    console.log("PolicySelector allowedPolicyTypes:", allowedPolicyTypes);
  }, [types, allowedPolicyTypes]);

  // Safety check: if allowedPolicyTypes is not provided or is undefined, default to allowing all
  const effectiveAllowedTypes = allowedPolicyTypes || ['*'];

  return (
    <div className="policy-selector">
      <label>Select Policy Type:</label>
      <select value={value} onChange={e => onChange(e.target.value)}>
        <option value="">-- Choose Policy Type --</option>
        {types
          .filter(t => {
            // if wildcard, allow all
            if (effectiveAllowedTypes.includes('*')) return true;

            // else strip "_policy" and check
            const baseType = t.type.endsWith('_policy')
              ? t.type.slice(0, -7)
              : t.type;
            return effectiveAllowedTypes.includes(baseType);
          })
          .map(({ type, name }) => (
            <option key={type} value={type}>
              {name}
            </option>
          ))}
      </select>
    </div>
  );
}

export default PolicySelector;
