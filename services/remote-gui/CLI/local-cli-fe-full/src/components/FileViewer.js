// src/components/FileViewer.jsx
import React from 'react';

const FileViewer = ({ src, mimeType, style = {} }) => {
  // Derive a “type” (image, video, pdf, audio, text, other) from the mimeType
  const mainType = mimeType.split('/')[0];
  // const subtype  = mimeType.split('/')[1] || '';

  const commonStyles = {
    maxWidth:  '100%',
    maxHeight: '100%',
    ...style
  };

  if (mainType === 'image') {
    return <img src={src} style={commonStyles} alt="" />;
  }

  if (mainType === 'video') {
    return (
      <video controls style={commonStyles}>
        <source src={src} type={mimeType} />
        Your browser does not support video.
      </video>
    );
  }

  if (mainType === 'audio') {
    return (
      <audio controls style={commonStyles}>
        <source src={src} type={mimeType} />
        Your browser does not support audio.
      </audio>
    );
  }

  // PDF (and any application/pdf subtype)
  if (mimeType === 'application/pdf') {
    return (
      <object
        data={src}
        type="application/pdf"
        style={commonStyles}
        aria-label="PDF viewer"
      >
        <p>
          Your browser doesn’t support embedded PDFs. <br/>
          <a href={src} download>Download PDF</a>
        </p>
      </object>
    );
  }

  // Plain text / code
  if (mainType === 'text') {
    return (
      <iframe
        src={src}
        style={commonStyles}
        title="text-file"
      />
    );
  }

  // Fallback for anything else (Office docs, archives, etc.)
  return (
    <div style={{ padding: 20 }}>
      <p>
        Can’t preview this file type ({mimeType}).<br/>
        <a href={src} download>Download</a>
      </p>
    </div>
  );
};

export default FileViewer;
