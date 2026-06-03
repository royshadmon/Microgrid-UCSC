// src/components/Sidebar.js
import React, { useState, useEffect } from 'react';
import { NavLink } from 'react-router-dom';
import { getPluginSidebarItems, initializePluginOrder } from '../plugins/loader';
import { 
  initializeFeatureConfig, 
  isFeatureEnabled, 
  isPluginEnabled 
} from '../services/featureConfig';
import '../styles/Sidebar.css';

const Sidebar = () => {
  const [pluginItems, setPluginItems] = useState(() => getPluginSidebarItems());
  const [enabledFeatures, setEnabledFeatures] = useState(new Set());
  const [enabledPlugins, setEnabledPlugins] = useState(new Set());
  const [configLoaded, setConfigLoaded] = useState(false);
  
  // Feature configuration mapping
  const featureConfig = [
    { path: 'client', name: 'Client', featureKey: 'client' },
    { path: 'monitor', name: 'Monitor', featureKey: 'monitor' },
    { path: 'policies', name: 'Policies', featureKey: 'policies' },
    { path: 'adddata', name: 'Add Data', featureKey: 'adddata' },
    { path: 'viewfiles', name: 'View Files', featureKey: 'viewfiles' },
    { path: 'sqlquery', name: 'SQL Query', featureKey: 'sqlquery' },
    { path: 'blockchain', name: 'Blockchain Manager', featureKey: 'blockchain' },
    { path: 'presets', name: 'Presets', featureKey: 'presets' },
    { path: 'bookmarks', name: 'Bookmarks', featureKey: 'bookmarks' },
    { path: 'security', name: 'Security (Anylog)', featureKey: 'security' },
  ];
  
  // Fetch feature config and plugin order on mount
  useEffect(() => {
    const loadConfig = async () => {
      // Initialize both configs in parallel
      await Promise.all([
        initializeFeatureConfig(),
        initializePluginOrder()
      ]);
      
      // Check which features are enabled
      const enabled = new Set();
      for (const feature of featureConfig) {
        if (await isFeatureEnabled(feature.featureKey)) {
          enabled.add(feature.featureKey);
        }
      }
      setEnabledFeatures(enabled);
      
      // Check which plugins are enabled and filter plugin items
      const allPluginItems = getPluginSidebarItems();
      const enabledPluginItems = [];
      const enabledPluginSet = new Set();
      
      for (const plugin of allPluginItems) {
        if (await isPluginEnabled(plugin.path)) {
          enabledPluginItems.push(plugin);
          enabledPluginSet.add(plugin.path);
        }
      }
      
      setEnabledPlugins(enabledPluginSet);
      setPluginItems(enabledPluginItems);
      setConfigLoaded(true);
    };
    
    loadConfig();
  }, []);
  
  // Filter features based on config
  const visibleFeatures = featureConfig.filter(feature => 
    enabledFeatures.has(feature.featureKey)
  );
  
  // Filter plugins based on config
  const visiblePlugins = pluginItems.filter(plugin => 
    enabledPlugins.has(plugin.path)
  );
  
  return (
    <nav className="sidebar">
      {visibleFeatures.map((feature) => (
        <NavLink 
          key={feature.path}
          to={feature.path} 
          className={({ isActive }) => isActive ? 'active' : ''}
        >
          {feature.name}
        </NavLink>
      ))}
      
      {/* Plugin Navigation - Auto-loaded and filtered */}
      {configLoaded && visiblePlugins.length > 0 && (
        <div className="plugin-section">
          {visiblePlugins.map((plugin) => (
            <NavLink 
              key={plugin.path}
              to={plugin.path} 
              className={({ isActive }) => isActive ? 'active' : ''}
            >
              {plugin.icon && `${plugin.icon} `}{plugin.name}
            </NavLink>
          ))}
        </div>
      )}
      
    </nav>
  );
};

export default Sidebar;
