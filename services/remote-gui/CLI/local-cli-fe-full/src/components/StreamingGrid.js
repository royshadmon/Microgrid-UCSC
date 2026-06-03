// src/components/StreamingGrid.js
import React, { useState, useEffect, useRef } from 'react';
import '../styles/StreamingGrid.css';

const StreamingGrid = ({ videos = [], autoPlay = true, showControls = true }) => {
  const [currentVideoIndex, setCurrentVideoIndex] = useState(0);
  const [isPlaying, setIsPlaying] = useState(autoPlay);
  const [isMuted, setIsMuted] = useState(false);
  const [volume, setVolume] = useState(1);
  const [playbackRate, setPlaybackRate] = useState(1);
  const [showGridControls, setShowGridControls] = useState(true);
  const [progress, setProgress] = useState(0);
  const [duration, setDuration] = useState(0);
  const [currentTime, setCurrentTime] = useState(0);
  
  const videoRefs = useRef([]);
  const progressRef = useRef(null);
  const intervalRef = useRef(null);
  const controlsTimeoutRef = useRef(null);

  // Filter videos to only include video files
  const videoFiles = videos.filter(video => {
    const url = video.streaming_url || video.url || video;
    return url && (url.includes('.mp4') || url.includes('.webm') || url.includes('.ogg') || url.includes('video'));
  });

  const currentVideo = videoFiles[currentVideoIndex];

  // Auto-advance to next video when current video ends
  useEffect(() => {
    const currentVideoRef = videoRefs.current[currentVideoIndex];
    if (!currentVideoRef) return;

    const handleEnded = () => {
      if (videoFiles.length > 1) {
        setCurrentVideoIndex(prev => (prev + 1) % videoFiles.length);
      }
    };

    currentVideoRef.addEventListener('ended', handleEnded);
    
    return () => {
      currentVideoRef.removeEventListener('ended', handleEnded);
    };
  }, [videoFiles.length, currentVideoIndex]);

  // Handle video events for the current video
  useEffect(() => {
    const currentVideoRef = videoRefs.current[currentVideoIndex];
    if (!currentVideoRef) return;

    const handleLoadedMetadata = () => {
      setDuration(currentVideoRef.duration);
    };

    const handleTimeUpdate = () => {
      setCurrentTime(currentVideoRef.currentTime);
      setProgress((currentVideoRef.currentTime / currentVideoRef.duration) * 100);
    };

    const handleEnded = () => {
      if (videoFiles.length > 1) {
        setCurrentVideoIndex(prev => (prev + 1) % videoFiles.length);
      }
    };

    const handlePlay = () => setIsPlaying(true);
    const handlePause = () => setIsPlaying(false);

    currentVideoRef.addEventListener('loadedmetadata', handleLoadedMetadata);
    currentVideoRef.addEventListener('timeupdate', handleTimeUpdate);
    currentVideoRef.addEventListener('ended', handleEnded);
    currentVideoRef.addEventListener('play', handlePlay);
    currentVideoRef.addEventListener('pause', handlePause);

    return () => {
      currentVideoRef.removeEventListener('loadedmetadata', handleLoadedMetadata);
      currentVideoRef.removeEventListener('timeupdate', handleTimeUpdate);
      currentVideoRef.removeEventListener('ended', handleEnded);
      currentVideoRef.removeEventListener('play', handlePlay);
      currentVideoRef.removeEventListener('pause', handlePause);
    };
  }, [currentVideoIndex, videoFiles.length]);

  // Auto-hide controls
  useEffect(() => {
    if (showGridControls) {
      if (controlsTimeoutRef.current) {
        clearTimeout(controlsTimeoutRef.current);
      }
      controlsTimeoutRef.current = setTimeout(() => {
        setShowGridControls(false);
      }, 3000);
    }

    return () => {
      if (controlsTimeoutRef.current) {
        clearTimeout(controlsTimeoutRef.current);
      }
    };
  }, [showGridControls]);

  const togglePlayPause = () => {
    const currentVideoRef = videoRefs.current[currentVideoIndex];
    if (currentVideoRef) {
      if (currentVideoRef.paused) {
        currentVideoRef.play();
      } else {
        currentVideoRef.pause();
      }
    }
  };

  const handleProgressClick = (e) => {
    const currentVideoRef = videoRefs.current[currentVideoIndex];
    const progressBar = progressRef.current;
    if (currentVideoRef && progressBar) {
      const rect = progressBar.getBoundingClientRect();
      const clickX = e.clientX - rect.left;
      const width = rect.width;
      const clickTime = (clickX / width) * currentVideoRef.duration;
      currentVideoRef.currentTime = clickTime;
    }
  };

  const toggleMute = () => {
    videoRefs.current.forEach(videoRef => {
      if (videoRef) {
        videoRef.muted = !isMuted;
      }
    });
    setIsMuted(!isMuted);
  };

  const handleVolumeChange = (e) => {
    const newVolume = parseFloat(e.target.value);
    videoRefs.current.forEach(videoRef => {
      if (videoRef) {
        videoRef.volume = newVolume;
      }
    });
    setVolume(newVolume);
    setIsMuted(newVolume === 0);
  };

  const handlePlaybackRateChange = (e) => {
    const newRate = parseFloat(e.target.value);
    videoRefs.current.forEach(videoRef => {
      if (videoRef) {
        videoRef.playbackRate = newRate;
      }
    });
    setPlaybackRate(newRate);
  };

  const goToNextVideo = () => {
    setCurrentVideoIndex(prev => (prev + 1) % videoFiles.length);
  };

  const goToPreviousVideo = () => {
    setCurrentVideoIndex(prev => (prev - 1 + videoFiles.length) % videoFiles.length);
  };

  const selectVideo = (index) => {
    setCurrentVideoIndex(index);
  };

  const formatTime = (time) => {
    const minutes = Math.floor(time / 60);
    const seconds = Math.floor(time % 60);
    return `${minutes}:${seconds.toString().padStart(2, '0')}`;
  };

  const handleMouseMove = () => {
    setShowGridControls(true);
  };

  const handleMouseLeave = () => {
    setShowGridControls(false);
  };

  if (!videoFiles.length) {
    return (
      <div className="streaming-grid-container">
        <div className="no-video-message">
          <h3>No videos available</h3>
          <p>Please select some video files to stream.</p>
        </div>
      </div>
    );
  }

  return (
    <div 
      className="streaming-grid-container"
      onMouseMove={handleMouseMove}
      onMouseLeave={handleMouseLeave}
    >
      <div className="grid-header">
        <h3>Streaming Grid ({videoFiles.length} videos)</h3>
        <p>Videos displayed side-by-side. Current video highlighted.</p>
      </div>

      <div className="video-grid">
        {videoFiles.map((video, index) => (
          <div 
            key={index}
            className={`video-item ${index === currentVideoIndex ? 'active' : ''}`}
            onClick={() => selectVideo(index)}
          >
            <div className="video-wrapper">
              <video
                ref={el => videoRefs.current[index] = el}
                src={video.streaming_url || video.url || video}
                className="grid-video"
                muted={isMuted}
                loop={false}
                preload="metadata"
              >
                Your browser does not support the video tag.
              </video>
              
              <div className="video-overlay">
                <div className="video-info">
                  <span className="video-number">{index + 1}</span>
                  <span className="video-title">
                    {video.file || video.name || `Video ${index + 1}`}
                  </span>
                </div>
                
                {index === currentVideoIndex && (
                  <div className="current-indicator">
                    <span>▶️ Now Playing</span>
                  </div>
                )}
              </div>
            </div>
          </div>
        ))}
      </div>

      {showGridControls && showControls && (
        <div className="grid-controls">
          <div className="progress-container">
            <div 
              ref={progressRef}
              className="progress-bar"
              onClick={handleProgressClick}
            >
              <div 
                className="progress-fill"
                style={{ width: `${progress}%` }}
              />
            </div>
          </div>

          <div className="controls-row">
            <div className="controls-left">
              <button 
                className="control-button"
                onClick={togglePlayPause}
                title={isPlaying ? 'Pause' : 'Play'}
              >
                {isPlaying ? '⏸️' : '▶️'}
              </button>

              <button 
                className="control-button"
                onClick={goToPreviousVideo}
                title="Previous Video"
                disabled={videoFiles.length <= 1}
              >
                ⏮️
              </button>

              <button 
                className="control-button"
                onClick={goToNextVideo}
                title="Next Video"
                disabled={videoFiles.length <= 1}
              >
                ⏭️
              </button>

              <button 
                className="control-button"
                onClick={toggleMute}
                title={isMuted ? 'Unmute' : 'Mute'}
              >
                {isMuted ? '🔇' : '🔊'}
              </button>

              <input
                type="range"
                min="0"
                max="1"
                step="0.1"
                value={volume}
                onChange={handleVolumeChange}
                className="volume-slider"
                title="Volume"
              />
            </div>

            <div className="controls-center">
              <span className="time-display">
                {formatTime(currentTime)} / {formatTime(duration)}
              </span>
            </div>

            <div className="controls-right">
              <select
                value={playbackRate}
                onChange={handlePlaybackRateChange}
                className="playback-rate-select"
                title="Playback Speed"
              >
                <option value="0.5">0.5x</option>
                <option value="0.75">0.75x</option>
                <option value="1">1x</option>
                <option value="1.25">1.25x</option>
                <option value="1.5">1.5x</option>
                <option value="2">2x</option>
              </select>

              <span className="video-counter">
                {currentVideoIndex + 1} / {videoFiles.length}
              </span>
            </div>
          </div>
        </div>
      )}
    </div>
  );
};

export default StreamingGrid;
