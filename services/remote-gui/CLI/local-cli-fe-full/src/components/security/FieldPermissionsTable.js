
import React from 'react';
import '../../styles/security/FieldPermissionsTable.css';

function FieldPermissionsTable({ fieldPermissions, onChange }) {
  const policyTypes = Object.keys(fieldPermissions || {});

  const handleFieldChange = (policyType, fieldName, value) => {
    const updated = { ...fieldPermissions };
    if (!updated[policyType]) updated[policyType] = {};
    updated[policyType][fieldName] = value;
    onChange(updated);
  };

  // Toggle all for one policyType
  const handleSelectAll = (policyType) => {
    const fields = fieldPermissions[policyType] || {};
    const fieldNames = Object.keys(fields);
    const allSelected = fieldNames.every(name => fields[name]);
    const updated = {
      ...fieldPermissions,
      [policyType]: fieldNames.reduce((acc, name) => {
        acc[name] = !allSelected;
        return acc;
      }, {})
    };
    onChange(updated);
  };

  return (
    <div className="field-permissions-tables-wrapper">
      {policyTypes.map(policyType => {
        const fields = fieldPermissions[policyType] || {};
        const fieldNames = Object.keys(fields);
        if (fieldNames.length === 0) return null;

        // check if every field is checked
        const allSelected = fieldNames.length > 0 && fieldNames.every(name => fields[name]);

        return (
          <div key={policyType} className="policy-type-table-container">
            <h5 className="policy-type-title">
              {policyType.charAt(0).toUpperCase() + policyType.slice(1)} Policy Permissions
            </h5>
            <div className="field-permissions-table-wrapper">
              <table className="field-permissions-table">
                <thead>
                  <tr>
                    <th>Field</th>
                    <th>
                      <label style={{ display: 'flex', alignItems: 'center', gap: '4px' }}>
                        Allowed
                        <input
                          type="checkbox"
                          checked={allSelected}
                          onChange={() => handleSelectAll(policyType)}
                          className="field-permission-checkbox"
                        />
                      </label>
                    </th>
                  </tr>
                </thead>
                <tbody>
                  {fieldNames.map(fieldName => {
                    const isAllowed = fields[fieldName] || false;
                    return (
                      <tr key={fieldName}>
                        <td className="field-name">
                          <span className="field-label">{fieldName}</span>
                        </td>
                        <td className="permission-cell">
                          <input
                            type="checkbox"
                            checked={isAllowed}
                            onChange={e => handleFieldChange(policyType, fieldName, e.target.checked)}
                            className="field-permission-checkbox"
                          />
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          </div>
        );
      })}
    </div>
  );
}

export default FieldPermissionsTable;
