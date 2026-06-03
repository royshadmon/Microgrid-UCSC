// Fully Automatic Frontend Plugin Loader
// Auto-discovers plugin pages by scanning the plugins directory

import React from 'react';
import { isPluginEnabled } from '../services/featureConfig';

// Cache for plugin order from backend
let cachedPluginOrder = null;
let orderFetchPromise = null;

// Fetch plugin order from backend
const fetchPluginOrder = async () => {
  if (cachedPluginOrder !== null) {
    return cachedPluginOrder;
  }
  
  if (orderFetchPromise) {
    return orderFetchPromise;
  }
  
  orderFetchPromise = (async () => {
    try {
      const API_URL = window._env_?.REACT_APP_API_URL || "http://localhost:8000";
      const response = await fetch(`${API_URL}/plugins/order`);
      if (response.ok) {
        const data = await response.json();
        cachedPluginOrder = data.plugin_order || [];
        return cachedPluginOrder;
      }
    } catch (error) {
      console.warn('Failed to fetch plugin order:', error);
    }
    // Return empty array if fetch fails (will use alphabetical order)
    cachedPluginOrder = [];
    return cachedPluginOrder;
  })();
  
  return orderFetchPromise;
};

// Sort plugins according to order config
const sortPluginsByOrder = (plugins, order) => {
  if (!order || order.length === 0) {
    // No order specified, return plugins in alphabetical order
    return Object.keys(plugins).sort().map(key => ({ key, plugin: plugins[key] }));
  }
  
  const ordered = [];
  const remaining = new Set(Object.keys(plugins));
  
  // Add plugins in specified order
  for (const pluginName of order) {
    if (plugins[pluginName]) {
      ordered.push({ key: pluginName, plugin: plugins[pluginName] });
      remaining.delete(pluginName);
    }
  }
  
  // Add remaining plugins alphabetically
  const remainingSorted = Array.from(remaining).sort();
  for (const pluginName of remainingSorted) {
    ordered.push({ key: pluginName, plugin: plugins[pluginName] });
  }
  
  return ordered;
};

