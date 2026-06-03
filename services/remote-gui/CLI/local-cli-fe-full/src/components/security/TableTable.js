// import React from 'react';
// import '../styles/PermissionsTable.css'; // Reuse the same styles

// function TableTable({ groups, selectedGroups, onChange }) {

//   const allSelected = groups.length > 0 && selectedGroups.length === groups.length;

//   const handleCheckbox = (group) => {
//     let updated;
//     if (selectedGroups.includes(group)) {
//       updated = selectedGroups.filter(g => g !== group);
//     } else {
//       updated = [...selectedGroups, group];
//     }
//     onChange(updated);
//   };

//   // Toggle the “Select All” checkbox
//   const handleSelectAll = () => {
//     if (allSelected) {
//       onChange([]);           // Uncheck all
//     } else {
//       onChange([...groups]); // Check all
//     }
//   };

//   return (
//     <div className="permissions-table-wrapper">
//       <table className="permissions-table">
//         <thead>
//           <tr>
//             <th>Table Name</th>
//             <th><label style={{ display: 'flex', alignItems: 'center', gap: '4px' }}>
//               Allowed
//               <input
//                 type="checkbox"
//                 checked={allSelected}
//                 onChange={handleSelectAll}
//                 className="permission-checkbox"
//               />
//             </label></th>
//           </tr>
//         </thead>
//         <tbody>
//           {groups.map((group) => (
//             <tr key={group}>
//               <td>{group}</td>
//               <td>
//                 <input
//                   type="checkbox"
//                   checked={selectedGroups.includes(group)}
//                   onChange={() => handleCheckbox(group)}
//                   className="permission-checkbox"
//                 />
//               </td>
//             </tr>
//           ))}
//         </tbody>
//       </table>
//     </div>
//   );
// }

// export default TableTable; 

import React, { useState, useMemo } from 'react';
import '../../styles/security/PermissionsTable.css';

function TableTable({ groups, selectedGroups, onChange }) {
  const [filter, setFilter] = useState('');

  // derive the list of groups that match the filter (case‐insensitive)
  const filteredGroups = useMemo(() => 
    groups.filter(g =>
      g.toLowerCase().includes(filter.trim().toLowerCase())
    ),
    [groups, filter]
  );

  const allSelected = filteredGroups.length > 0
    && filteredGroups.every(g => selectedGroups.includes(g));

  const handleCheckbox = (group) => {
    let updated;
    if (selectedGroups.includes(group)) {
      updated = selectedGroups.filter(g => g !== group);
    } else {
      updated = [...selectedGroups, group];
    }
    onChange(updated);
  };

  const handleSelectAll = () => {
    if (allSelected) {
      // remove only the filtered ones
      onChange(selectedGroups.filter(g => !filteredGroups.includes(g)));
    } else {
      // add all filtered ones (avoiding duplicates)
      const newSelection = Array.from(new Set([
        ...selectedGroups,
        ...filteredGroups
      ]));
      onChange(newSelection);
    }
  };

  return (
    <div className="permissions-table-wrapper">
      {/* Search box */}
      <div style={{ marginBottom: '8px' }}>
        <input
          type="text"
          placeholder="Search tables…"
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
            <th>Table Name</th>
            <th>
              <label style={{ display: 'flex', alignItems: 'center', gap: '4px' }}>
                Allowed
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
          {filteredGroups.map(group => (
            <tr key={group}>
              <td>{group}</td>
              <td>
                <input
                  type="checkbox"
                  checked={selectedGroups.includes(group)}
                  onChange={() => handleCheckbox(group)}
                  className="permission-checkbox"
                />
              </td>
            </tr>
          ))}
          {filteredGroups.length === 0 && (
            <tr>
              <td colSpan={2} style={{ textAlign: 'center', color: '#666' }}>
                No tables match “{filter}”
              </td>
            </tr>
          )}
        </tbody>
        </table>
      </div>
    </div>
  );
}

export default TableTable;
