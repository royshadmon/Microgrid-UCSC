

// src/pages/Presets.jsx
import React, { useEffect, useState } from "react";
import {
  getPresetGroups,
  addPresetGroup,
  deletePresetGroup,
  getPresetsByGroup,
  addPreset,
  deletePreset
} from "../services/file_auth";
import "../styles/Presets.css";

const Presets = () => {
  const [groups, setGroups] = useState([]);
  const [groupName, setGroupName] = useState("");
  const [selectedGroupId, setSelectedGroupId] = useState("");
  const [presets, setPresets] = useState([]);

  const [preset, setPreset] = useState({
    command: "",
    type:    "GET",
    button:  "",
    groupName:   groupName
  });
  const [loading,    setLoading]    = useState(false);
  const [error,      setError]      = useState("");
  const [successMsg, setSuccessMsg] = useState("");

  // Import functionality
  const [importFile, setImportFile] = useState(null);
  const [importing, setImporting] = useState(false);
  const [importPreview, setImportPreview] = useState(null);

  // load groups once
  useEffect(() => {
    const loadGroups = async () => {
      try {
        const res = await getPresetGroups();
        setGroups(res.data);
      } catch (e) {
        console.error(e);
      }
    };
    loadGroups();
  }, []);

  // when group changes, load its presets
  useEffect(() => {
    if (!selectedGroupId) {
      setPresets([]);
      return;
    }
    const loadPresets = async () => {
      try {
        const res = await getPresetsByGroup({
          groupId: selectedGroupId
        });
        setPresets(res.data);
      } catch (e) {
        console.error("Failed to load presets", e);
      }
    };
    loadPresets();
  }, [selectedGroupId]);

  const handleCreateGroup = async () => {
    if (!groupName.trim()) {
      setError("Group name required");
      return;
    }
    setLoading(true);
    try {
      const res = await addPresetGroup({ name: groupName });
      // Assume new group is returned as an object in res.data
      console.log("Group created:", res.data);
      const newG = res.data.group; // Updated to match new API response format
      setGroups(g => [...g, newG]);
      setGroupName("");
      setError("");
      setSuccessMsg(`Group “${newG.group_name}” created`);
    } catch {
      setError("Failed to create group");
    } finally {
      setLoading(false);
    }
  };

  const handleDeleteGroup = async (groupId) => {
    // stop further actions
    if (!window.confirm("Delete this group and all its presets?")) {
      return;
    }
    
    // Prevent multiple rapid delete attempts
    if (loading) {
      return;
    }
    
    setLoading(true);
    try {
      console.log("Groups: ", groups)
      console.log("Group ID: ", groupId)
      console.log("Selected Group ID: ", selectedGroupId)
      console.log("Selected Group Name: ", groupName)
      const gname = groups.find(g => g.id === groupId)?.group_name;
      console.log("Gname: ", gname)
      console.log("Deleting group:", groupId, gname);
      
      if (!gname) {
        throw new Error(`Group name not found for ID: ${groupId}`);
      }
      
      // Check if group still exists before attempting delete
      const currentGroup = groups.find(g => g.id === groupId);
      if (!currentGroup) {
        throw new Error("Group no longer exists");
      }
      
      // Small delay to prevent rapid clicking issues
      await new Promise(resolve => setTimeout(resolve, 100));
      
      const res = await deletePresetGroup({ groupId, groupName: gname });
      console.log("Group deleted:", res.data);
      
      // Verify the group was actually deleted before updating state
      if (res.data && res.data.success !== false) {
      // remove from state
      setGroups(g => g.filter(x => x.id !== groupId));
      // if it was selected, clear selection
      if (selectedGroupId === groupId) {
        setSelectedGroupId("");
        setPresets([]);
      }
      setError("");
      setSuccessMsg("Group deleted");
      } else {
        throw new Error("Server indicated delete operation failed");
      }
    } catch (error) {
      console.error("Delete group error:", error);
      setError(`Failed to delete group: ${error.message}`);
    } finally {
      setLoading(false);
    }
  };

  const handleCreatePreset = async () => {

    const gname = groups.find(g => g.id === selectedGroupId)?.group_name;
    
    if (!preset.command.trim() || !preset.button.trim()) {
      setError("Command and button label required");
      return;
    }
    setLoading(true);
    try {
      const res = await addPreset({ 
        preset: { 
          ...preset, 
          group_id: selectedGroupId,
          group_name: gname
        } 
      });
      console.log("Preset created:", res.data);
      const newP = res.data.preset;
      setPresets(p => [...p, newP]);
      setPreset({ command: "", type: "GET", button: "", groupName: gname });
      setError("");
      setSuccessMsg(`Preset "${newP.button}" created`);
    } catch {
      setError("Failed to create preset");
    } finally {
      setLoading(false);
    }
  };

  const handleDeletePreset = async (presetId) => {
    if (!window.confirm("Delete this preset?")) {
      return;
    }
    setLoading(true);
    try {
      const res = await deletePreset({ presetId });
      console.log("Preset deleted:", res.data);
      // remove from state
      setPresets(p => p.filter(x => x.id !== presetId));
      setError("");
      setSuccessMsg("Preset deleted");
    } catch {
      setError("Failed to delete preset");
    } finally {
      setLoading(false);
    }
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
      setError("Invalid import data format - expected an array of groups");
      return;
    }

    setImporting(true);
    setError("");
    let importedCount = 0;
    let errors = [];

    try {
      for (const groupData of importPreview) {
        // Validate group structure - support both formats
        if (!groupData.group && !groupData.group_name) {
          errors.push(`Invalid group data - missing group name: ${JSON.stringify(groupData)}`);
          continue;
        }

        // Support both "group" and "group_name" fields
        const groupName = groupData.group || groupData.group_name;
        
        if (!Array.isArray(groupData.queries)) {
          errors.push(`Invalid group data - missing queries array for group "${groupName}": ${JSON.stringify(groupData)}`);
          continue;
        }

        // Check if group already exists
        let existingGroup = groups.find(g => g.group_name === groupName);
        let targetGroup;

        if (existingGroup) {
          // Group exists - use existing group
          targetGroup = existingGroup;
          console.log(`Using existing group "${groupName}" (ID: ${existingGroup.id})`);
        } else {
          // Group doesn't exist - create new group
          try {
            const groupRes = await addPresetGroup({ name: groupName });
            targetGroup = groupRes.data.group;
            setGroups(g => [...g, targetGroup]);
            console.log(`Created new group "${groupName}" (ID: ${targetGroup.id})`);
          } catch (groupError) {
            errors.push(`Failed to create group "${groupName}": ${groupError.message}`);
            continue;
          }
        }
        
        // Create presets for this group
        for (const query of groupData.queries) {
          // Support both "name" and "button" fields for the preset name
          const presetName = query.name || query.button;
          
          if (!presetName || !query.command || !query.type) {
            errors.push(`Invalid query data in group "${groupName}" - missing required fields: ${JSON.stringify(query)}`);
            continue;
          }

          // Validate type is GET or POST
          if (!['GET', 'POST'].includes(query.type.toUpperCase())) {
            errors.push(`Invalid query type "${query.type}" in group "${groupName}" - must be GET or POST`);
            continue;
          }

          try {
            await addPreset({
              preset: {
                command: query.command,
                type: query.type.toUpperCase(),
                button: presetName,
                group_id: targetGroup.id,
                group_name: targetGroup.group_name
              }
            });
            importedCount++;
          } catch (presetError) {
            errors.push(`Failed to create preset "${presetName}" in group "${groupName}": ${presetError.message}`);
          }
        }
      }

      // Show results
      if (errors.length > 0) {
        setError(`Import completed with ${errors.length} errors. Imported ${importedCount} presets. Errors: ${errors.join('; ')}`);
      } else {
        setSuccessMsg(`Successfully imported ${importedCount} presets from ${importPreview.length} groups`);
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
    if (groups.length === 0) {
      setError("No groups to export");
      return;
    }

    try {
      // Debug logging
      console.log("Export Debug - Groups:", groups);
      
      // Fetch all presets for all groups
      const allPresets = [];
      for (const group of groups) {
        try {
          const res = await getPresetsByGroup({ groupId: group.id });
          const groupPresets = res.data || [];
          console.log(`Group "${group.group_name}" (ID: ${group.id}) has ${groupPresets.length} presets`);
          allPresets.push(...groupPresets);
        } catch (error) {
          console.error(`Failed to fetch presets for group "${group.group_name}":`, error);
        }
      }
      
      console.log("Export Debug - All Presets:", allPresets);
      
      // Create export data structure - only include groups with presets
      const exportData = groups
        .map(group => {
          // Find presets for this group from all presets
          const groupPresets = allPresets.filter(p => p.group_id === group.id);
          
          // Only include groups that have presets
          if (groupPresets.length === 0) {
            return null;
          }
          
          return {
            group: group.group_name,
            queries: groupPresets.map(preset => ({
              name: preset.button,
              command: preset.command,
              type: preset.type
            }))
          };
        })
        .filter(group => group !== null); // Remove null entries (empty groups)

      console.log("Final export data:", exportData);

      if (exportData.length === 0) {
        setError("No groups with presets to export");
        return;
      }

      // Create and download JSON file
      const dataStr = JSON.stringify(exportData, null, 2);
      const dataBlob = new Blob([dataStr], { type: 'application/json' });
      const url = URL.createObjectURL(dataBlob);
      
      const link = document.createElement('a');
      link.href = url;
      link.download = `presets-export-${new Date().toISOString().split('T')[0]}.json`;
      document.body.appendChild(link);
      link.click();
      document.body.removeChild(link);
      URL.revokeObjectURL(url);

      const totalPresets = exportData.reduce((sum, group) => sum + group.queries.length, 0);
      setSuccessMsg(`Exported ${exportData.length} groups with ${totalPresets} presets`);
    } catch (error) {
      setError(`Export failed: ${error.message}`);
    }
  };

  return (
    <div className="container">
      <section className="import-section">
        <h2>📁 Import Presets from JSON</h2>
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
              disabled={groups.length === 0}
              className="export-btn"
              title="Export all presets as JSON"
            >
              📤 Export All Presets
            </button>
          </div>
          {importFile && (
            <div className="file-info">
              <p>Selected file: {importFile.name}</p>
              {importPreview && (
                <div className="import-preview">
                  <h4>Preview:</h4>
                  <ul>
                    {importPreview.map((group, index) => {
                      const groupName = group.group || group.group_name;
                      const queries = group.queries || [];
                      const validQueries = queries.filter(q => 
                        (q.name || q.button) && q.command && q.type && 
                        ['GET', 'POST'].includes(q.type.toUpperCase())
                      );
                      const invalidQueries = queries.length - validQueries.length;
                      
                      return (
                        <li key={index}>
                          <strong>{groupName}</strong> - {queries.length} queries
                          {invalidQueries > 0 && (
                            <span style={{ color: '#dc3545', fontSize: '0.8rem' }}>
                              {' '}({invalidQueries} invalid)
                            </span>
                          )}
                        </li>
                      );
                    })}
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

      <section className="group-section">
        <h2>📁 Manage Groups</h2>
        <div className="form-row">
          <input
            type="text"
            placeholder="New group name"
            value={groupName}
            onChange={e => setGroupName(e.target.value)}
          />
          <button onClick={handleCreateGroup} disabled={loading}>
            Create
          </button>
        </div>
        <ul className="group-list">
          {groups.map(g => (
            <li
              key={g.id}
              className={selectedGroupId === g.id ? "selected" : ""}
            >
              <span
                onClick={() => {
                  setSelectedGroupId(g.id);
                  setSuccessMsg("");
                  setError("");
                }}
              >
                {g.group_name}
              </span>
              <button
                className="delete-btn"
                disabled={loading}
                onClick={() => handleDeleteGroup(g.id)}
                title="Delete group and all its presets"
              >
                🗑️
              </button>
            </li>
          ))}
        </ul>
      </section>

      <section className="preset-section">
        <h2>➕ Add & View Presets</h2>
        <div className="form-row">
          <label htmlFor="group-select">Group:</label>
          <select
            id="group-select"
            value={selectedGroupId}
            onChange={e => setSelectedGroupId(e.target.value)}
          >
            <option value="">– choose –</option>
            {groups.map(g => (
              <option key={g.id} value={g.id}>
                {g.group_name}
              </option>
            ))}
          </select>
        </div>

        {selectedGroupId && (
          <>
            <div className="form-row">
              <input
                type="text"
                placeholder="Button Label"
                value={preset.button}
                onChange={e =>
                  setPreset({ ...preset, button: e.target.value })
                }
              />
              <select
                value={preset.type}
                onChange={e =>
                  setPreset({ ...preset, type: e.target.value })
                }
              >
                <option value="GET">GET</option>
                <option value="POST">POST</option>
              </select>
              <input
                type="text"
                placeholder="Command"
                value={preset.command}
                onChange={e =>
                  setPreset({ ...preset, command: e.target.value })
                }
              />
              <button onClick={handleCreatePreset} disabled={loading}>
                Add Preset
              </button>
            </div>

            <ul className="preset-list">
              {presets.length === 0 ? (
                <li className="empty-state">
                  <div className="preset-content">
                    <div className="preset-command" style={{ textAlign: 'center', color: '#6c757d', fontStyle: 'italic' }}>
                      No presets in this group yet. Add your first preset above!
                    </div>
                  </div>
                </li>
              ) : (
                presets.map(p => (
                  <li key={p.id}>
                    <div className="preset-content">
                      <div className="preset-header">
                        <span className="preset-button">{p.button}</span>
                        <span className="preset-type">{p.type}</span>
                      </div>
                      <div className="preset-command">{p.command}</div>
                    </div>
                    <button
                      className="delete-btn"
                      disabled={loading}
                      onClick={() => handleDeletePreset(p.id)}
                      title="Delete preset"
                    >
                      🗑️
                    </button>
                  </li>
                ))
              )}
            </ul>
          </>
        )}
      </section>

      {error && <div className="error-message">{error}</div>}
      {successMsg && (
        <div className="success-message">{successMsg}</div>
      )}
    </div>
  );
};

export default Presets;