// Auto-discover plugin pages by attempting imports
// Uses webpack's require.context to find all plugin Page.js files
export const discoverPluginPages = () => {
  const pluginPages = {};
  
  // Use require.context to get all plugin Page.js files
  // Pattern: ./pluginname/PluginnamePage.js
  const pluginContext = require.context('./', true, /^\.\/[^/]+\/[A-Z][^/]*Page\.js$/);
  
  pluginContext.keys().forEach(modulePath => {
    try {
      // Extract plugin name from path: ./pluginname/PluginnamePage.js
      const pathParts = modulePath.split('/');
      const pluginName = pathParts[1]; // Get the folder name
      const pageFileName = pathParts[2]; // Get the Page.js filename
      
      // Skip if we've already loaded this plugin
      if (pluginPages[pluginName]) {
        return;
      }
      
      // Import the module synchronously to get metadata
      const module = pluginContext(modulePath);
      
      // Get metadata from the module (each Page.js should export pluginMetadata)
      const metadata = module.pluginMetadata || {};
      
      // Create lazy-loaded component that imports dynamically
      // Store the modulePath for dynamic import
      const importPath = modulePath.replace(/^\.\//, './').replace(/\.js$/, '');
      
      const PluginPage = React.lazy(() => 
        import(`./${pluginName}/${pageFileName.replace(/\.js$/, '')}`)
          .catch(() => {
            // Fallback if import fails
            return {
              default: () => (
                <div style={{ padding: '20px' }}>
                  <h1>Plugin Not Found</h1>
                  <p>The {pluginName} plugin could not be loaded.</p>
                </div>
              )
            };
          })
      );
      
      pluginPages[pluginName] = {
        component: PluginPage,
        path: pluginName,
        name: metadata.name || formatPluginName(pluginName),
        icon: metadata.icon || null
      };
    } catch (error) {
      console.warn(`Failed to load plugin from ${modulePath}:`, error);
    }
  });
  
  return pluginPages;
};

// Helper function to format plugin name (fallback if metadata not provided)
const formatPluginName = (pluginName) => {
  // Convert camelCase or lowercase to Title Case
  // e.g., "reportgenerator" -> "Report Generator"
  // e.g., "nodeCheck" -> "Node Check"
  
  // Try to detect word boundaries
  const words = pluginName
    .replace(/([A-Z])/g, ' $1') // Add space before capital letters
    .replace(/([a-z])([A-Z])/g, '$1 $2') // Add space between lowercase and uppercase
    .toLowerCase()
    .split(/\s+/)
    .filter(word => word.length > 0);
  
  // Capitalize first letter of each word
  return words
    .map(word => word.charAt(0).toUpperCase() + word.slice(1))
    .join(' ');
};

// Get plugin pages for routing (sorted by plugin order)
// Note: This function is synchronous and doesn't filter by feature config
// Filtering should be done in components that use this function
export const getPluginPages = () => {
  const pages = discoverPluginPages();
  
  // Use cached order if available, otherwise sort alphabetically
  const order = cachedPluginOrder || [];
  const sortedPlugins = sortPluginsByOrder(pages, order);
  
  // Fetch order in background if not already cached (for next render)
  if (cachedPluginOrder === null && !orderFetchPromise) {
    fetchPluginOrder();
  }
  
  // Reconstruct object with plugins in sorted order
  // JavaScript objects maintain insertion order, so this will preserve the sort
  const sortedPages = {};
  for (const { key, plugin } of sortedPlugins) {
    sortedPages[key] = plugin;
  }
  
  return sortedPages;
};

// Get plugin pages filtered by feature config (async)
export const getPluginPagesFiltered = async () => {
  const pages = discoverPluginPages();
  
  // Use cached order if available, otherwise sort alphabetically
  const order = cachedPluginOrder || [];
  const sortedPlugins = sortPluginsByOrder(pages, order);
  
  // Fetch order in background if not already cached (for next render)
  if (cachedPluginOrder === null && !orderFetchPromise) {
    fetchPluginOrder();
  }
  
  // Filter plugins by feature config
  const filteredPlugins = [];
  for (const { key, plugin } of sortedPlugins) {
    if (await isPluginEnabled(key)) {
      filteredPlugins.push({ key, plugin });
    }
  }
  
  // Reconstruct object with filtered plugins in sorted order
  const filteredPages = {};
  for (const { key, plugin } of filteredPlugins) {
    filteredPages[key] = plugin;
  }
  
  return filteredPages;
};

// Get plugin sidebar items (sorted by plugin order)
// Note: This function is synchronous and doesn't filter by feature config
// Filtering should be done in components that use this function
export const getPluginSidebarItems = () => {
  const pages = discoverPluginPages();
  
  // Use cached order if available, otherwise sort alphabetically
  const order = cachedPluginOrder || [];
  const sortedPlugins = sortPluginsByOrder(pages, order);
  
  // Fetch order in background if not already cached (for next render)
  if (cachedPluginOrder === null && !orderFetchPromise) {
    fetchPluginOrder();
  }
  
  return sortedPlugins.map(({ plugin }) => ({
    path: plugin.path,
    name: plugin.name,
    icon: plugin.icon
  }));
};

// Get plugin sidebar items filtered by feature config (async)
export const getPluginSidebarItemsFiltered = async () => {
  const pages = discoverPluginPages();
  
  // Use cached order if available, otherwise sort alphabetically
  const order = cachedPluginOrder || [];
  const sortedPlugins = sortPluginsByOrder(pages, order);
  
  // Fetch order in background if not already cached (for next render)
  if (cachedPluginOrder === null && !orderFetchPromise) {
    fetchPluginOrder();
  }
  
  // Filter plugins by feature config
  const filteredItems = [];
  for (const { plugin } of sortedPlugins) {
    if (await isPluginEnabled(plugin.path)) {
      filteredItems.push({
        path: plugin.path,
        name: plugin.name,
        icon: plugin.icon
      });
    }
  }
  
  return filteredItems;
};

// Initialize plugin order fetch (call this early to preload the order)
export const initializePluginOrder = () => {
  const result = fetchPluginOrder();
  // fetchPluginOrder may return a promise or a value directly, so wrap it
  return Promise.resolve(result);
};
