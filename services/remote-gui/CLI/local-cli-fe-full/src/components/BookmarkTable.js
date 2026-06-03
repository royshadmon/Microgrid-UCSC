import React, { useState } from 'react';
import '../styles/DataTable.css';

const BookmarkTable = ({ data, onDelete, onUpdateDescription }) => {
  const [editingNode, setEditingNode] = useState(null);
  const [tempDescription, setTempDescription] = useState('');

  if (!data || data.length === 0) {
    return <div>No bookmarks available.</div>;
  }

  const startEditing = (node, currentDescription) => {
    setEditingNode(node);
    setTempDescription(currentDescription || '');
  };

  const saveDescription = (node) => {
    onUpdateDescription(node, tempDescription);
    setEditingNode(null);
  };

  return (
    <table className="data-table">
      <thead>
        <tr>
          <th>Node</th>
          <th>Description</th>
          <th>Actions</th>
        </tr>
      </thead>
      <tbody>
        {data.map((bookmark, index) => (
          <tr key={`bookmark-${index}`}>
            <td>{bookmark.node}</td>
            <td>
              {editingNode === bookmark.node ? (
                <>
                  <input
                    type="text"
                    value={tempDescription}
                    onChange={(e) => setTempDescription(e.target.value)}
                    style={{ width: '100%' }}
                  />
                  <button
                    onClick={() => saveDescription(bookmark.node)}
                    style={{
                      marginLeft: '0.5rem',
                      backgroundColor: '#2ecc71',
                      color: 'white',
                      border: 'none',
                      borderRadius: '4px',
                      padding: '4px 8px',
                      cursor: 'pointer',
                    }}
                  >
                    Save
                  </button>
                </>
              ) : (
                <>
                  {bookmark.description || <i style={{ color: 'gray' }}>No description</i>}
                  <button
                    onClick={() => startEditing(bookmark.node, bookmark.description)}
                    style={{
                      marginLeft: '0.5rem',
                      backgroundColor: '#3498db',
                      color: 'white',
                      border: 'none',
                      borderRadius: '4px',
                      padding: '4px 8px',
                      cursor: 'pointer',
                    }}
                  >
                    Edit
                  </button>
                </>
              )}
            </td>
            <td>
              <button
                onClick={() => onDelete(bookmark.node)}
                style={{
                  backgroundColor: '#e74c3c',
                  color: 'white',
                  border: 'none',
                  borderRadius: '4px',
                  padding: '6px 12px',
                  cursor: 'pointer',
                }}
              >
                Delete
              </button>
            </td>
          </tr>
        ))}
      </tbody>
    </table>
  );
};

export default BookmarkTable;

