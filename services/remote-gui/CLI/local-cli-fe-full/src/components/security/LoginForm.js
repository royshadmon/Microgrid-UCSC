import React, { useState } from 'react';
import { login } from '../../services/security_api';
import '../../styles/security/LoginForm.css';

function LoginForm({ onLoginSuccess }) {
  const [nodeAddress, setNodeAddress] = useState('');
  const [pubkey, setPubkey] = useState('');
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState('');

  const handleSubmit = async (e) => {
    e.preventDefault();
    setIsLoading(true);
    setError('');

    const result = await login(nodeAddress, pubkey);
    
    if (result.success) {
      onLoginSuccess({
        node: nodeAddress,
        pubkey: pubkey,
        memberPolicy: result.data.member_policy
      });
    } else {
      setError(result.error);
    }
    
    setIsLoading(false);
  };

  return (
    <div className="login-form">
      <div className="login-container">
        <h2>AnyLog Policy Maker Login</h2>
        <p className="login-subtitle">Enter your node address and public key to access member policies</p>
        
        <form onSubmit={handleSubmit}>
          <div className="form-group">
            <label htmlFor="nodeAddress">Node Address (IP:Port)</label>
            <input
              type="text"
              id="nodeAddress"
              value={nodeAddress}
              onChange={(e) => setNodeAddress(e.target.value)}
              placeholder="e.g. 192.168.1.100:7848"
              required
            />
          </div>
          
          <div className="form-group">
            <label htmlFor="pubkey">Public Key</label>
            <input
              type="text"
              id="pubkey"
              value={pubkey}
              onChange={(e) => setPubkey(e.target.value)}
              placeholder="Enter your public key"
              required
            />
          </div>
          
          {error && (
            <div className="error-message">
              {error}
            </div>
          )}
          
          <button 
            type="submit" 
            className="login-button"
            disabled={isLoading}
          >
            {isLoading ? 'Authenticating...' : 'Login'}
          </button>
        </form>
      </div>
    </div>
  );
}

export default LoginForm; 