import React from 'react';
import '../../styles/security/SSLConfig.css';  // Optional CSS for styling

function SSLConfig({ sslEnabled, setSSLEnabled, sslFiles, setSSLFiles }) {
  const handleFileChange = (key, file) => {
    setSSLFiles(prev => ({ ...prev, [key]: file }));
  };

  return (
    <div className="ssl-config">
      <label>
        <input
          type="checkbox"
          checked={sslEnabled}
          onChange={() => setSSLEnabled(!sslEnabled)}
        />
        SSL Enabled
      </label>

      {sslEnabled && (
        <div className="ssl-files">
          <div>
            <label>Private Key:</label>
            <input type="file" onChange={e => handleFileChange("private_key", e.target.files[0])} />
          </div>
          <div>
            <label>Public Key:</label>
            <input type="file" onChange={e => handleFileChange("public_key", e.target.files[0])} />
          </div>
          <div>
            <label>CA File:</label>
            <input type="file" onChange={e => handleFileChange("ca_file", e.target.files[0])} />
          </div>
        </div>
      )}
    </div>
  );
}

export default SSLConfig;
