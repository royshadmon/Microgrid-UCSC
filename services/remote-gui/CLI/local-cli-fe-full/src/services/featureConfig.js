// Feature Configuration Service
// Fetches and caches feature configuration from backend

let cachedFeatureConfig = null;
let configFetchPromise = null;

/**
 * Fetch feature configuration from backend
 * @returns {Promise<Object>} Feature configuration object
 */
export const fetchFeatureConfig = async () => {
  if (cachedFeatureConfig !== null) {
    return cachedFeatureConfig;
  }

  if (configFetchPromise) {
    return configFetchPromise;
  }

  configFetchPromise = (async () => {
    try {
      const API_URL = window._env_?.REACT_APP_API_URL || "http://localhost:8000";
      const response = await fetch(`${API_URL}/feature-config`);
      if (response.ok) {
        const data = await response.json();
        cachedFeatureConfig = data;
        return cachedFeatureConfig;
      } else {
        console.warn('Failed to fetch feature config:', response.status);
        // Return default: all features enabled
        cachedFeatureConfig = {
          features: {},
          plugins: {},
          version: "1.0.0"
        };
        return cachedFeatureConfig;
      }
    } catch (error) {
      console.warn('Failed to fetch feature config:', error);
      // Return default: all features enabled
      cachedFeatureConfig = {
        features: {},
        plugins: {},
        version: "1.0.0"
      };
      return cachedFeatureConfig;
    }
  })();

  return configFetchPromise;
};

/**
 * Check if a feature is enabled
 * @param {string} featureName - Name of the feature
 * @returns {boolean} True if enabled, false otherwise. Defaults to true if not in config.
 */
export const isFeatureEnabled = async (featureName) => {
  const config = await fetchFeatureConfig();
  const features = config.features || {};
  
  if (!(featureName in features)) {
    // Feature not in config, default to enabled for backward compatibility
    return true;
  }
  
  return features[featureName].enabled !== false;
};

/**
 * Check if a plugin is enabled
 * @param {string} pluginName - Name of the plugin
 * @returns {boolean} True if enabled, false otherwise. Defaults to true if not in config.
 */
export const isPluginEnabled = async (pluginName) => {
  const config = await fetchFeatureConfig();
  const plugins = config.plugins || {};
  
  if (!(pluginName in plugins)) {
    // Plugin not in config, default to enabled for backward compatibility
    return true;
  }
  
  return plugins[pluginName].enabled !== false;
};

/**
 * Get all enabled features
 * @returns {Promise<Set<string>>} Set of enabled feature names
 */
export const getEnabledFeatures = async () => {
  const config = await fetchFeatureConfig();
  const features = config.features || {};
  const enabled = new Set();
  
  for (const [name, data] of Object.entries(features)) {
    if (data.enabled !== false) {
      enabled.add(name);
    }
  }
  
  return enabled;
};

/**
 * Get all enabled plugins
 * @returns {Promise<Set<string>>} Set of enabled plugin names
 */
export const getEnabledPlugins = async () => {
  const config = await fetchFeatureConfig();
  const plugins = config.plugins || {};
  const enabled = new Set();
  
  for (const [name, data] of Object.entries(plugins)) {
    if (data.enabled !== false) {
      enabled.add(name);
    }
  }
  
  return enabled;
};

/**
 * Initialize feature config (call this early to preload)
 * @returns {Promise<Object>} Feature configuration
 */
export const initializeFeatureConfig = () => {
  return fetchFeatureConfig();
};
