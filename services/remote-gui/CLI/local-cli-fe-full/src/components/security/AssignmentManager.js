import React, { useState, useEffect } from 'react';
import { assignmentSummary, regenerateAssignments } from '../../services/security_api';
import '../../styles/security/AssignmentManager.css';

function AssignmentManager({ node }) {
  const [summary, setSummary] = useState(null);
  const [loading, setLoading] = useState(false);
  const [message, setMessage] = useState('');
  const [selectedSecurityGroup, setSelectedSecurityGroup] = useState('');
  const [securityGroups, setSecurityGroups] = useState([]);

  useEffect(() => {
    if (node) {
      loadSummary();
    }
  }, [node]);

  const loadSummary = async () => {
    if (!node) return;
    
    setLoading(true);
    try {
      const data = await assignmentSummary(node);
      setSummary(data);
      
      // Extract security groups from summary
      if (data.assignments_by_security_group) {
        setSecurityGroups(Object.keys(data.assignments_by_security_group));
      }
    } catch (error) {
      console.error('Error loading assignment summary:', error);
      setMessage('Error loading assignment summary');
    } finally {
      setLoading(false);
    }
  };

  const handleRegenerateAll = async () => {
    if (!node) return;
    
    setLoading(true);
    setMessage('');
    try {
      const response = await regenerateAssignments(node);
      setMessage(response.message || 'Successfully regenerated all assignments');
      await loadSummary(); // Reload summary
    } catch (error) {
      console.error('Error regenerating assignments:', error);
      setMessage('Error regenerating assignments');
    } finally {
      setLoading(false);
    }
  };

  const handleRegenerateSecurityGroup = async () => {
    if (!node || !selectedSecurityGroup) return;
    
    setLoading(true);
    setMessage('');
    try {
      const response = await regenerateAssignments(node, selectedSecurityGroup);
      setMessage(response.message || `Successfully regenerated assignments for ${selectedSecurityGroup}`);
      await loadSummary(); // Reload summary
    } catch (error) {
      console.error('Error regenerating assignments:', error);
      setMessage('Error regenerating assignments');
    } finally {
      setLoading(false);
    }
  };

  if (!node) {
    return <div className="assignment-manager">Please select a node to manage assignments.</div>;
  }

  return (
    <div className="assignment-manager">
      <h2>Assignment Policy Management</h2>
      
      <div className="assignment-controls">
        <div className="control-group">
          <h3>Regenerate Assignments</h3>
          <div className="button-group">
            <button 
              onClick={handleRegenerateAll}
              disabled={loading}
              className="btn btn-primary"
            >
              {loading ? 'Regenerating...' : 'Regenerate All Assignments'}
            </button>
          </div>
        </div>

        <div className="control-group">
          <h3>Regenerate by Security Group</h3>
          <div className="select-group">
            <select 
              value={selectedSecurityGroup}
              onChange={(e) => setSelectedSecurityGroup(e.target.value)}
              disabled={loading}
            >
              <option value="">Select Security Group</option>
              {securityGroups.map(group => (
                <option key={group} value={group}>{group}</option>
              ))}
            </select>
            <button 
              onClick={handleRegenerateSecurityGroup}
              disabled={loading || !selectedSecurityGroup}
              className="btn btn-secondary"
            >
              {loading ? 'Regenerating...' : 'Regenerate'}
            </button>
          </div>
        </div>

        <div className="control-group">
          <button 
            onClick={loadSummary}
            disabled={loading}
            className="btn btn-outline"
          >
            Refresh Summary
          </button>
        </div>
      </div>

      {message && (
        <div className={`message ${message.includes('Error') ? 'error' : 'success'}`}>
          {message}
        </div>
      )}

      {summary && (
        <div className="assignment-summary">
          <h3>Assignment Summary</h3>
          
          <div className="summary-stats">
            <div className="stat-card">
              <h4>Total Assignments</h4>
              <p>{summary.total_assignments || 0}</p>
            </div>
          </div>

          {summary.assignments_by_security_group && (
            <div className="summary-section">
              <h4>Assignments by Security Group</h4>
              <div className="summary-table">
                <table>
                  <thead>
                    <tr>
                      <th>Security Group</th>
                      <th>Assignment Count</th>
                    </tr>
                  </thead>
                  <tbody>
                    {Object.entries(summary.assignments_by_security_group).map(([group, count]) => (
                      <tr key={group}>
                        <td>{group}</td>
                        <td>{count}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          )}

          {summary.assignments_by_permission && (
            <div className="summary-section">
              <h4>Assignments by Permission</h4>
              <div className="summary-table">
                <table>
                  <thead>
                    <tr>
                      <th>Permission</th>
                      <th>Assignment Count</th>
                      <th>Total Members</th>
                    </tr>
                  </thead>
                  <tbody>
                    {Object.entries(summary.assignments_by_permission).map(([permission, data]) => (
                      <tr key={permission}>
                        <td>{permission}</td>
                        <td>{data.count}</td>
                        <td>{data.total_members}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          )}

          {summary.error && (
            <div className="error-message">
              Error: {summary.error}
            </div>
          )}
        </div>
      )}
    </div>
  );
}

export default AssignmentManager; 