"""
Feature Configuration Loader
Loads and validates feature configuration from feature_config.json
"""
import os
import json
from typing import Dict, Set, Optional

# Cache for feature config
_feature_config_cache: Optional[Dict] = None

def get_feature_config_path() -> str:
    """Get the path to feature_config.json"""
    BASE_DIR = os.path.dirname(os.path.abspath(__file__))
    return os.path.join(BASE_DIR, 'feature_config.json')

def load_feature_config() -> Dict:
    """
    Load feature configuration from feature_config.json
    Returns cached config if already loaded, otherwise loads from file
    """
    global _feature_config_cache
    
    if _feature_config_cache is not None:
        return _feature_config_cache
    
    config_path = get_feature_config_path()
    
    if not os.path.exists(config_path):
        print(f"⚠️  Warning: feature_config.json not found at {config_path}")
        print("⚠️  Using default: all features enabled")
        # Return default config with all features enabled
        _feature_config_cache = {
            "features": {},
            "plugins": {},
            "version": "1.0.0"
        }
        return _feature_config_cache
    
    try:
        with open(config_path, 'r') as f:
            config = json.load(f)
            _feature_config_cache = config
            return config
    except Exception as e:
        print(f"❌ Error loading feature_config.json: {e}")
        print("⚠️  Using default: all features enabled")
        _feature_config_cache = {
            "features": {},
            "plugins": {},
            "version": "1.0.0"
        }
        return _feature_config_cache

def is_feature_enabled(feature_name: str) -> bool:
    """
    Check if a core feature is enabled
    Returns True if feature is enabled, False otherwise
    If feature is not in config, defaults to True (backward compatibility)
    """
    config = load_feature_config()
    features = config.get("features", {})
    
    if feature_name not in features:
        # Feature not in config, default to enabled for backward compatibility
        return True
    
    return features[feature_name].get("enabled", True)

def is_plugin_enabled(plugin_name: str) -> bool:
    """
    Check if a plugin is enabled
    Returns True if plugin is enabled, False otherwise
    If plugin is not in config, defaults to True (backward compatibility)
    """
    config = load_feature_config()
    plugins = config.get("plugins", {})
    
    if plugin_name not in plugins:
        # Plugin not in config, default to enabled for backward compatibility
        return True
    
    return plugins[plugin_name].get("enabled", True)

def get_enabled_features() -> Set[str]:
    """Get set of all enabled feature names"""
    config = load_feature_config()
    features = config.get("features", {})
    return {name for name, data in features.items() if data.get("enabled", True)}

def get_enabled_plugins() -> Set[str]:
    """Get set of all enabled plugin names"""
    config = load_feature_config()
    plugins = config.get("plugins", {})
    return {name for name, data in plugins.items() if data.get("enabled", True)}

def get_backend_router_for_feature(feature_name: str) -> Optional[str]:
    """Get the backend router name for a feature, if specified"""
    config = load_feature_config()
    features = config.get("features", {})
    if feature_name in features:
        return features[feature_name].get("backend_router")
    return None

def reload_config():
    """Force reload of feature config (useful for testing or hot-reload)"""
    global _feature_config_cache
    _feature_config_cache = None
    return load_feature_config()
