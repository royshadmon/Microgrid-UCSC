// src/pages/Bookmarks.jsx
import React, { useEffect, useState } from "react";
import {
  getBookmarks,
  bookmarkNode,
  deleteBookmarkedNode,
  updateBookmarkDescription,
  setDefaultBookmark
} from "../services/file_auth";
import "../styles/Bookmarks.css";

const Bookmarks = ({ node, onSelectNode }) => {
  const [bookmarks, setBookmarks] = useState([]);
  const [newBookmark, setNewBookmark] = useState({
    node: "",
    description: ""
  });
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [successMsg, setSuccessMsg] = useState("");
  const [nodeSelectionMsg, setNodeSelectionMsg] = useState("");

  // Import functionality
  const [importFile, setImportFile] = useState(null);
  const [importing, setImporting] = useState(false);
  const [importPreview, setImportPreview] = useState(null);

  // Load bookmarks on component mount and listen for refresh events
  useEffect(() => {
    loadBookmarks();
    
    // Listen for bookmark refresh events from NodePicker
    const handleBookmarkRefresh = () => {
      console.log("Bookmark refresh event received");
      loadBookmarks();
    };
    
    window.addEventListener('bookmark-refresh', handleBookmarkRefresh);
    
    // Cleanup event listener on component unmount
    return () => {
      window.removeEventListener('bookmark-refresh', handleBookmarkRefresh);
    };
  }, []);

  // Auto-clear node selection message
  useEffect(() => {
    if (!nodeSelectionMsg) return;

    const timer = setTimeout(() => {
      setNodeSelectionMsg("");
    }, 3000);

    return () => clearTimeout(timer);
  }, [nodeSelectionMsg]);

  const loadBookmarks = async () => {
    try {
      setLoading(true);
      const res = await getBookmarks();
      setBookmarks(res.data || []);
    } catch (e) {
      console.error("Failed to load bookmarks", e);
      setError("Failed to load bookmarks");
    } finally {
      setLoading(false);
    }
  };

  const handleCreateBookmark = async () => {
    if (!newBookmark.node.trim()) {
      setError("Node name required");
      return;
    }
    setLoading(true);
    try {
      // Create the bookmark with the node
      const res = await bookmarkNode({ node: newBookmark.node });
      console.log("Bookmark created:", res);
      
      // If there's a description, update it
      if (newBookmark.description && newBookmark.description.trim()) {
        try {
          await updateBookmarkDescription({ 
            node: newBookmark.node, 
            description: newBookmark.description.trim() 
          });
          console.log("Bookmark description updated");
        } catch (descError) {
          console.warn("Failed to update bookmark description:", descError);
          // Don't fail the entire operation if description update fails
        }
      }
      
      // Reload bookmarks to get the updated list
      await loadBookmarks();
      
      setNewBookmark({ node: "", description: "" });
      setError("");
      setSuccessMsg(`Bookmark "${newBookmark.node}" created${newBookmark.description ? ' with description' : ''}`);
    } catch (error) {
      setError("Failed to create bookmark");
    } finally {
      setLoading(false);
    }
  };

  const handleDeleteBookmark = async (node) => {
    if (!window.confirm("Delete this bookmark?")) {
      return;
    }
    setLoading(true);
    try {
      const res = await deleteBookmarkedNode({ node });
      console.log("Bookmark deleted:", res);
      
      // Reload bookmarks to get the updated list
      await loadBookmarks();
      
      setError("");
      setSuccessMsg("Bookmark deleted");
    } catch (error) {
      setError("Failed to delete bookmark");
    } finally {
      setLoading(false);
    }
  };

  const [editingDescriptions, setEditingDescriptions] = useState({});
  const [descriptionValues, setDescriptionValues] = useState({});

  const handleUpdateDescription = async (node, description) => {
    setLoading(true);
    try {
      const res = await updateBookmarkDescription({ node, description });
      console.log("Bookmark updated:", res);
      
      // Update the bookmark in the local state
      setBookmarks(prev => prev.map(bookmark => 
        bookmark.node === node 
          ? { ...bookmark, description } 
          : bookmark
      ));
      
      // Clear editing state for this bookmark
      setEditingDescriptions(prev => ({ ...prev, [node]: false }));
      setDescriptionValues(prev => ({ ...prev, [node]: description }));
      
      setError("");
      setSuccessMsg("Bookmark description updated");
    } catch (error) {
      setError("Failed to update bookmark description");
    } finally {
      setLoading(false);
    }
  };

  const handleSetDefault = async (node) => {
    setLoading(true);
    try {
      await setDefaultBookmark({ node });
      // reload to reflect updated flags
      await loadBookmarks();
      setSuccessMsg(`Set ${node} as default`);
      setError("");
    } catch (error) {
      setError("Failed to set default bookmark");
    } finally {
      setLoading(false);
    }
  };

  const handleStartEditing = (node, currentDescription) => {
    setEditingDescriptions(prev => ({ ...prev, [node]: true }));
    setDescriptionValues(prev => ({ ...prev, [node]: currentDescription || "" }));
  };

  const handleCancelEditing = (node) => {
    setEditingDescriptions(prev => ({ ...prev, [node]: false }));
    setDescriptionValues(prev => ({ ...prev, [node]: "" }));
  };

  // Import functionality
  const handleFileUpload = (event) => {
    const file = event.target.files[0];
    if (!file) return;

    if (file.type !== 'application/json' && !file.name.endsWith('.json')) {
      setError("Please select a valid JSON file");
      return;
    }

    setImportFile(file);
    setError("");

    const reader = new FileReader();
    reader.onload = (e) => {
      try {
        const jsonData = JSON.parse(e.target.result);
        setImportPreview(jsonData);
      } catch (parseError) {
        setError("Invalid JSON format");
        setImportPreview(null);
      }
    };
    reader.readAsText(file);
  };

  const handleImport = async () => {
    if (!importPreview || !Array.isArray(importPreview)) {
      setError("Invalid import data format - expected an array of bookmarks");
      return;
    }

    setImporting(true);
    setError("");
    let importedCount = 0;
    let errors = [];

    try {
      for (const bookmarkData of importPreview) {
        if (!bookmarkData.node) {
          errors.push(`Invalid bookmark data - missing node: ${JSON.stringify(bookmarkData)}`);
          continue;
        }

        try {
          // Create the bookmark
          await bookmarkNode({ node: bookmarkData.node });
          
          // If there's a description, update it
          if (bookmarkData.description && bookmarkData.description.trim()) {
            await updateBookmarkDescription({ 
              node: bookmarkData.node, 
              description: bookmarkData.description.trim() 
            });
          }
          
          importedCount++;
        } catch (bookmarkError) {
          errors.push(`Failed to create bookmark "${bookmarkData.node}": ${bookmarkError.message}`);
        }
      }

      // Reload bookmarks after import
      await loadBookmarks();

      // Show results
      if (errors.length > 0) {
        setError(`Import completed with ${errors.length} errors. Imported ${importedCount} bookmarks. Errors: ${errors.join('; ')}`);
      } else {
        setSuccessMsg(`Successfully imported ${importedCount} bookmarks`);
      }

      // Clear import state
      setImportFile(null);
      setImportPreview(null);
      setImporting(false);
    } catch (error) {
      setError(`Import failed: ${error.message}`);
      setImporting(false);
    }
  };

  const handleCancelImport = () => {
    setImportFile(null);
    setImportPreview(null);
    setError("");
  };

  // Export functionality
  const handleExport = async () => {
    if (bookmarks.length === 0) {
      setError("No bookmarks to export");
      return;
    }

    try {
      // Create export data structure
      const exportData = bookmarks.map(bookmark => ({
        node: bookmark.node,
        description: bookmark.description || "",
        created_at: bookmark.created_at || new Date().toISOString()
      }));

      // Create and download JSON file
      const dataStr = JSON.stringify(exportData, null, 2);
      const dataBlob = new Blob([dataStr], { type: 'application/json' });
      const url = URL.createObjectURL(dataBlob);
      
      const link = document.createElement('a');
      link.href = url;
      link.download = `bookmarks-export-${new Date().toISOString().split('T')[0]}.json`;
      document.body.appendChild(link);
      link.click();
      document.body.removeChild(link);
      URL.revokeObjectURL(url);

      setSuccessMsg(`Exported ${exportData.length} bookmarks`);
    } catch (error) {
      setError(`Export failed: ${error.message}`);
    }
  };

  return (
    <div className="container">
      <section className="import-section">
        <h2>📁 Import Bookmarks from JSON</h2>
        <div className="import-container">
          <div className="import-export-actions">
            <input
              type="file"
              accept=".json"
              onChange={handleFileUpload}
              disabled={importing}
              className="file-input"
            />
            <button 
              onClick={handleExport} 
              disabled={bookmarks.length === 0}
              className="export-btn"
              title="Export all bookmarks as JSON"
            >
              📤 Export All Bookmarks
            </button>
          </div>
          {importFile && (
            <div className="file-info">
              <p>Selected file: {importFile.name}</p>
              {importPreview && (
                <div className="import-preview">
                  <h4>Preview:</h4>
                  <ul>
                    {importPreview.map((bookmark, index) => (
                      <li key={index}>
                        <strong>{bookmark.node}</strong>
                        {bookmark.description && ` - ${bookmark.description}`}
                      </li>
                    ))}
                  </ul>
                  <div className="import-actions">
                    <button 
                      onClick={handleImport} 
                      disabled={importing}
                      className="import-btn"
                    >
                      {importing ? "Importing..." : "Import All"}
                    </button>
                    <button 
                      onClick={handleCancelImport} 
                      disabled={importing}
                      className="cancel-btn"
                    >
                      Cancel
                    </button>
                  </div>
                </div>
              )}
            </div>
          )}
        </div>
      </section>

      <section className="bookmark-section">
        <h2>➕ Add & View Bookmarks</h2>
        <div className="form-row">
          <input
            type="text"
            placeholder="Node ip:port"
            value={newBookmark.node}
            onChange={e => setNewBookmark({ ...newBookmark, node: e.target.value })}
          />
          <input
            type="text"
            placeholder="Description (optional)"
            value={newBookmark.description}
            onChange={e => setNewBookmark({ ...newBookmark, description: e.target.value })}
          />
          <button onClick={handleCreateBookmark} disabled={loading}>
            Add Bookmark
          </button>
        </div>

        <ul className="bookmark-list">
          {bookmarks.length === 0 ? (
            <li className="empty-state">
              <div className="bookmark-content">
                <div className="bookmark-node" style={{ textAlign: 'center', color: '#6c757d', fontStyle: 'italic' }}>
                  No bookmarks yet. Add your first bookmark above!
                </div>
              </div>
            </li>
          ) : (
            bookmarks.map(bookmark => (
              <li key={bookmark.node}>
                <div className="bookmark-content">
                  <div className="bookmark-header">
                    <span className="bookmark-node">{bookmark.node}</span>
                    {bookmark.is_default && (
                      <span className="default-badge" style={{
                        marginLeft: '0.5rem',
                        backgroundColor: '#ffd54f',
                        color: '#000',
                        borderRadius: '4px',
                        padding: '2px 6px',
                        fontSize: '0.8rem',
                        fontWeight: 600
                      }}>
                        Default
                      </span>
                    )}
                    <span className="bookmark-date">
                      {new Date(bookmark.created_at).toLocaleDateString()}
                    </span>
                  </div>
                  <div className="bookmark-description">
                    {editingDescriptions[bookmark.node] ? (
                      <div className="description-edit-container">
                        <input
                          type="text"
                          placeholder="Add description..."
                          value={descriptionValues[bookmark.node] || ""}
                          onChange={(e) => setDescriptionValues(prev => ({ 
                            ...prev, 
                            [bookmark.node]: e.target.value 
                          }))}
                          className="description-input"
                        />
                        <div className="description-actions">
                          <button
                            className="save-btn"
                            disabled={loading}
                            onClick={() => handleUpdateDescription(bookmark.node, descriptionValues[bookmark.node])}
                            title="Save description"
                          >
                            💾 Save
                          </button>
                          <button
                            className="cancel-btn"
                            disabled={loading}
                            onClick={() => handleCancelEditing(bookmark.node)}
                            title="Cancel editing"
                          >
                            ❌ Cancel
                          </button>
                        </div>
                      </div>
                    ) : (
                      <div className="description-display-container">
                        <span className="description-text">
                          {bookmark.description || "No description"}
                        </span>
                        <button
                          className="edit-btn"
                          disabled={loading}
                          onClick={() => handleStartEditing(bookmark.node, bookmark.description)}
                          title="Edit description"
                        >
                          ✏️ Edit
                        </button>
                      </div>
                    )}
                  </div>
                </div>
                <div className="bookmark-actions">
                  <button
                    className="use-node-btn"
                    disabled={loading || bookmark.is_default}
                    onClick={() => handleSetDefault(bookmark.node)}
                    title={bookmark.is_default ? "Already default" : "Set as default"}
                  >
                    {bookmark.is_default ? '⭐ Default' : 'Set as default'}
                  </button>
                  <button
                    className="use-node-btn"
                    disabled={loading}
                    onClick={() => {
                      console.log("Use Node clicked for:", bookmark.node);
                      console.log("onSelectNode function:", onSelectNode);
                      if (onSelectNode) {
                        onSelectNode(bookmark.node);
                        setNodeSelectionMsg(`✅ Selected node: ${bookmark.node}`);
                        console.log("Node selection function called");
                      } else {
                        console.log("onSelectNode function not available");
                      }
                    }}
                    title="Use this node as selected node"
                  >
                    ✅ Use Node
                  </button>
                  <button
                    className="delete-btn"
                    disabled={loading}
                    onClick={() => handleDeleteBookmark(bookmark.node)}
                    title="Delete bookmark"
                  >
                    🗑️
                  </button>
                </div>
              </li>
            ))
          )}
        </ul>
      </section>

      {error && <div className="error-message">{error}</div>}
      {successMsg && (
        <div className="success-message">{successMsg}</div>
      )}
      {nodeSelectionMsg && (
        <div className="success-message">{nodeSelectionMsg}</div>
      )}
    </div>
  );
};

export default Bookmarks;
