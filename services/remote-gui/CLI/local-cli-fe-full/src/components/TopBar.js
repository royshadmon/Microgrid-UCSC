// src/components/TopBar.js
import React from 'react';
import '../styles/TopBar.css';
import logo from '../assets/logo.png';
import NodePicker from './NodePicker.js';
import { NavLink } from 'react-router-dom';


const TopBar = ({ nodes, selectedNode, onAddNode, onSelectNode, restoredFromStorage, onClearStoredData }) => {
  return (
    <header className="topbar">
      <div className="topbar-left">
        <img src={logo} alt="App Logo" className="logo" />
        <NodePicker 
          nodes={nodes} 
          selectedNode={selectedNode} 
          onAddNode={onAddNode} 
          onSelectNode={onSelectNode} 
        />
      </div>
      <div className="topbar-right">
        {restoredFromStorage && (
          <div className="restoration-message">
            <span className="restoration-icon">🔄</span>
            <span className="restoration-text">Data restored from previous session</span>
          </div>
        )}
        {onClearStoredData && (
          <button 
            onClick={onClearStoredData}
            className="clear-data-btn"
            title="Clear all stored data"
          >
            🗑️ Clear Browser Data
          </button>
        )}
        {/* <button className="profile-btn">User Profile</button> */}
        {/* <nav className="profile-btn">
              <NavLink to="userprofile" className={({ isActive }) => isActive ? 'active' : ''}>User Profile</NavLink>
        </nav> */}
      </div>
    </header>
  );
};


export default TopBar;
