import React, { useState, useMemo } from 'react';
import '../../styles/security/PermissionsTable.css'; // Reuse the same styles

function SecurityGroupsTable({ groups, selectedGroups, onChange }) {
  const [filter, setFilter] = useState('');

  // Filter on name OR description
  const filteredGroups = useMemo(
    () =>
      groups.filter(({ security_group: group }) => {
        const name = group.group_name.toLowerCase();
        const desc = (group.description || '').toLowerCase();
        const term = filter.trim().toLowerCase();
        return name.includes(term) || desc.includes(term);
      }),
    [groups, filter]
  );

  // Are all visible rows selected?
  const allSelected =
    filteredGroups.length > 0 &&
    filteredGroups.every(({ security_group: group }) =>
      selectedGroups.includes(group.group_name)
    );

  const handleCheckbox = (name) => {
    let next;
    if (selectedGroups.includes(name)) {
      next = selectedGroups.filter(g => g !== name);
    } else {
      next = [...selectedGroups, name];
    }
    onChange(next);
  };

  const handleSelectAll = () => {
    if (allSelected) {
      // remove only the visible ones
      onChange(
        selectedGroups.filter(
          name => !filteredGroups.some(({ security_group: group }) => group.group_name === name)
        )
      );
    } else {
      // add visible ones (dedupe)
      const toAdd = filteredGroups.map(({ security_group: group }) => group.group_name);
      onChange(Array.from(new Set([...selectedGroups, ...toAdd])));
    }
  };

  return (
    <div className="permissions-table-wrapper">
      {/* Search input */}
      <div style={{ marginBottom: '8px' }}>
        <input
          type="text"
          placeholder="Search security groups…"
          value={filter}
          onChange={e => setFilter(e.target.value)}
          style={{
            width: '100%',
            padding: '6px 8px',
            boxSizing: 'border-box',
            fontSize: '14px'
          }}
        />
      </div>

      <div className="permissions-table-container">
        <table className="permissions-table">
        <thead>
          <tr>
            <th>Name</th>
            <th>Description</th>
            {/* <th>Permissions</th> */}
            <th>
              <label style={{ display: 'flex', alignItems: 'center', gap: '4px' }}>
                Member of
                <input
                  type="checkbox"
                  checked={allSelected}
                  onChange={handleSelectAll}
                  className="permission-checkbox"
                />
              </label>
            </th>
          </tr>
        </thead>
        <tbody>
          {filteredGroups.length > 0 ? (
            filteredGroups.map(({ security_group: group }) => (
              <tr key={group.id}>
                <td>{group.group_name}</td>
                <td>{group.description || '-'}</td>
                {/* <td>
                  <div style={{ maxWidth: '200px', overflow: 'hidden' }}>
                    {group.permissions && group.permissions.length > 0 ? (
                      <div style={{ fontSize: '12px', color: '#666' }}>
                        {group.permissions.slice(0, 3).join(', ')}
                        {group.permissions.length > 3 && ` +${group.permissions.length - 3} more`}
                      </div>
                    ) : (
                      <span style={{ fontSize: '12px', color: '#999' }}>No permissions</span>
                    )}
                  </div>
                </td> */}
                <td>
                  <input
                    type="checkbox"
                    checked={selectedGroups.includes(group.group_name)}
                    onChange={() => handleCheckbox(group.group_name)}
                    className="permission-checkbox"
                  />
                </td>
              </tr>
            ))
          ) : (
            <tr>
              <td colSpan={4} style={{ textAlign: 'center', color: '#666' }}>
                No groups match "{filter}"
              </td>
            </tr>
          )}
        </tbody>
        </table>
      </div>
    </div>
  );
}

export default SecurityGroupsTable;
