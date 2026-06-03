import React, { useState, useEffect } from 'react';
import { getGrafanaUrl } from './grafana_api';

// Plugin metadata - used by the plugin loader
export const pluginMetadata = {
  name: 'Grafana',
  icon: null
};

const GrafanaPage = ({ node }) => {
  const [grafanaUrl, setGrafanaUrl] = useState('');
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [iframeError, setIframeError] = useState(false);

  useEffect(() => {
    const loadGrafanaUrl = async () => {
      try {
        setLoading(true);
        const url = await getGrafanaUrl();
        setGrafanaUrl(url);
        setError(null);
        setIframeError(false);
      } catch (err) {
        console.error('Failed to load Grafana URL:', err);
        setError('Failed to load Grafana URL. Please check backend configuration.');
        // Fallback to default if API fails
        setGrafanaUrl('https://grafana.com/');
      } finally {
        setLoading(false);
      }
    };

    loadGrafanaUrl();
  }, []);

  // Detect iframe loading issues after a timeout
  useEffect(() => {
    if (!grafanaUrl || loading) return;

    const timeout = setTimeout(() => {
      // Check if iframe might be blocked
      // This is a fallback - the onError handler should catch it first
      const iframe = document.querySelector('iframe[title="Grafana Dashboard"]');
      if (iframe) {
        try {
          // Try to access iframe - if blocked, this will throw
          const iframeWindow = iframe.contentWindow;
          if (!iframeWindow) {
            setIframeError(true);
          }
        } catch (e) {
          // Cross-origin or blocked - this is expected for external URLs
          // Don't set error here as cross-origin is normal
        }
      }
    }, 3000); // Wait 3 seconds to see if iframe loads

    return () => clearTimeout(timeout);
  }, [grafanaUrl, loading]);

  const handleOpenGrafana = () => {
    if (grafanaUrl) {
      window.open(grafanaUrl, '_blank');
    }
  };

  if (loading) {
    return (
      <div style={{ 
        display: 'flex', 
        justifyContent: 'center', 
        alignItems: 'center', 
        height: '100vh',
        padding: '20px'
      }}>
        <p>Loading Grafana configuration...</p>
      </div>
    );
  }

  return (
    <div style={{ 
      width: '100%',
      height: '100vh',
      display: 'flex',
      flexDirection: 'column',
      padding: '0',
      overflow: 'hidden',
      backgroundColor: '#f8f9fa'
    }}>
      {/* Header with title and button */}
      <div style={{ 
        position: 'relative',
        padding: '20px',
        backgroundColor: '#ffffff',
        borderBottom: '2px solid #007bff',
        display: 'flex',
        justifyContent: 'space-between',
        alignItems: 'center',
        flexShrink: 0,
        zIndex: 100,
        boxShadow: '0 2px 4px rgba(0, 0, 0, 0.1)'
      }}>
        <h2 style={{ 
          margin: 0,
          color: '#333',
          fontSize: '24px',
          fontWeight: '600',
          borderBottom: '2px solid #007bff',
          paddingBottom: '10px',
          display: 'inline-block'
        }}>
          Grafana
        </h2>
        
        <button 
          onClick={handleOpenGrafana}
          style={{ 
            padding: '12px 24px', 
            fontSize: '14px',
            background: 'linear-gradient(135deg, #007bff, #0056b3)',
            color: 'white',
            border: 'none',
            borderRadius: '6px',
            cursor: 'pointer',
            fontWeight: '600',
            boxShadow: '0 2px 4px rgba(0, 0, 0, 0.1)',
            transition: 'all 0.3s ease',
            textTransform: 'uppercase',
            letterSpacing: '0.5px'
          }}
          onMouseOver={(e) => {
            e.currentTarget.style.background = 'linear-gradient(135deg, #0056b3, #004085)';
            e.currentTarget.style.transform = 'translateY(-2px)';
            e.currentTarget.style.boxShadow = '0 4px 12px rgba(0, 123, 255, 0.3)';
          }}
          onMouseOut={(e) => {
            e.currentTarget.style.background = 'linear-gradient(135deg, #007bff, #0056b3)';
            e.currentTarget.style.transform = 'translateY(0)';
            e.currentTarget.style.boxShadow = '0 2px 4px rgba(0, 0, 0, 0.1)';
          }}
        >
          Open in New Tab
        </button>
      </div>

      {error && (
        <div style={{ 
          padding: '15px 20px', 
          backgroundColor: '#f8d7da', 
          border: '1px solid #f5c6cb',
          borderRadius: '6px',
          margin: '20px',
          color: '#721c24',
          flexShrink: 0,
          fontWeight: '500'
        }}>
          <strong>Error:</strong> {error}
        </div>
      )}

      {iframeError && (
        <div style={{ 
          padding: '20px', 
          backgroundColor: '#fff3cd', 
          border: '1px solid #ffeaa7',
          borderRadius: '6px',
          margin: '20px',
          color: '#856404',
          flexShrink: 0
        }}>
          <strong>⚠️ Iframe Embedding Blocked:</strong>
          <p style={{ margin: '10px 0 0 0', fontSize: '14px' }}>
            Grafana is preventing this page from being embedded in an iframe for security reasons. 
            This is a common security setting. Please use the <strong>"Open in New Tab"</strong> button above to access Grafana.
          </p>
          <p style={{ margin: '10px 0 0 0', fontSize: '12px', fontStyle: 'italic' }}>
            To enable iframe embedding, configure Grafana's <code>allow_embedding</code> setting in your Grafana configuration file.
          </p>
        </div>
      )}

      {/* Centered Embedded Grafana iframe */}
      {grafanaUrl && (
        <div style={{ 
          flex: 1,
          width: '100%',
          display: 'flex',
          justifyContent: 'center',
          alignItems: 'center',
          padding: '20px',
          boxSizing: 'border-box',
          overflow: 'hidden'
        }}>
          <div style={{ 
            width: '100%',
            height: '100%',
            maxWidth: '1400px',
            backgroundColor: '#ffffff',
            border: '1px solid #dee2e6',
            borderRadius: '8px',
            overflow: 'hidden',
            boxShadow: '0 2px 4px rgba(0, 0, 0, 0.1)',
            position: 'relative'
          }}>
            {iframeError ? (
              <div style={{
                width: '100%',
                height: '100%',
                display: 'flex',
                flexDirection: 'column',
                justifyContent: 'center',
                alignItems: 'center',
                padding: '40px',
                backgroundColor: '#f8f9fa',
                textAlign: 'center'
              }}>
                <div style={{ fontSize: '48px', marginBottom: '20px' }}>🔒</div>
                <h3 style={{ color: '#495057', marginBottom: '10px' }}>Unable to Load Grafana</h3>
                <p style={{ color: '#6c757d', marginBottom: '20px' }}>
                  The Grafana server is blocking iframe embedding. Click the button above to open in a new tab.
                </p>
                <button 
                  onClick={handleOpenGrafana}
                  style={{ 
                    padding: '12px 24px', 
                    fontSize: '14px',
                    background: 'linear-gradient(135deg, #007bff, #0056b3)',
                    color: 'white',
                    border: 'none',
                    borderRadius: '6px',
                    cursor: 'pointer',
                    fontWeight: '600',
                    boxShadow: '0 2px 4px rgba(0, 0, 0, 0.1)',
                    transition: 'all 0.3s ease',
                    textTransform: 'uppercase',
                    letterSpacing: '0.5px'
                  }}
                  onMouseOver={(e) => {
                    e.currentTarget.style.background = 'linear-gradient(135deg, #0056b3, #004085)';
                    e.currentTarget.style.transform = 'translateY(-2px)';
                    e.currentTarget.style.boxShadow = '0 4px 12px rgba(0, 123, 255, 0.3)';
                  }}
                  onMouseOut={(e) => {
                    e.currentTarget.style.background = 'linear-gradient(135deg, #007bff, #0056b3)';
                    e.currentTarget.style.transform = 'translateY(0)';
                    e.currentTarget.style.boxShadow = '0 2px 4px rgba(0, 0, 0, 0.1)';
                  }}
                >
                  Open Grafana in New Tab
                </button>
              </div>
            ) : (
              <iframe
                src={grafanaUrl}
                style={{
                  width: '100%',
                  height: '100%',
                  border: 'none'
                }}
                title="Grafana Dashboard"
                allow="fullscreen"
                onError={() => {
                  setIframeError(true);
                }}
                onLoad={(e) => {
                  // Iframe loaded - clear any error state
                  setIframeError(false);
                }}
              />
            )}
          </div>
        </div>
      )}
    </div>
  );
};

export default GrafanaPage;
