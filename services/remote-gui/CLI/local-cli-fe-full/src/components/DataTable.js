// import React from 'react';
// import '../styles/DataTable.css'; 


// const DataTable = ({ data }) => {
//   // If no data or empty array, render a message
//   if (!data || data.length === 0) {
//     return <div>No data available.</div>;
//   }

//   // Get table headers from the keys of the first object
//   const headers = Object.keys(data[0]);

//   return (
//     <table className="data-table">
//       <thead>
//         <tr>
//           {headers.map((header, idx) => (
//             <th key={`header-${idx}`}>{header}</th>
//           ))}
//         </tr>
//       </thead>
//       <tbody>
//         {data.map((row, rowIndex) => (
//           <tr key={`row-${rowIndex}`}>
//             {headers.map((header, cellIndex) => (
//               <td key={`cell-${rowIndex}-${cellIndex}`}>
//                 {row[header]}
//               </td>
//             ))}
//           </tr>
//         ))}
//       </tbody>
//     </table>
//   );
// };

// export default DataTable;


import React, { useEffect, useMemo, useRef, useState } from 'react';
import { filterTableData, hasInternalColumns } from '../utils/tableUtils';

const clamp = (val, min, max) => Math.max(min, Math.min(max, val));

function DataTable({
  data,
  minColumnWidth = 60,
  maxColumnWidth = 800,
  defaultColumnWidth = 150,
}) {
  const tableRef = useRef(null);
  const draggingRef = useRef({ active: false, colIndex: -1, startX: 0, startWidth: 0 });
  
  // State for showing/hiding internal columns
  const [showInternalColumns, setShowInternalColumns] = useState(false);

  // Check if data has internal columns
  const hasInternal = useMemo(() => hasInternalColumns(data), [data]);

  // Filter data based on internal column visibility
  const { data: filteredData, headers } = useMemo(() => {
    return filterTableData(data, showInternalColumns);
  }, [data, showInternalColumns]);

  // ✅ Hooks are unconditional
  const [colWidths, setColWidths] = useState(() => headers.map(() => defaultColumnWidth));

  useEffect(() => {
    setColWidths(headers.map(() => defaultColumnWidth));
  }, [headers, defaultColumnWidth]);

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

  // <colgroup>
  const colgroup = React.createElement(
    'colgroup',
    null,
    headers.map((_, i) =>
      React.createElement('col', {
        key: `col-${i}`,
        style: { width: `${colWidths[i]}px` },
      })
    )
  );

  // <thead>
  const thead = React.createElement(
    'thead',
    null,
    React.createElement(
      'tr',
      null,
      headers.map((header, idx) =>
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

  // <tbody>
  const tbody = React.createElement(
    'tbody',
    null,
    (Array.isArray(filteredData) ? filteredData : []).map((row, rowIndex) =>
      React.createElement(
        'tr',
        { key: `row-${rowIndex}` },
        headers.map((header, cellIndex) =>
          React.createElement(
            'td',
            { key: `cell-${rowIndex}-${cellIndex}`, 'data-col-index': cellIndex },
            String(row?.[header] ?? '')
          )
        )
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
}

export default DataTable;
