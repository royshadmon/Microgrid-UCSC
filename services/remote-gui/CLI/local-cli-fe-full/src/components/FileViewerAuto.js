// src/components/FileViewerAuto.jsx
import React from 'react';
import FileViewer from './FileViewer';

const EXT2MIME = {
  jpg:  'image/jpeg',
  jpeg: 'image/jpeg',
  png:  'image/png',
  gif:  'image/gif',
  mp4:  'video/mp4',
  webm: 'video/webm',
  mp3:  'audio/mpeg',
  wav:  'audio/wav',
  pdf:  'application/pdf',
  txt:  'text/plain',
  // …add more as you need
};

const FileViewerAuto = ({ src, mimeType, style }) => {
  let type = mimeType;
  if (!type) {
    const ext = src.split('.').pop().toLowerCase();
    type = EXT2MIME[ext] || 'application/octet-stream';
  }
  return <FileViewer src={src} mimeType={type} style={style} />;
};

export default FileViewerAuto;
