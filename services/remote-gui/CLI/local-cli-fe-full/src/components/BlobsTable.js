// import React, { useState, useEffect } from 'react';
// import '../styles/DataTable.css'; 

// /**
//  * BlobsTable
//  *
//  * Props:
//  *   - data: array of objects to display
//  *   - keyField: (optional) name of the unique key in each object (default: 'id')
//  *   - onSelectionChange: (optional) fn(selectedRows) called whenever selection updates
//  */
// const BlobsTable = ({ data = [], keyField = 'id', onSelectionChange }) => {
//   const [selectedIds, setSelectedIds] = useState([]);

//   // Whenever selectedIds changes, compute the selected row objects
//   useEffect(() => {
//     if (typeof onSelectionChange === 'function') {
//       const selectedRows = data.filter(row => selectedIds.includes(row[keyField]));
//       onSelectionChange(selectedRows);
//     }
//   }, [selectedIds, data, keyField, onSelectionChange]);

//   if (data.length === 0) {
//     return <div>No data available.</div>;
//   }

//   const headers = Object.keys(data[0]);

//   // Toggle a row’s presence in selectedIds
//   const toggleRow = (id) => {
//     setSelectedIds(prev => 
//       prev.includes(id) 
//         ? prev.filter(x => x !== id) 
//         : [...prev, id]
//     );
//   };

//   return (
//     <table className="data-table">
//       <thead>
//         <tr>
//           <th>Select</th>
//           {headers.map((h, i) => (
//             <th key={`h-${i}`}>{h}</th>
//           ))}
//         </tr>
//       </thead>
//       <tbody>
//         {data.map((row, rowIndex) => {
//           // Fallback to rowIndex if keyField is missing
//           const id = row[keyField] != null ? row[keyField] : rowIndex;
//           return (
//             <tr key={id}>
//               <td>
//                 <input
//                   type="checkbox"
//                   checked={selectedIds.includes(id)}
//                   onChange={() => toggleRow(id)}
//                 />
//               </td>
//               {headers.map((h, i) => (
//                 <td key={`c-${rowIndex}-${i}`}>
//                   {String(row[h])}
//                 </td>
//               ))}
//             </tr>
//           );
//         })}
//       </tbody>
//     </table>
//   );
// };

// export default BlobsTable;


import React, { useState, useEffect, useMemo, useRef } from 'react';
import { filterTableData, hasInternalColumns } from '../utils/tableUtils';
import '../styles/DataTable.css'; 

const clamp = (val, min, max) => Math.max(min, Math.min(max, val));

/**
 * BlobsTable
 *
 * Props:
 *   - data: array of objects to display
 *   - onSelectionChange: fn(selectedRows) called whenever selection updates
 *   - minColumnWidth: minimum column width (default: 60)
 *   - maxColumnWidth: maximum column width (default: 800)
 *   - defaultColumnWidth: default column width (default: 150)
 */
