# Fully Automatic Plugin System

This is a fully automatic plugin system that supports organized folder structures and completely automatic frontend routing.

## How to Create a Backend Plugin

1. Create a folder in `CLI/local-cli-backend/plugins/` with your plugin name
2. Create a file named `<plugin_name>_router.py` in that folder
3. Define an `api_router` variable that is a FastAPI APIRouter
4. That's it! The plugin loader will automatically find and load it.

### Example Backend Plugin Structure:

```
CLI/local-cli-backend/plugins/
└── calculator/
    ├── __init__.py
    └── calculator_router.py
```

### Example Backend Plugin (`calculator_router.py`):

```python
from fastapi import APIRouter
from pydantic import BaseModel

# Create the API router
api_router = APIRouter(prefix="/calculator", tags=["Calculator"])

# Request model
class CalculationRequest(BaseModel):
    operation: str
    a: float
    b: float

# API endpoints
@api_router.get("/")
async def calculator_info():
    return {"name": "Simple Calculator Plugin"}

@api_router.post("/calculate")
async def calculate(request: CalculationRequest):
    # Your logic here
    return {"result": request.a + request.b}
```

## How to Create a Frontend Plugin

1. Create a folder in `CLI/local-cli-fe-full/src/plugins/` with your plugin name
2. Create a React component named `<PluginName>Page.js` in that folder
3. **Important**: Use the full API URL (`${API_URL}/your-plugin/endpoint`) for all fetch calls
4. Add the plugin name to the `KNOWN_PLUGINS` array in `loader.js`
5. The routing and sidebar navigation will be completely automatic!

### Example Frontend Plugin Structure:

```
CLI/local-cli-fe-full/src/plugins/
└── calculator/
    └── CalculatorPage.js
```

### Example Frontend Plugin (`CalculatorPage.js`):

```javascript
import React, { useState } from 'react';

// Get API URL from environment or default to localhost:8000
const API_URL = window._env_?.REACT_APP_API_URL || "http://localhost:8000";

const CalculatorPage = () => {
  const handleCalculate = async () => {
    const response = await fetch(`${API_URL}/calculator/calculate`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ operation: 'add', a: 5, b: 3 })
    });
    const data = await response.json();
    // Handle response...
  };

  return (
    <div>
      <h1>Calculator Plugin</h1>
      {/* Your UI here */}
    </div>
  );
};

export default CalculatorPage;
```

### Adding to Plugin Loader (`loader.js`):

```javascript
// Add your plugin name to this array
const KNOWN_PLUGINS = [
  'calculator',
  'yournewplugin'  // Add your plugin here
];

// Icons are optional - add to iconMap if you want one
const iconMap = {
  calculator: '🧮',
  yournewplugin: '🔌',  // Optional icon
  // Or leave out for no icon
};
```

## Plugin Loading Order

By default, plugins are loaded in alphabetical order. However, you can control the loading order by creating a `plugin_order.json` file in the `plugins/` directory.

### Creating a Plugin Order Configuration

1. Copy the example file: `cp plugin_order.json.example plugin_order.json`
2. Edit `plugin_order.json` and specify your desired plugin order:

```json
{
  "plugin_order": [
    "reportgenerator",
    "nodecheck",
    "calculator"
  ]
}
```

**Notes:**
- Plugins listed in `plugin_order` will be loaded first, in the order specified
- Plugins not listed in `plugin_order` will be loaded after, in alphabetical order
- If `plugin_order.json` doesn't exist, all plugins load alphabetically (default behavior)
- The order affects the sequence in which routers are added to the FastAPI app, which can be important for route precedence

## Fully Automatic Features

- **Backend**: Automatically discovers plugin folders and loads `<plugin_name>_router.py` files
- **Frontend**: Automatically attempts to import plugin pages and adds them to routing
- **Sidebar**: Automatically adds navigation items with appropriate icons
- **Error Handling**: Gracefully handles missing plugins with fallback components
- **Lazy Loading**: Plugin pages load on-demand with loading states
- **Custom Ordering**: Control plugin loading order via `plugin_order.json`

## Plugin Structure Summary

**Backend:**
- Folder: `CLI/local-cli-backend/plugins/<plugin_name>/`
- Router file: `<plugin_name>_router.py`
- Export: `api_router = APIRouter(...)`

**Frontend:**
- Folder: `CLI/local-cli-fe-full/src/plugins/<plugin_name>/`
- Page file: `<PluginName>Page.js`
- Register in: `loader.js` → `KNOWN_PLUGINS` array

## Example Plugins Included

1. **Calculator Plugin** (`calculator/`)
   - Simple arithmetic operations
   - 2 API endpoints
   - Clean UI with form handling
   - **Icon**: 🧮

## That's It!

The system is now completely automatic:
- **Backend**: Just create a folder with `<plugin_name>_router.py` and it's discovered
- **Frontend**: Just create a folder with `<PluginName>Page.js` and add to `KNOWN_PLUGINS`
- **No manual routing**: Everything is handled automatically
- **No manual navigation**: Sidebar items are added automatically
- **Error resilient**: Missing plugins show fallback components

Total: **2 API endpoints** across **1 plugin** working automatically!



# Process
1. make folder for nodecheck
2. make nodecheck_router.py
3. write routes for nodecheck
4. run refresh_frontend_apis.py to update the frontend
5. write the frontend page using the generated api functions


