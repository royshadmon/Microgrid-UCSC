import React, { useState, useEffect } from 'react';
import { fetchAvailableSigningMembers } from '../../services/security_api';
import '../../styles/security/MemberSelector.css';

function MemberSelector({ node, currentUserPubkey, selectedMembers = [], onChange, disabled = false, refreshTrigger = 0 }) {
  const [availableMembers, setAvailableMembers] = useState([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);

  useEffect(() => {
    if (node) {
      fetchMembers();
    }
  }, [node, refreshTrigger]);

  const fetchMembers = async () => {
    setLoading(true);
    setError(null);
    
    try {
      // If no currentUserPubkey provided, use a default/empty one for fetching all members
      const pubkey = currentUserPubkey || '';
      const result = await fetchAvailableSigningMembers(node, pubkey);
      if (result.success) {
        setAvailableMembers(result.data);
      } else {
        setError(result.error || 'Failed to fetch available members');
      }
    } catch (err) {
      setError('Failed to fetch available members');
      console.error('Error fetching members:', err);
    } finally {
      setLoading(false);
    }
  };

  const handleMemberToggle = (member) => {
    const isSelected = selectedMembers.some(selected => selected.public_key === member.public_key);
    
    if (isSelected) {
      // Remove member
      const updatedMembers = selectedMembers.filter(selected => selected.public_key !== member.public_key);
      onChange(updatedMembers);
    } else {
      // Add member
      const updatedMembers = [...selectedMembers, member];
      onChange(updatedMembers);
    }
  };

  const handleRemoveMember = (memberToRemove) => {
    const updatedMembers = selectedMembers.filter(member => member.public_key !== memberToRemove.public_key);
    onChange(updatedMembers);
  };

  if (loading) {
    return (
      <div className="member-selector">
        <label className="member-selector-label">
          Select Members:
          <span className="tooltip-icon">ⓘ
            <span className="tooltip-text">
              Select members to automatically populate their public keys
            </span>
          </span>
        </label>
        <div className="loading-members">Loading available members...</div>
      </div>
    );
  }

  if (error) {
    return (
      <div className="member-selector">
        <label className="member-selector-label">
          Select Members:
          <span className="tooltip-icon">ⓘ
            <span className="tooltip-text">
              Select members to automatically populate their public keys
            </span>
          </span>
        </label>
        <div className="error-message">
          <span className="error-text">{error}</span>
          <button onClick={fetchMembers} className="retry-button">Retry</button>
        </div>
      </div>
    );
  }

  return (
    <div className="member-selector">
      <label className="member-selector-label">
        Select Members:
        <span className="tooltip-icon">ⓘ
          <span className="tooltip-text">
            Select members to automatically populate their public keys. 
            You can select multiple members.
          </span>
        </span>
      </label>
      
      {/* Available Members List */}
      <div className="available-members">
        <h4>Available Members ({availableMembers.length})</h4>
        <div className="members-grid">
          {availableMembers.map((member) => {
            const isSelected = selectedMembers.some(selected => selected.public_key === member.public_key);
            return (
              <div 
                key={member.public_key}
                className={`member-card ${isSelected ? 'selected' : ''}`}
                onClick={() => !disabled && handleMemberToggle(member)}
              >
                <div className="member-info">
                  <div className="member-name">{member.name}</div>
                  <div className="member-type">{member.type}</div>
                  <div className="member-pubkey">{member.public_key.substring(0, 16)}...</div>
                </div>
                <div className="member-checkbox">
                  {isSelected ? '✓' : '○'}
                </div>
              </div>
            );
          })}
        </div>
      </div>


      {/* Refresh Button */}
      <div className="member-selector-actions">
        <button 
          onClick={fetchMembers} 
          className="refresh-members-button"
          disabled={loading}
          title="Refresh the list of available members"
        >
          {loading ? 'Refreshing...' : '🔄 Refresh Members'}
        </button>
      </div>
    </div>
  );
}

export default MemberSelector;
