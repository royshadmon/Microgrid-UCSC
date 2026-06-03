// src/components/StreamingPlayer.js
import React, { useState, useEffect, useRef } from 'react';
import '../styles/StreamingPlayer.css';

const StreamingPlayer = ({ videos = [], autoPlay = true, loop = true }) => {
  const [currentVideoIndex, setCurrentVideoIndex] = useState(0);
  const [isPlaying, setIsPlaying] = useState(autoPlay);
  const [isMuted, setIsMuted] = useState(false);
  const [volume, setVolume] = useState(1);
  const [playbackRate, setPlaybackRate] = useState(1);
  const [showControls, setShowControls] = useState(true);
  const [progress, setProgress] = useState(0);
  const [duration, setDuration] = useState(0);
  const [currentTime, setCurrentTime] = useState(0);
  
  const videoRef = useRef(null);
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
    const video = videoRef.current;
    if (!video) return;

    const handleEnded = () => {
      if (videoFiles.length > 1 && loop) {
        setCurrentVideoIndex(prev => (prev + 1) % videoFiles.length);
      }
    };

    video.addEventListener('ended', handleEnded);
    
    return () => {
      video.removeEventListener('ended', handleEnded);
    };
  }, [videoFiles.length, loop, currentVideoIndex]);

  // Handle video events
  useEffect(() => {
    const video = videoRef.current;
    if (!video) return;

    const handleLoadedMetadata = () => {
      setDuration(video.duration);
    };

    const handleTimeUpdate = () => {
      setCurrentTime(video.currentTime);
      setProgress((video.currentTime / video.duration) * 100);
    };

    const handlePlay = () => setIsPlaying(true);
    const handlePause = () => setIsPlaying(false);

    video.addEventListener('loadedmetadata', handleLoadedMetadata);
    video.addEventListener('timeupdate', handleTimeUpdate);
    video.addEventListener('play', handlePlay);
    video.addEventListener('pause', handlePause);

    return () => {
      video.removeEventListener('loadedmetadata', handleLoadedMetadata);
      video.removeEventListener('timeupdate', handleTimeUpdate);
      video.removeEventListener('play', handlePlay);
      video.removeEventListener('pause', handlePause);
    };
  }, [currentVideoIndex, videoFiles.length, loop]);

  // Auto-hide controls
  useEffect(() => {
    if (showControls) {
      if (controlsTimeoutRef.current) {
        clearTimeout(controlsTimeoutRef.current);
      }
      controlsTimeoutRef.current = setTimeout(() => {
        setShowControls(false);
      }, 3000);
    }

    return () => {
      if (controlsTimeoutRef.current) {
        clearTimeout(controlsTimeoutRef.current);
      }
    };
  }, [showControls]);

  const togglePlayPause = () => {
    const video = videoRef.current;
    if (video) {
      if (video.paused) {
        video.play();
      } else {
        video.pause();
      }
    }
  };

  const handleProgressClick = (e) => {
    const video = videoRef.current;
    const progressBar = progressRef.current;
    if (video && progressBar) {
      const rect = progressBar.getBoundingClientRect();
      const clickX = e.clientX - rect.left;
      const width = rect.width;
      const clickTime = (clickX / width) * video.duration;
      video.currentTime = clickTime;
    }
  };

  const toggleMute = () => {
    const video = videoRef.current;
    if (video) {
      video.muted = !video.muted;
      setIsMuted(video.muted);
    }
  };

  const handleVolumeChange = (e) => {
    const video = videoRef.current;
    const newVolume = parseFloat(e.target.value);
    if (video) {
      video.volume = newVolume;
      setVolume(newVolume);
      setIsMuted(newVolume === 0);
    }
  };

  const handlePlaybackRateChange = (e) => {
    const video = videoRef.current;
    const newRate = parseFloat(e.target.value);
    if (video) {
      video.playbackRate = newRate;
      setPlaybackRate(newRate);
    }
  };

  const goToNextVideo = () => {
    setCurrentVideoIndex(prev => (prev + 1) % videoFiles.length);
  };

  const goToPreviousVideo = () => {
    setCurrentVideoIndex(prev => (prev - 1 + videoFiles.length) % videoFiles.length);
  };

  const formatTime = (time) => {
    const minutes = Math.floor(time / 60);
    const seconds = Math.floor(time % 60);
    return `${minutes}:${seconds.toString().padStart(2, '0')}`;
  };

  const handleMouseMove = () => {
    setShowControls(true);
  };

  const handleMouseLeave = () => {
    setShowControls(false);
  };

  if (!currentVideo) {
    return (
      <div className="streaming-player-container">
        <div className="no-video-message">
          <h3>No videos available</h3>
          <p>Please select some video files to stream.</p>
        </div>
      </div>
    );
  }

  return (
    <div 
      className="streaming-player-container"
      onMouseMove={handleMouseMove}
      onMouseLeave={handleMouseLeave}
    >
      <div className="video-wrapper">
        <video
          ref={videoRef}
          src={currentVideo.streaming_url || currentVideo.url || currentVideo}
          className="streaming-video"
          autoPlay={autoPlay}
          muted={isMuted}
          loop={false} // We handle looping manually
        >
          Your browser does not support the video tag.
        </video>

        {showControls && (
          <div className="video-controls">
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

      {videoFiles.length > 1 && (
        <div className="playlist-info">
          <h4>Streaming Playlist ({videoFiles.length} videos)</h4>
          <div className="playlist-items">
            {videoFiles.map((video, index) => (
              <div
                key={index}
                className={`playlist-item ${index === currentVideoIndex ? 'active' : ''}`}
                onClick={() => setCurrentVideoIndex(index)}
              >
                <span className="playlist-number">{index + 1}</span>
                <span className="playlist-title">
                  {video.file || video.name || `Video ${index + 1}`}
                </span>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
};

export default StreamingPlayer;
