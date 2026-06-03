import React, { useState, useEffect } from 'react';
import { fetchAvailableSigningMembers } from '../../services/security_api';
import '../../styles/security/SignWithSelector.css';

function SignWithSelector({ node, currentUserPubkey, selectedMember, onMemberChange, disabled = false, refreshTrigger = 0 }) {
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
      console.error('Error fetching signing members:', err);
    } finally {
      setLoading(false);
    }
  };

  const handleMemberChange = (e) => {
    const memberName = e.target.value;
    onMemberChange(memberName);
  };

  if (loading) {
    return (
      <div className="sign-with-selector">
        <label className="sign-with-label">
          Sign With:
          <span className="tooltip-icon">ⓘ
            <span className="tooltip-text">
              Select which member's keys to use for signing this policy
            </span>
          </span>
        </label>
        <div className="loading-members">Loading available members...</div>
      </div>
    );
  }

  if (error) {
    return (
      <div className="sign-with-selector">
        <label className="sign-with-label">
          Sign With:
          <span className="tooltip-icon">ⓘ
            <span className="tooltip-text">
              Select which member's keys to use for signing this policy
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
    <div className="sign-with-selector">
      <label className="sign-with-label">
        Sign With:
        <span className="tooltip-icon">ⓘ
          <span className="tooltip-text">
            Select which member's keys to use for signing this policy. 
            You can only sign with members you have access to.
          </span>
        </span>
      </label>
      
      <select 
        value={selectedMember || ''} 
        onChange={handleMemberChange}
        disabled={disabled}
        className="sign-with-select"
        required
      >
        <option value="">-- Select Member to Sign With --</option>
        {availableMembers.map((member) => (
          <option key={member.name} value={member.name}>
            {member.name} ({member.type}) - {member.description || 'No description'}
          </option>
        ))}
      </select>
      
      {selectedMember && (
        <div className="selected-member-info">
          <span className="selected-member-label">Selected:</span>
          <span className="selected-member-name">{selectedMember}</span>
        </div>
      )}

      <div className="sign-with-actions">
        <button 
          onClick={fetchMembers} 
          className="refresh-members-button"
          disabled={loading}
          title="Refresh the list of available signing members"
        >
          {loading ? 'Refreshing...' : '🔄 Refresh Members'}
        </button>
      </div>
    </div>
  );
}

export default SignWithSelector;
