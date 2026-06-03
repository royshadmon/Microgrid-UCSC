import React, { useState, useEffect } from 'react';
import { fetchAvailablePermissions } from '../../services/security_api';
import '../../styles/security/PermissionPolicySelector.css';

function PermissionPolicySelector({ node, selectedPermissionId, onChange, disabled = false, refreshTrigger = 0 }) {
  const [availablePermissions, setAvailablePermissions] = useState([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);
  const [searchTerm, setSearchTerm] = useState('');

  useEffect(() => {
    if (node) {
      fetchPermissions();
    }
  }, [node, refreshTrigger]);

  const fetchPermissions = async () => {
    setLoading(true);
    setError(null);
    
    try {
      const permissions = await fetchAvailablePermissions(node);
      console.log("[DEBUG] PermissionPolicySelector received permissions:", permissions);
      console.log("[DEBUG] Permissions type:", typeof permissions);
      console.log("[DEBUG] Is array:", Array.isArray(permissions));
      
      if (Array.isArray(permissions)) {
        setAvailablePermissions(permissions);
      } else {
        console.error("[DEBUG] Permissions is not an array:", permissions);
        setError('Invalid permissions data received');
      }
    } catch (err) {
      setError('Failed to fetch available permissions');
      console.error('Error fetching permissions:', err);
    } finally {
      setLoading(false);
    }
  };

  const handlePermissionSelect = (permissionToSelect) => {
    if (disabled) return;
    
    // Single selection - if clicking the same permission, deselect it
    if (selectedPermissionId === permissionToSelect.id) {
      onChange('');
    } else {
      onChange(permissionToSelect.id); // Use the ID, not the name
    }
  };

  const filteredPermissions = availablePermissions.filter(permission =>
    permission.name.toLowerCase().includes(searchTerm.toLowerCase()) ||
    permission.id.toLowerCase().includes(searchTerm.toLowerCase()) ||
    permission.type.toLowerCase().includes(searchTerm.toLowerCase())
  );

  if (loading) {
    return (
      <div className="permission-policy-selector">
        <p>Loading available permission policies...</p>
      </div>
    );
  }

  if (error) {
    return (
      <div className="permission-policy-selector error">
        <p>Error: {error}</p>
        <button onClick={fetchPermissions} disabled={loading}>Retry</button>
      </div>
    );
  }

  return (
    <div className="permission-policy-selector">
      <div className="permission-policy-selector-header">
        <input
          type="text"
          placeholder="Search permission policies..."
          value={searchTerm}
          onChange={(e) => setSearchTerm(e.target.value)}
          className="permission-search-input"
          disabled={disabled}
        />
        <button 
          onClick={fetchPermissions} 
          className="refresh-permissions-button"
          disabled={loading || disabled}
          title="Refresh the list of available permission policies"
        >
          {loading ? 'Refreshing...' : '🔄 Refresh'}
        </button>
      </div>

      <div className="permission-cards-grid">
        {filteredPermissions.length > 0 ? (
          filteredPermissions.map((permission) => {
            const isSelected = selectedPermissionId === permission.id;
            return (
              <div 
                key={permission.id} 
                className={`permission-card ${isSelected ? 'selected' : ''} ${disabled ? 'disabled' : ''}`}
                onClick={() => !disabled && handlePermissionSelect(permission)}
              >
                <div className="permission-card-header">
                  <span className="permission-card-name">{permission.name}</span>
                  {/* <span className={`permission-card-type type-${permission.type}`}>{permission.type}</span> */}
                  <span className="permission-card-checkbox">{isSelected ? '✓' : '○'}</span>
                </div>
                {permission.description && <p className="permission-card-description">{permission.description}</p>}
              </div>
            );
          })
        ) : (
          <p className="no-permissions-found">No permission policies found. Try refreshing or creating new permission policies.</p>
        )}
      </div>

    </div>
  );
}

export default PermissionPolicySelector;
