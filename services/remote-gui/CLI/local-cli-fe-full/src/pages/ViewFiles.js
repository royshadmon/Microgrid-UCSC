// src/pages/ViewFiles.jsx
import React, {useState} from 'react';
// import { useParams }       from 'react-router-dom';
import { useLocation } from 'react-router-dom';
import FileViewerAuto      from '../components/FileViewerAuto';
import StreamingPlayer     from '../components/StreamingPlayer';
import StreamingGrid       from '../components/StreamingGrid';
import '../styles/ViewFiles.css';  // <-- import the new stylesheet

const BACKEND_URL = window._env_?.REACT_APP_API_URL || "http://localhost:8000";

const ViewFiles = () => {

  console.log("backend url is", BACKEND_URL);

  // const { fileId } = useParams();
  const [expandedFile, setExpandedFile] = useState(null);
  const [streamingMode, setStreamingMode] = useState(false);
  const [gridMode, setGridMode] = useState(false);

  const location = useLocation();
  const { blobs, isStreaming, nodeInfo } = location.state || { }; // Use optional chaining to avoid errors if state is undefined
  console.log('ViewFiles component rendered with files state:', blobs);
  console.log('Blobs type:', typeof blobs);
  console.log('Blobs is array:', Array.isArray(blobs));
  console.log('Blobs length:', blobs ? blobs.length : 'N/A');
  console.log('Is streaming:', isStreaming);
  console.log('Node info:', nodeInfo);

  const files = Array.isArray(blobs)
    ? blobs.map(obj => `${obj.dbms_name}.${obj.video_table || obj.table_name}.${obj.file}`)
    : [];
  console.log('Files:', files);

  // List of your filenames in public/static/
  const dummyFiles = [
    'flower.jpg',
    // …add as many as you like
  ];

  const finalFiles = files || dummyFiles;

  // Function to render blob content (streaming vs regular)
  const renderBlobContent = (blob, idx) => {
    if (isStreaming) {
      // For streaming, use the constructed URL
      return (
        <div
          key={idx}
          className="streaming-card"
        >
          <h4 className="streaming-header">📡 {blob.file}</h4>
          <div className="streaming-content">
            <div className="streaming-info">
              <p><strong>DBMS:</strong> {blob.dbms}</p>
              <p><strong>Table:</strong> {blob.table}</p>
              <p><strong>ID:</strong> {blob.id}</p>
              <p><strong>Node:</strong> {blob.ip}:{blob.port}</p>
            </div>
            <div className="streaming-url-section">
              <p><strong>Streaming URL:</strong></p>
              <code className="streaming-url">{blob.streaming_url}</code>
            </div>
            <div className="streaming-actions">
              <button 
                onClick={() => window.open(blob.streaming_url, '_blank')}
                className="stream-open-button"
              >
                🎬 Open Stream
              </button>
              <button 
                onClick={() => {
                  navigator.clipboard.writeText(blob.streaming_url);
                  alert('Streaming URL copied to clipboard!');
                }}
                className="stream-copy-button"
              >
                📋 Copy URL
              </button>
            </div>
          </div>
        </div>
      );
    } else {
      // Regular blob handling (existing code)
      const name = `${blob.dbms_name}.${blob.video_table || blob.table_name}.${blob.file}`;
      const url = `${BACKEND_URL}/static/${name}`;
      console.log("url", url);
      return (
        <div
          key={idx}
          className="view-files-card"
          onClick={() => setExpandedFile(name)}
        >
          <h4 className="view-files-header">{name}</h4>
          <div className="view-files-wrapper">
            <FileViewerAuto src={url} />
          </div>
        </div>
      );
    }
  };

  // Filter videos from blobs for streaming
  const videoBlobs = Array.isArray(blobs) ? blobs.filter(blob => {
    const url = blob.streaming_url || '';
    return url && (url.includes('.mp4') || url.includes('.webm') || url.includes('.ogg') || url.includes('video'));
  }) : [];

  return (
    <>
      {isStreaming && (
        <div className="streaming-notice">
          📡 <strong>Streaming Mode</strong> - Click "Open Stream" to view files directly from the node
          {videoBlobs.length > 0 && (
            <div className="streaming-mode-toggle">
              <div className="toggle-buttons">
                <button 
                  className={`toggle-button ${!streamingMode && !gridMode ? 'active' : ''}`}
                  onClick={() => {
                    setStreamingMode(false);
                    setGridMode(false);
                  }}
                >
                  📋 List View
                </button>
                <button 
                  className={`toggle-button ${streamingMode ? 'active' : ''}`}
                  onClick={() => {
                    setStreamingMode(true);
                    setGridMode(false);
                  }}
                >
                  🎬 Single Player
                </button>
                <button 
                  className={`toggle-button ${gridMode ? 'active' : ''}`}
                  onClick={() => {
                    setStreamingMode(false);
                    setGridMode(true);
                  }}
                >
                  📺 Grid View
                </button>
              </div>
            </div>
          )}
        </div>
      )}

      {isStreaming && streamingMode && videoBlobs.length > 0 ? (
        <div className="embedded-streaming-container">
          <StreamingPlayer 
            videos={videoBlobs}
            autoPlay={true}
            loop={true}
          />
        </div>
      ) : isStreaming && gridMode && videoBlobs.length > 0 ? (
        <div className="embedded-streaming-container">
          <StreamingGrid 
            videos={videoBlobs}
            autoPlay={true}
            showControls={true}
          />
        </div>
      ) : (
        <div className={isStreaming ? "streaming-grid" : "view-files-grid"}>
        {isStreaming ? (
          // Render streaming blobs
          Array.isArray(blobs) && blobs.length > 0 ? (
            blobs.map((blob, idx) => renderBlobContent(blob, idx))
          ) : (
            <div className="no-streaming-data">
              <p>No streaming data available.</p>
              <p>Please go back and select some blobs first.</p>
            </div>
          )
        ) : (
          // Render regular files
          Array.isArray(finalFiles) && finalFiles.length > 0 ? (
            finalFiles.map((name, idx) => {
              const url = `${BACKEND_URL}/static/${name}`;
              console.log("url", url);
              return (
                <div
                  key={idx}
                  className="view-files-card"
                  onClick={() => setExpandedFile(name)}
                >
                  <h4 className="view-files-header">{name}</h4>
                  <div className="view-files-wrapper">
                    <FileViewerAuto src={url} />
                  </div>
                </div>
              );
            })
          ) : (
            <div className="no-files-data">
              <p>No files available.</p>
              <p>Please go back and select some blobs first.</p>
            </div>
          )
        )}
        </div>
      )}

      {expandedFile && !isStreaming && (
        <div className="modal-overlay" onClick={() => setExpandedFile(null)}>
          <div
            className="modal-content"
            onClick={e => e.stopPropagation()}
          >
            <button
              className="modal-close"
              onClick={() => setExpandedFile(null)}
            >
              ×
            </button>
            <FileViewerAuto
              src={`${BACKEND_URL}/static/${expandedFile}`}
              style={{ maxWidth: '90vw', maxHeight: '90vh' }}
            />
          </div>
        </div>
      )}
    </>
  );
};

export default ViewFiles;