const BlobsTable = ({ 
  data = [], 
  onSelectionChange,
  minColumnWidth = 60,
  maxColumnWidth = 800,
  defaultColumnWidth = 150
}) => {
  const tableRef = useRef(null);
  const draggingRef = useRef({ active: false, colIndex: -1, startX: 0, startWidth: 0 });

  // 1) Keep track of which row‐indexes are selected
  const [selectedIndexes, setSelectedIndexes] = useState([]);
  
  // State for showing/hiding internal columns
  const [showInternalColumns, setShowInternalColumns] = useState(false);

  // Check if data has internal columns
  const hasInternal = useMemo(() => hasInternalColumns(data), [data]);

  // Filter data based on internal column visibility
  const { data: filteredData, headers } = useMemo(() => {
    return filterTableData(data, showInternalColumns);
  }, [data, showInternalColumns]);

  // ✅ Hooks are unconditional
  const [colWidths, setColWidths] = useState(() => {
    // Include the "Select" column + data columns
    return ['Select', ...headers].map(() => defaultColumnWidth);
  });

  useEffect(() => {
    // Include the "Select" column + data columns
    setColWidths(['Select', ...headers].map(() => defaultColumnWidth));
  }, [headers, defaultColumnWidth]);

  // 2) Whenever selection changes, notify parent with the actual row objects
  useEffect(() => {
    if (typeof onSelectionChange === 'function') {
      const selectedRows = selectedIndexes.map(i => data[i]);
      onSelectionChange(selectedRows);
    }
  }, [selectedIndexes, data, onSelectionChange]);

  useEffect(() => {
    const handleMouseMove = (e) => {
      const { active, colIndex, startX, startWidth } = draggingRef.current;
      if (!active) return;
      const dx = e.clientX - startX;
      setColWidths((prev) => {
        const next = prev.slice();
        next[colIndex] = clamp(startWidth + dx, minColumnWidth, maxColumnWidth);
        return next;
      });
      e.preventDefault();
    };

    const handleMouseUp = () => {
      if (draggingRef.current.active) {
        draggingRef.current.active = false;
        document.body.classList.remove('col-resizing');
      }
    };

    window.addEventListener('mousemove', handleMouseMove);
    window.addEventListener('mouseup', handleMouseUp);
    return () => {
      window.removeEventListener('mousemove', handleMouseMove);
      window.removeEventListener('mouseup', handleMouseUp);
    };
  }, [minColumnWidth, maxColumnWidth]);

  const startDrag = (e, index) => {
    const startWidth = colWidths[index];
    draggingRef.current = {
      active: true,
      colIndex: index,
      startX: e.clientX,
      startWidth,
    };
    document.body.classList.add('col-resizing');
    e.preventDefault();
    e.stopPropagation();
  };

  const autoFit = (index) => {
    const table = tableRef.current;
    if (!table) return;
    const cells = table.querySelectorAll(`[data-col-index="${index}"]`);
    let maxWidth = minColumnWidth;
    cells.forEach((el) => {
      const contentWidth = el.scrollWidth + 16; // padding allowance
      maxWidth = Math.max(maxWidth, contentWidth);
    });
    setColWidths((prev) => {
      const next = prev.slice();
      next[index] = clamp(maxWidth, minColumnWidth, maxColumnWidth);
      return next;
    });
  };

  const onResizerKeyDown = (e, idx) => {
    if (e.key === 'Enter') {
      autoFit(idx);
    } else if (e.key === 'ArrowLeft') {
      setColWidths((prev) => {
        const next = prev.slice();
        next[idx] = clamp(prev[idx] - 10, minColumnWidth, maxColumnWidth);
        return next;
      });
    } else if (e.key === 'ArrowRight') {
      setColWidths((prev) => {
        const next = prev.slice();
        next[idx] = clamp(prev[idx] + 10, minColumnWidth, maxColumnWidth);
        return next;
      });
    }
  };

  // ⛳ After all Hooks have run, you can early-return UI safely
  if (headers.length === 0) {
    return React.createElement('div', null, 'No data available.');
  }

  // 5) Toggle a row's index in selectedIndexes
  const toggleRow = (index) => {
    setSelectedIndexes(prev =>
      prev.includes(index)
        ? prev.filter(i => i !== index)
        : [...prev, index]
    );
  };

  // <colgroup> - includes "Select" column + data columns
  const colgroup = React.createElement(
    'colgroup',
    null,
    ['Select', ...headers].map((_, i) =>
      React.createElement('col', {
        key: `col-${i}`,
        style: { width: `${colWidths[i]}px` },
      })
    )
  );

  // <thead> - includes "Select" column + data columns with resizers
  const thead = React.createElement(
    'thead',
    null,
    React.createElement(
      'tr',
      null,
      ['Select', ...headers].map((header, idx) =>
        React.createElement(
          'th',
          { key: `header-${idx}`, 'data-col-index': idx },
          [
            React.createElement('div', { key: 'content', className: 'th-content' }, header),
            React.createElement('div', {
              key: 'resizer',
              className: 'col-resizer',
              role: 'separator',
              'aria-orientation': 'vertical',
              'aria-label': `Resize column ${header}`,
              tabIndex: 0,
              onMouseDown: (e) => startDrag(e, idx),
              onDoubleClick: () => autoFit(idx),
              onKeyDown: (e) => onResizerKeyDown(e, idx),
            }),
          ]
        )
      )
    )
  );

  // <tbody> - includes "Select" column + data columns
  const tbody = React.createElement(
    'tbody',
    null,
    (Array.isArray(filteredData) ? filteredData : []).map((row, rowIndex) =>
      React.createElement(
        'tr',
        { key: `row-${rowIndex}` },
        [
          // Select column (index 0)
          React.createElement(
            'td',
            { key: 'select', 'data-col-index': 0 },
            React.createElement('input', {
              type: 'checkbox',
              checked: selectedIndexes.includes(rowIndex),
              onChange: () => toggleRow(rowIndex),
            })
          ),
          // Data columns (indices 1+)
          ...headers.map((header, cellIndex) =>
            React.createElement(
              'td',
              { key: `cell-${rowIndex}-${cellIndex}`, 'data-col-index': cellIndex + 1 },
              String(row?.[header] ?? '')
            )
          )
        ]
      )
    )
  );

  return React.createElement(
    'div',
    { className: 'data-table-wrapper' },
    [
      // Toggle button for internal columns (only show if internal columns exist)
      hasInternal && React.createElement(
        'div',
        { key: 'toggle-container', className: 'internal-columns-toggle' },
        React.createElement(
          'button',
          {
            key: 'toggle-button',
            className: 'toggle-internal-columns',
            onClick: () => setShowInternalColumns(!showInternalColumns),
            style: {
              marginBottom: '10px',
              padding: '8px 16px',
              backgroundColor: showInternalColumns ? '#007bff' : '#6c757d',
              color: 'white',
              border: 'none',
              borderRadius: '4px',
              cursor: 'pointer',
              fontSize: '14px'
            }
          },
          showInternalColumns ? 'Hide Internal Rows' : 'Show Internal Rows'
        )
      ),
      // Table
      React.createElement(
        'table',
        { key: 'table', ref: tableRef, className: 'data-table' },
        [colgroup, thead, tbody]
      )
    ]
  );
};

export default BlobsTable;
