// src/components/NodePicker.js
import React, { useState } from 'react';
import { getConnectedNodes } from '../services/api'; // Adjust the import path as necessary
import { bookmarkNode } from '../services/file_auth';
import '../styles/NodePicker.css'; // Optional: create a CSS file for node picker styling
import { isLoggedIn } from '../services/file_auth';
import { useEffect } from 'react';

const NodePicker = ({ nodes, selectedNode, onAddNode, onSelectNode, onBookmarkAdded }) => {
  const [newNode, setNewNode] = useState('');
  const [error, setError] = useState(null);
  const [local, setLocal] = useState(false);
  const [bookmarkMsg, setBookmarkMsg] = useState(null);
  const [showAddNode, setShowAddNode] = useState(false);

  useEffect(() => {
    if (!bookmarkMsg) return;

    const timer = setTimeout(() => {
      setBookmarkMsg(null);
    }, 5000); // 3000ms = 3s

    return () => clearTimeout(timer);
  }, [bookmarkMsg]);

  const handleAdd = () => {
    // Basic validation: check that new node is not empty, and ideally matches "ip:port" format
    if (newNode.trim()) {
      onAddNode(newNode.trim());
      onSelectNode(newNode.trim());
      setNewNode('');
      setShowAddNode(false);
    }
  };

  const handleAddConnectedNodes = async (e) => {
    e.preventDefault();
    setError(null);

    try {
      console.log("Selected Node is this:", selectedNode);
      const fetchedNodes = await getConnectedNodes({ selectedNode });
      for (const node of fetchedNodes.data) {
        console.log(node);
        onAddNode(node);
      }

    } catch (err) {
      setError("Failed to test network.");
    }
  };

  const makeLocal = (node, isLocal) => {
    if (!node) return node;  // Return if node is empty
    const parts = node.split(':');
    if (isLocal && parts.length === 2) {  // Check if local is true and node is in "ip:port" format
      console.log("MADE LOCAL")
      return `127.0.0.1:${parts[1]}`;
    }
    return node;
  };

  const handleLocalChange = (e) => {
    const isLocal = e.target.checked;
    setLocal(isLocal);
    console.log("Local mode is now:", e.target.checked);
    // console.log("makeLocal is now:", makeLocal(selectedNode));
    onSelectNode(makeLocal(selectedNode, isLocal));
  }

  const handleBookmark = async () => {
    if (!selectedNode) {
      setBookmarkMsg('No node selected to bookmark.');
      return;
    }
    setError(null);
    setBookmarkMsg(null);

    try {
      if (isLoggedIn()) {
        await bookmarkNode({ node: selectedNode });
        setBookmarkMsg(`Bookmarked ${selectedNode}!`);
        
        // Dispatch event to refresh bookmarks globally
        window.dispatchEvent(new Event('bookmark-refresh'));
        
        // Call the callback to refresh bookmarks in parent component
        if (onBookmarkAdded) {
          onBookmarkAdded();
        }
      }
    } catch (err) {
      console.error('Bookmark failed:', err);
      setError('Could not bookmark node. Try again.');
    }
  };

  const handleDropdownChange = (e) => {
    const value = e.target.value;
    if (value === 'add-node') {
      setShowAddNode(true);
    } else {
      onSelectNode(value);
      setShowAddNode(false);
    }
  };

  // If no node is selected, show connection input
  if (!selectedNode) {
    return (
      <div className="node-picker-container">
        <div className="connection-box">
          <input
            className="node-picker-input"
            type="text"
            placeholder="Enter Node Connection (IP:Port)"
            value={newNode}
            onChange={(e) => setNewNode(e.target.value)}
            onKeyPress={(e) => e.key === 'Enter' && handleAdd()}
          />
          <button className="node-picker-btn primary" onClick={handleAdd}>
            Connect
          </button>
        </div>
        {bookmarkMsg && (
          <div className="bookmark-msg">
            {bookmarkMsg}
          </div>
        )}
        {error && (
          <div className="error">
            {error}
          </div>
        )}
      </div>
    );
  }

  // If node is selected, show dropdown with "Add Node" option
  return (
    <div className="node-picker-container">
      <div className="connected-node-section">
        <select
          className="node-picker-select"
          value={selectedNode}
          onChange={handleDropdownChange}
        >
          {nodes.map((node, index) => (
            <option key={index} value={node}>
              {node}
            </option>
          ))}
          <option value="add-node">+ Add New Node</option>
        </select>
        
        <button className="node-picker-btn secondary" onClick={handleBookmark}>
          Bookmark
        </button>
      </div>

      {showAddNode && (
        <div className="add-node-section">
          <input
            className="node-picker-input"
            type="text"
            placeholder="Enter New Node Connection (IP:Port)"
            value={newNode}
            onChange={(e) => setNewNode(e.target.value)}
            onKeyPress={(e) => e.key === 'Enter' && handleAdd()}
          />
          <button className="node-picker-btn primary" onClick={handleAdd}>
            Add & Connect
          </button>
          <button className="node-picker-btn cancel" onClick={() => {
            setShowAddNode(false);
            setNewNode('');
          }}>
            Cancel
          </button>
        </div>
      )}

      {bookmarkMsg && (
        <div className="bookmark-msg">
          {bookmarkMsg}
        </div>
      )}
      {error && (
        <div className="error">
          {error}
        </div>
      )}
    </div>
  );
};


export default NodePicker;