# Frontend API Refresh Tool

This tool automatically generates frontend API functions that match your backend plugin implementation. It scans your backend router files and creates corresponding frontend API files with proper error handling and TypeScript-ready code.

## Usage

```bash
# Refresh APIs for a specific plugin
python refresh_frontend_apis.py <plugin_name>

# Refresh APIs for all plugins
python refresh_frontend_apis.py all
```

## Examples

```bash
# Refresh calculator plugin APIs
python refresh_frontend_apis.py calculator

# Refresh all plugins at once
python refresh_frontend_apis.py all
```

## How It Works

1. **Scans Backend**: Reads your `<plugin_name>_router.py` file
2. **Extracts Routes**: Finds all `@api_router.get/post/put/delete` decorators
3. **Generates Functions**: Creates corresponding frontend API functions
4. **Writes File**: Creates `<plugin_name>_api.js` in the frontend plugin directory

## Generated API Files

The tool creates files like:
- `calculator_api.js` - Calculator plugin API functions

## Example Generated Code

For a backend route like:
```python
@api_router.post("/calculate")
async def calculate(request: CalculationRequest):
    """Perform a calculation"""
    # ... implementation
```

The tool generates:
```javascript
/**
 * Perform a calculation
 */
export const calculate = async (request) => {
  try {
    const url = `${API_URL}/calculator/calculate`
    const response = await fetch(url, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
      },
      body: JSON.stringify(request)
    });
    if (!response.ok) {
      const errorData = await response.json().catch(() => ({}));
      throw new Error(errorData.detail || `HTTP error! status: ${response.status}`);
    }
    return await response.json();
  } catch (error) {
    console.error('Error calling calculate:', error);
    throw error;
  }
};
```

## Using Generated APIs

In your React components:
```javascript
import { calculate, calculatorInfo } from './calculator_api';

// Use the generated functions
const result = await calculate({ operation: 'add', a: 5, b: 3 });
const info = await calculatorInfo();
```

## Before vs After Comparison

### Before (Manual Fetch)
```javascript
const handleCalculate = async () => {
  try {
    const response = await fetch(`${API_URL}/calculator/calculate`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ operation, a: numA, b: numB })
    });
    
    if (!response.ok) {
      const errorData = await response.json();
      throw new Error(errorData.detail || 'Calculation failed');
    }
    
    const data = await response.json();
    setResult(data);
  } catch (error) {
    setResult({ error: error.message });
  }
};
```

### After (Generated API)
```javascript
import { calculate } from './calculator_api';

const handleCalculate = async () => {
  try {
    const data = await calculate({ operation, a: numA, b: numB });
    setResult(data);
  } catch (error) {
    setResult({ error: error.message });
  }
};
```

### Benefits

- ✅ **Cleaner Code**: No more manual fetch setup
- ✅ **Error Handling**: Built-in error handling
- ✅ **Type Safety**: Consistent function signatures
- ✅ **Maintainable**: Auto-updates when backend changes
- ✅ **DRY Principle**: No duplicate API code

## Features

- ✅ **Automatic Route Detection**: Scans FastAPI decorators
- ✅ **Parameter Extraction**: Handles function parameters correctly
- ✅ **Error Handling**: Proper error handling with try/catch
- ✅ **HTTP Status Codes**: Checks response.ok and handles errors
- ✅ **TypeScript Ready**: Clean function signatures
- ✅ **Documentation**: Includes docstrings from backend
- ✅ **Consistent Naming**: Converts snake_case to camelCase

## Development Workflow

1. **Add Backend Route**:
   ```python
   @api_router.post("/new-endpoint")
   async def new_function(data: RequestModel):
       """New functionality"""
       return {"result": "success"}
   ```

2. **Refresh APIs**:
   ```bash
   python refresh_frontend_apis.py your_plugin
   ```

3. **Use Generated Function**:
   ```javascript
   import { newFunction } from './your_plugin_api';
   
   const result = await newFunction(data);
   ```

That's it! The tool handles all the boilerplate for you.

## Development Workflow (Legacy)

1. **Implement Backend**: Create your `<plugin_name>_router.py` with routes
2. **Run Refresh Tool**: `python refresh_frontend_apis.py <plugin_name>`
3. **Use Generated APIs**: Import and use the generated functions
4. **Repeat**: Run the tool whenever you add/modify backend routes

## Requirements

- Python 3.6+
- Backend plugin with `<plugin_name>_router.py` file
- FastAPI route decorators (`@api_router.get`, `@api_router.post`, etc.)

## Notes

- Generated files are **auto-generated** and will be overwritten
- Do not edit generated API files manually
- The tool uses regex parsing for route detection
- All functions include proper error handling
- API URL is configurable via environment variables
