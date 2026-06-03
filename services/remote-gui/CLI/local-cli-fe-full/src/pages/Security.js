import React, { useState, useEffect } from 'react';
import PolicySelector from '../components/security/PolicySelector';
import DynamicPolicyForm from '../components/security/DynamicPolicyForm';
import SignWithSelector from '../components/security/SignWithSelector';
import { getPolicyTemplate, submitPolicy } from '../services/security_api';
import '../styles/security/PolicyGeneratorPage.css';

// Main page for generating and submitting policies
function PolicyGeneratorPage({ node }) {
  // State for the selected policy type
  const [policyType, setPolicyType] = useState('');
  // State for the current policy template (schema)
  const [formTemplate, setFormTemplate] = useState(null);
  // State for the form data (user input)
  const [formData, setFormData] = useState({});
  // State for the backend response after submitting a policy
  const [response, setResponse] = useState(null);
  // State for preview visibility
  const [showPreview, setShowPreview] = useState(true);
  // State for loading during submission
  const [isSubmitting, setIsSubmitting] = useState(false);
  // State to trigger refresh of dynamic data
  const [refreshTrigger, setRefreshTrigger] = useState(0);
  // State for signing member selection
  const [signingMember, setSigningMember] = useState('');

  // Fetch the policy template whenever the policy type changes
  useEffect(() => {
    if (!policyType) return;

    setFormTemplate(null);
    setFormData({});

    getPolicyTemplate(policyType).then((template) => {
      if (template) setFormTemplate(template);
    });
  }, [policyType]);

  // Handle form submission for creating a policy
  const handleSubmit = async () => {
    if (!node) {
      alert('Please select a node from the top bar before submitting a policy.');
      return;
    }

    // Check for missing required fields (excluding generated fields)
    const missingFields = formTemplate.fields
      .filter(f => f.required && f.type !== "generated")
      .filter(f => {
        const val = formData[f.name];
        return val === undefined || val === null || val === '';
      });

    if (missingFields.length > 0) {
      alert(`Please fill out all required fields: ${missingFields.map(f => f.name).join(", ")}`);
      return;
    }

    // Check if signing member is selected (only if template requires signature and is not a member policy)
    if (formTemplate.requires_signature && policyType !== "member_policy" && !signingMember) {
      alert('Please select a member to sign the policy with');
      return;
    }

    // Set loading state and clear previous response
    setIsSubmitting(true);
    setResponse(null);

    try {
      // Submit the policy to the backend
      console.log('Submitting policy to backend:', formData);
      console.log('Signing with member:', signingMember);
      
      // Only pass signing member if template requires signature and is not a member policy
      const signingMemberToUse = (formTemplate.requires_signature && policyType !== "member_policy") ? signingMember : null;
      const result = await submitPolicy(node, policyType, formData, null, signingMemberToUse);
      console.log('Submit result:', result);

      if (result.success) {
        // Show the last policy in the response (if multiple)
        setResponse({ status: 'success', policy: result.data[result.data.length - 1] });
        // Trigger refresh of dynamic data
        setRefreshTrigger(prev => prev + 1);
      } else {
        setResponse({ status: 'error', message: result.error });
      }
    } catch (error) {
      console.error('Error submitting policy:', error);
      setResponse({ status: 'error', message: 'An unexpected error occurred while submitting the policy.' });
    } finally {
      setIsSubmitting(false);
    }
  };

  // Main render
  return (
    <div className="policy-generator">
      <div className="page-header">
        <h2>Security Policy Generator</h2>
        {node ? (
          <p className="node-info">Connected to: <strong>{node}</strong></p>
        ) : (
          <p className="node-warning">⚠️ Please select a node from the top bar to continue</p>
        )}
      </div>

      {/* Policy type selector */}
      {node && (
        <PolicySelector 
          value={policyType} 
          onChange={setPolicyType} 
          allowedPolicyTypes={['*']} // Allow all policy types
        />
      )}

      {/* Preview toggle button */}
      {node && formTemplate && (
        <div className="form-controls">
          <div className="preview-toggle">
            <button 
              onClick={() => setShowPreview(!showPreview)}
              className="preview-toggle-button"
            >
              {showPreview ? 'Hide Preview' : 'Show Preview'}
            </button>
          </div>
        </div>
      )}

      {/* Dynamic form for the selected policy template */}
      {node && formTemplate && (
        <DynamicPolicyForm
          template={formTemplate}
          formData={formData}
          node={node}
          onChange={setFormData}
          allowedPolicyFields={null} // Allow all fields
          showPreview={showPreview}
          refreshTrigger={refreshTrigger}
          currentUserPubkey={null} // No authentication
        />
      )}

      {/* Sign With Selector - only show if template requires signature and is not a member policy */}
      {node && formTemplate && formTemplate.requires_signature && policyType !== "member_policy" && (
        <SignWithSelector
          node={node}
          currentUserPubkey={null} // No authentication - will fetch all members
          selectedMember={signingMember}
          onMemberChange={setSigningMember}
          disabled={isSubmitting}
          refreshTrigger={refreshTrigger}
        />
      )}

      {/* Special message for member policies */}
      {node && formTemplate && policyType === "member_policy" && (
        <div className="member-policy-signing-info">
          <div className="info-box">
            <h4>📝 Member Policy Signing</h4>
            <p>
              <strong>Note:</strong> When creating a new member policy, the new member will automatically 
              sign the policy themselves after their cryptographic keys are created. No additional 
              signing member selection is needed.
            </p>
          </div>
        </div>
      )}

      {/* Submit button for the form */}
      {node && formTemplate && (
        <button 
          onClick={handleSubmit}
          disabled={isSubmitting || !node}
          className="submit-button"
        >
          {isSubmitting ? 'Submitting...' : 'Submit Policy'}
        </button>
      )}



      {/* Loading overlay during submission */}
      {isSubmitting && (
        <div className="loading-overlay">
          <div className="loading-content">
            <div className="loading-spinner"></div>
            <p>Submitting policy...</p>
          </div>
        </div>
      )}

      {/* Show backend response after submission */}
      {response && (
        <div className="response">
          <h4>Response:</h4>
          <pre>{JSON.stringify(response, null, 2)}</pre>
        </div>
      )}

      {/* Assignment Manager Section
      {userPermissions && (
        <div className="assignment-manager-section">
          <div className="section-header">
            <h3>Assignment Policy Management</h3>
            <button 
              onClick={() => setShowAssignmentManager(!showAssignmentManager)}
              className="toggle-button"
            >
              {showAssignmentManager ? 'Hide' : 'Show'} Assignment Manager
            </button>
          </div>
          
          {showAssignmentManager && (
            <AssignmentManager node={node} />
          )}
        </div>
      )} */}
    </div>
  );
}


export default PolicyGeneratorPage;
