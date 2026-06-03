// import React, { useState, useMemo } from 'react';
// import '../styles/PermissionsTable.css';

// function PermissionsTable({ permissions, selectedPermissions, onChange }) {
//   const [filter, setFilter] = useState('');

//   // Only show permissions that include the filter text (case-insensitive)
//   const filteredPermissions = useMemo(
//     () =>
//       permissions.filter(perm =>
//         perm.toLowerCase().includes(filter.trim().toLowerCase())
//       ),
//     [permissions, filter]
//   );

//   // Are all *visible* rows selected?
//   const allSelected =
//     filteredPermissions.length > 0 &&
//     filteredPermissions.every(perm => selectedPermissions.includes(perm));

//   const handleCheckbox = (perm) => {
//     let updated;
//     if (selectedPermissions.includes(perm)) {
//       updated = selectedPermissions.filter(p => p !== perm);
//     } else {
//       updated = [...selectedPermissions, perm];
//     }
//     onChange(updated);
//   };

//   // Toggle only the visible ones
//   const handleSelectAll = () => {
//     if (allSelected) {
//       // remove filtered ones
//       onChange(selectedPermissions.filter(p => !filteredPermissions.includes(p)));
//     } else {
//       // add filtered ones (dedupe)
//       onChange(Array.from(new Set([...selectedPermissions, ...filteredPermissions])));
//     }
//   };

//   return (
//     <div className="permissions-table-wrapper">
//       {/* Search box */}
//       <div style={{ marginBottom: '8px' }}>
//         <input
//           type="text"
//           placeholder="Search permissions…"
//           value={filter}
//           onChange={e => setFilter(e.target.value)}
//           style={{
//             width: '100%',
//             padding: '6px 8px',
//             boxSizing: 'border-box',
//             fontSize: '14px'
//           }}
//         />
//       </div>

//       <table className="permissions-table">
//         <thead>
//           <tr>
//             <th>Permission</th>
//             <th>
//               <label style={{ display: 'flex', alignItems: 'center', gap: '4px' }}>
//                 Allowed
//                 <input
//                   type="checkbox"
//                   checked={allSelected}
//                   onChange={handleSelectAll}
//                   className="permission-checkbox"
//                 />
//               </label>
//             </th>
//           </tr>
//         </thead>
//         <tbody>
//           {filteredPermissions.length > 0 ? (
//             filteredPermissions.map(perm => (
//               <tr key={perm}>
//                 <td>{perm}</td>
//                 <td>
//                   <input
//                     type="checkbox"
//                     checked={selectedPermissions.includes(perm)}
//                     onChange={() => handleCheckbox(perm)}
//                     className="permission-checkbox"
//                   />
//                 </td>
//               </tr>
//             ))
//           ) : (
//             <tr>
//               <td colSpan={2} style={{ textAlign: 'center', color: '#666' }}>
//                 No permissions match “{filter}”
//               </td>
//             </tr>
//           )}
//         </tbody>
//       </table>
//     </div>
//   );
// }

// export default PermissionsTable;


import React, { useState, useMemo } from 'react';
import '../../styles/security/PermissionsTable.css';

function PermissionsTable({ permissions, selectedPermissions, onChange }) {
  const [filter, setFilter] = useState('');

  // Filter on name OR description
  const filtered = useMemo(
    () =>
      permissions.filter(({ permissions: perm }) => {
        const name = perm.name.toLowerCase();
        const desc = (perm.description || '').toLowerCase();
        const term = filter.trim().toLowerCase();
        return name.includes(term) || desc.includes(term);
      }),
    [permissions, filter]
  );

  // Are all visible rows selected?
  const allSelected =
    filtered.length > 0 &&
    filtered.every(({ permissions: perm }) =>
      selectedPermissions.includes(perm.name)
    );

  const handleCheckbox = (name) => {
    let next;
    if (selectedPermissions.includes(name)) {
      next = selectedPermissions.filter(p => p !== name);
    } else {
      next = [...selectedPermissions, name];
    }
    onChange(next);
  };

  const handleSelectAll = () => {
    if (allSelected) {
      // remove only the visible ones
      onChange(
        selectedPermissions.filter(
          name => !filtered.some(({ permissions: perm }) => perm.name === name)
        )
      );
    } else {
      // add visible ones (dedupe)
      const toAdd = filtered.map(({ permissions: perm }) => perm.name);
      onChange(Array.from(new Set([...selectedPermissions, ...toAdd])));
    }
  };

  return (
    <div className="permissions-table-wrapper">
      {/* Search */}
      <div style={{ marginBottom: 8 }}>
        <input
          type="text"
          placeholder="Search permissions…"
          value={filter}
          onChange={e => setFilter(e.target.value)}
          style={{
            width: '100%',
            padding: '6px 8px',
            boxSizing: 'border-box',
            fontSize: 14
          }}
        />
      </div>

      <table className="permissions-table">
        <thead>
          <tr>
            <th>Name</th>
            <th>Description</th>
            <th>
              <label style={{ display: 'flex', alignItems: 'center', gap: 4 }}>
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
          {filtered.length > 0 ? (
            filtered.map(({ permissions: perm }) => (
              <tr key={perm.id}>
                <td>{perm.name}</td>
                <td>{perm.description}</td>
                <td>
                  <input
                    type="checkbox"
                    checked={selectedPermissions.includes(perm.name)}
                    onChange={() => handleCheckbox(perm.name)}
                    className="permission-checkbox"
                  />
                </td>
              </tr>
            ))
          ) : (
            <tr>
              <td colSpan={3} style={{ textAlign: 'center', color: '#666' }}>
                No permissions match “{filter}”
              </td>
            </tr>
          )}
        </tbody>
      </table>
    </div>
  );
}

export default PermissionsTable;
