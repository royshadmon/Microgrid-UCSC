# Feature Configuration System

This system allows you to enable/disable features and plugins for different customer deployments by configuring a JSON file.

## Configuration File

The feature configuration file is located at:
- **Backend**: `CLI/local-cli-backend/feature_config.json`

## How It Works

### Features
The system controls access to core features:
- `client` - Client connection and command execution
- `monitor` - Network monitoring
- `policies` - Policy management
- `adddata` - Add data to database
- `viewfiles` - View and manage files/blobs
- `sqlquery` - SQL Query Generator
- `blockchain` - Blockchain Manager
- `presets` - Preset management
- `bookmarks` - Bookmark management
- `security` - Security Policy Generator

### Plugins
The system also controls access to plugins:
- `reportgenerator` - Report Generator Plugin
- `nodecheck` - Node Check Plugin
- `calculator` - Calculator Plugin
- (Any other plugins you add)

## Configuration Format

```json
{
  "features": {
    "feature_name": {
      "enabled": true,
      "description": "Feature description"
    }
  },
  "plugins": {
    "plugin_name": {
      "enabled": true,
      "description": "Plugin description"
    }
  },
  "version": "1.0.0"
}
```

## Example: Disabling Features

To disable specific features for a customer deployment:

```json
{
  "features": {
    "client": { "enabled": true },
    "monitor": { "enabled": true },
    "policies": { "enabled": false },
    "adddata": { "enabled": true },
    "viewfiles": { "enabled": true },
    "sqlquery": { "enabled": false },
    "blockchain": { "enabled": true },
    "presets": { "enabled": true },
    "bookmarks": { "enabled": true },
    "security": { "enabled": false }
  },
  "plugins": {
    "reportgenerator": { "enabled": true },
    "nodecheck": { "enabled": false },
    "calculator": { "enabled": false }
  },
  "version": "1.0.0"
}
```

## What Gets Blocked

When a feature is disabled:

1. **Frontend**:
   - Feature is removed from the sidebar
   - Routes to the feature are not accessible
   - Users cannot navigate to disabled features

2. **Backend**:
   - API endpoints return 403 Forbidden
   - Routers are not included in the FastAPI app
   - All access to disabled features is cut off

3. **Plugins**:
   - Plugin routes are not loaded
   - Plugin sidebar items are hidden
   - Plugin API endpoints return 403

## Backend Protection

The system provides multiple layers of protection:

1. **Router Level**: Routers are conditionally included based on config
2. **Middleware**: HTTP middleware blocks requests to disabled features
3. **Endpoint Level**: Individual endpoints check feature status before processing

## API Endpoint

The backend exposes a configuration endpoint:
- `GET /feature-config` - Returns enabled/disabled status of all features and plugins

## Default Behavior

- If a feature/plugin is not in the config file, it defaults to **enabled** (backward compatibility)
- If the config file is missing, all features default to **enabled**

## Usage for Customer Deployments

1. Copy `feature_config.json` to your deployment
2. Set `"enabled": false` for features/plugins you want to disable
3. Restart the backend server
4. The frontend will automatically fetch and apply the configuration

## Notes

- Changes to `feature_config.json` require a backend restart
- The frontend caches the configuration on load
- Plugin order is still controlled by `plugin_order.json` (if present)
