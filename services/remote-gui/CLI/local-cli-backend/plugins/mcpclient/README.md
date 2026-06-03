# MCP Client Plugin - Backend Documentation

## Overview

The MCP Client plugin integrates Ollama (a local LLM framework) with AnyLog's Model Context Protocol (MCP) server to create an AI-powered maintenance copilot. This plugin allows users to interact with AnyLog data through natural language queries, where the AI agent can call MCP tools to fetch real-time data and provide intelligent responses.

## Architecture

The backend consists of two main modules:

1. **`mcp_agent.py`** - Core agent logic that handles MCP communication and Ollama integration
2. **`mcpclient_router.py`** - FastAPI REST API endpoints and WebSocket support

## File Structure

```
mcpclient/
├── __init__.py          # Plugin initialization
├── mcp_agent.py         # Core MCP agent implementation
├── mcpclient_router.py  # FastAPI router with REST/WebSocket endpoints
└── README.md            # This file
```

---

## Module 1: `mcp_agent.py`

### Purpose

This module contains the core logic for connecting to AnyLog MCP servers, converting MCP tools to Ollama-compatible formats, and orchestrating the conversation loop between the LLM and MCP tools.

### Dependencies

- **`ollama`** - Python client for Ollama LLM framework
- **`mcp`** - Model Context Protocol client library
- **`asyncio`** - For asynchronous operations
- **`json`** - For JSON schema manipulation
- **`contextlib.AsyncExitStack`** - For managing async context managers

### Detailed Component Breakdown

#### 1. Dependency Detection (Lines 11-26)

```python
try:
    import ollama
    HAS_OLLAMA = True
except ImportError:
    HAS_OLLAMA = False
    ollama = None
```

**Purpose**: Gracefully handles missing dependencies without crashing the plugin.

**Why**: The plugin should still load even if dependencies aren't installed, allowing the frontend to show helpful error messages rather than crashing the entire backend.

**Behavior**:
- Sets boolean flags (`HAS_OLLAMA`, `HAS_MCP`) to indicate availability
- Sets imported modules to `None` if unavailable
- Allows the router to check availability before attempting operations

#### 2. Configuration Constants (Lines 28-30)

```python
DEFAULT_ANYLOG_MCP_SSE_URL = os.getenv("ANYLOG_MCP_SSE_URL", "http://10.0.0.78:7849/mcp/sse")
DEFAULT_OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "qwen2.5:7b-instruct")
```

**Purpose**: Provides default configuration values with environment variable overrides.

**Configuration Options**:
- `ANYLOG_MCP_SSE_URL`: The Server-Sent Events (SSE) endpoint for AnyLog MCP server
- `OLLAMA_MODEL`: The Ollama model to use (options: qwen2.5:7b-instruct, gpt-oss:20b, mistral:7b-instruct, llama3.1:8b-instruct)

**Why Environment Variables**: Allows deployment-specific configuration without code changes.

#### 3. `sanitize_json_schema()` Function (Lines 32-54)

```python
def sanitize_json_schema(schema: dict) -> dict:
    """
    Fix common JSON Schema mistakes that break Ollama tool validation.
    - Move 'required' out of properties if incorrectly placed there.
    """
```

**Purpose**: Fixes JSON Schema formatting issues that prevent Ollama from understanding tool definitions.

**Problem It Solves**: 
Some MCP tools may define their schema with `required` nested inside `properties`, but Ollama expects `required` at the top level of the schema object.

**Example Transformation**:
```python
# Before (incorrect):
{
    "type": "object",
    "properties": {
        "name": {"type": "string"},
        "required": ["name"]  # Wrong location!
    }
}

# After (correct):
{
    "type": "object",
    "properties": {
        "name": {"type": "string"}
    },
    "required": ["name"]  # Correct location
}
```

**Algorithm**:
1. Check if schema is a dict, return default if not
2. If type is not "object", return as-is
3. Check if `required` is incorrectly nested in `properties`
4. Extract `required` from `properties`
5. Move it to top-level of schema
6. Return sanitized schema

**Why This Matters**: Without this fix, Ollama would reject tool definitions, preventing the agent from using MCP tools.

#### 4. `mcp_tools_to_ollama_tools()` Function (Lines 56-73)

```python
def mcp_tools_to_ollama_tools(mcp_tools) -> List[Dict[str, Any]]:
    """
    Convert MCP tool schema to Ollama tool schema:
    Ollama expects: [{"type":"function","function":{"name","description","parameters"}}]
    """
```

**Purpose**: Converts MCP tool definitions into the format Ollama expects for function calling.

**Input Format** (MCP):
```python
Tool(
    name="executeQuery",
    description="Execute a SQL query",
    inputSchema={
        "type": "object",
        "properties": {
            "query": {"type": "string"}
        },
        "required": ["query"]
    }
)
```

**Output Format** (Ollama):
```python
{
    "type": "function",
    "function": {
        "name": "executeQuery",
        "description": "Execute a SQL query",
        "parameters": {
            "type": "object",
            "properties": {
                "query": {"type": "string"}
            },
            "required": ["query"]
        }
    }
}
```

**Key Transformations**:
- Wraps each tool in `{"type": "function", "function": {...}}`
- Maps `inputSchema` → `parameters`
- Sanitizes the schema using `sanitize_json_schema()`
- Handles missing descriptions with empty string fallback

**Why This Exists**: MCP and Ollama use different but similar tool definition formats. This function bridges the gap.

#### 5. `ollama_chat_async()` Function (Lines 76-81)

```python
async def ollama_chat_async(**kwargs):
    """Run ollama.chat without blocking the event loop"""
    return await asyncio.to_thread(ollama.chat, **kwargs)
```

**Purpose**: Wraps the synchronous `ollama.chat()` function to run in a thread pool, preventing it from blocking the async event loop.

**Why This Is Needed**:
- `ollama.chat()` is a synchronous function that can take several seconds
- If called directly in async code, it would block all other async operations
- `asyncio.to_thread()` runs it in a separate thread, allowing other async tasks to continue

**Performance Impact**: Without this, the entire FastAPI server would freeze during LLM inference, making it unresponsive to other requests.

#### 6. `AnyLogMCPAgent` Class (Lines 84-178)

This is the main class that orchestrates the entire agent workflow.

##### Constructor `__init__()` (Lines 85-89)

```python
def __init__(self, anylog_sse_url: str, ollama_model: str = DEFAULT_OLLAMA_MODEL):
    self.anylog_sse_url = anylog_sse_url
    self.ollama_model = ollama_model
    self.session: Optional[ClientSession] = None
    self.exit_stack = AsyncExitStack()
```

**Parameters**:
- `anylog_sse_url`: The SSE endpoint URL for the AnyLog MCP server
- `ollama_model`: The Ollama model identifier to use

**Instance Variables**:
- `self.session`: The MCP client session (None until connected)
- `self.exit_stack`: Manages async context managers for proper cleanup

**Why `AsyncExitStack`**: Ensures all resources (stdio transport, session) are properly closed even if errors occur.

##### `connect()` Method (Lines 91-108)

```python
async def connect(self):
    """Connect to AnyLog MCP server via mcp-proxy"""
```

**Purpose**: Establishes connection to AnyLog MCP server through `mcp-proxy`.

**Connection Flow**:

1. **Check Dependencies** (Lines 93-94):
   - Verifies MCP libraries are installed
   - Raises `RuntimeError` with helpful message if not

2. **Create Server Parameters** (Lines 96-101):
   ```python
   server_params = StdioServerParameters(
       command="mcp-proxy",
       args=[self.anylog_sse_url],
       env=None,
   )
   ```
   - Configures `mcp-proxy` as a stdio subprocess
   - Passes AnyLog SSE URL as argument
   - `mcp-proxy` bridges stdio communication to remote SSE endpoint

3. **Establish Stdio Transport** (Line 102):
   ```python
   stdio_transport = await self.exit_stack.enter_async_context(stdio_client(server_params))
   ```
   - Creates stdio transport (stdin/stdout pipes)
   - Registers with exit stack for cleanup
   - Returns `(stdio_reader, stdio_writer)` tuple

4. **Create MCP Session** (Lines 103-104):
   ```python
   self.session = await self.exit_stack.enter_async_context(ClientSession(self.stdio, self.write))
   await self.session.initialize()
   ```
   - Creates MCP client session using stdio transport
   - Initializes the session (handshake with MCP server)
   - Registers with exit stack

5. **List Available Tools** (Lines 107-108):
   ```python
   tools_resp = await self.session.list_tools()
   return [t.name for t in tools_resp.tools]
   ```
   - Queries MCP server for available tools
   - Returns list of tool names for verification

**Why `mcp-proxy`**: 
- MCP protocol typically uses stdio for local communication
- AnyLog MCP server uses SSE (Server-Sent Events) over HTTP
- `mcp-proxy` translates between stdio MCP protocol and SSE HTTP protocol

**Error Handling**: All errors propagate up to caller (router) for proper HTTP error responses.

##### `ask()` Method (Lines 110-172)

This is the core method that implements the agent loop.

**Purpose**: Processes a user question through the agent, allowing it to call MCP tools as needed.

**Method Signature**:
```python
async def ask(self, user_prompt: str) -> str:
```

**Step-by-Step Flow**:

1. **Validation** (Lines 112-116):
   ```python
   if not self.session:
       raise RuntimeError("Not connected. Call connect() first.")
   if not HAS_OLLAMA:
       raise RuntimeError("Ollama is not installed...")
   ```
   - Ensures connection is established
   - Verifies Ollama is available

2. **Get MCP Tools** (Lines 118-120):
   ```python
   tools_resp = await self.session.list_tools()
   ollama_tools = mcp_tools_to_ollama_tools(tools_resp.tools)
   ```
   - Fetches current list of MCP tools
   - Converts to Ollama format
   - Tools may change between calls, so we fetch fresh each time

3. **Initialize Message History** (Lines 122-135):
   ```python
   messages: List[Dict[str, Any]] = [
       {
           "role": "system",
           "content": (
               "You are a maintenance copilot for PLC-controlled units. "
               "You cannot access AnyLog data unless you call tools. "
               "ALWAYS call tools to fetch facts before concluding. "
               ...
           ),
       },
       {"role": "user", "content": user_prompt},
   ]
   ```
   - **System Prompt**: Instructs the AI on its role and behavior
     - Role: Maintenance copilot for PLC units
     - Constraint: Must use tools to access data
     - Guidance: Use `executeQuery` or `queryWithIncrement` for trends
     - Warning: Never guess values
   - **User Message**: The actual question

4. **Agent Loop** (Lines 137-171):
   ```python
   for _ in range(12):  # safety loop cap
   ```
   - Maximum 12 iterations to prevent infinite loops
   - Each iteration represents one LLM call + potential tool execution

   **Iteration Steps**:

   a. **Call Ollama** (Lines 139-144):
      ```python
      resp = await ollama_chat_async(
          model=self.ollama_model,
          messages=messages,
          tools=ollama_tools,
          stream=False,
      )
      ```
      - Sends entire message history + available tools to Ollama
      - `stream=False`: Get complete response (not streaming)
      - Ollama analyzes the conversation and decides:
        - Answer directly, OR
        - Call one or more tools

   b. **Extract Response** (Lines 146-147):
      ```python
      msg = resp["message"]
      messages.append(msg)
      ```
      - Gets the message object from response
      - Adds to conversation history

   c. **Check for Tool Calls** (Lines 149-151):
      ```python
      tool_calls = msg.get("tool_calls") or []
      if not tool_calls:
          return msg.get("content", "")
      ```
      - If no tool calls, we have a final answer
      - Return the content immediately

   d. **Execute Tool Calls** (Lines 153-170):
      ```python
      for tc in tool_calls:
          fn = tc["function"]
          tool_name = fn["name"]
          tool_args = fn.get("arguments") or {}
          if isinstance(tool_args, str):
              tool_args = json.loads(tool_args)
          
          result = await self.session.call_tool(tool_name, tool_args)
          
          messages.append({
              "role": "tool",
              "tool_name": tool_name,
              "content": json.dumps(result.model_dump() if hasattr(result, "model_dump") else result, default=str),
          })
      ```
      - Iterates through each tool call Ollama requested
      - Extracts tool name and arguments
      - Parses JSON string arguments if needed
      - Calls the tool via MCP session
      - Converts result to JSON string
      - Adds tool result to message history as `role: "tool"`
      - Loop continues with tool results included

5. **Safety Limit** (Line 172):
   ```python
   return "Stopped (too many tool-call iterations). Try narrowing the question."
   ```
   - If loop completes 12 iterations without final answer
   - Returns error message (likely infinite loop or complex query)

**Example Conversation Flow**:

```
User: "What's the temperature of unit 250?"
↓
Iteration 1:
  Ollama: [calls tool: getUnitData(unit=250)]
  Tool Result: {"temperature": 75.3}
  ↓
Iteration 2:
  Ollama: "The temperature of unit 250 is 75.3°F"
  (no tool calls) → Return answer
```

**Why This Design**:
- **Iterative**: Allows multi-step reasoning (query → analyze → query more → answer)
- **Tool Integration**: Seamlessly combines LLM reasoning with real data
- **Safety**: Loop limit prevents runaway processes
- **Context Preservation**: Full message history maintains conversation context

##### `close()` Method (Lines 174-176)

```python
async def close(self):
    """Close the MCP connection"""
    await self.exit_stack.aclose()
```

**Purpose**: Properly closes all resources managed by the exit stack.

**What Gets Closed**:
1. MCP client session
2. Stdio transport (closes pipes to `mcp-proxy`)
3. `mcp-proxy` subprocess

**Why Important**: Prevents resource leaks and ensures clean shutdown.

---

## Module 2: `mcpclient_router.py`

### Purpose

Provides FastAPI REST API endpoints and WebSocket support for the frontend to interact with the MCP agent.

### Dependencies

- **`fastapi`** - Web framework for REST API
- **`pydantic`** - Data validation and settings management
- **`asyncio`** - For async operations and locks

### Detailed Component Breakdown

#### 1. Router Initialization (Lines 12-26)

```python
api_router = APIRouter(prefix="/mcpclient", tags=["MCP Client"])
```

**Purpose**: Creates FastAPI router with prefix `/mcpclient`, so all endpoints are under `/mcpclient/*`.

**Import Handling** (Lines 14-26):
```python
HAS_MCP_AGENT = False
try:
    from .mcp_agent import AnyLogMCPAgent, ...
    HAS_MCP_AGENT = True
except ImportError as e:
    # Create dummy class for error handling
    class AnyLogMCPAgent:
        def __init__(self, *args, **kwargs):
            raise RuntimeError("MCP agent not available - missing dependencies")
```

**Why**: Allows plugin to load even if dependencies missing, providing graceful error messages instead of crashing.

#### 2. Pydantic Models (Lines 28-44)

**Request Models**:

```python
class MCPConnectRequest(BaseModel):
    anylog_sse_url: Optional[str] = None
    ollama_model: Optional[str] = None
```

**Purpose**: Validates and structures connection request data.

**Fields**:
- `anylog_sse_url`: Optional override for AnyLog URL (uses env var if None)
- `ollama_model`: Optional override for Ollama model (uses env var if None)

```python
class MCPAskRequest(BaseModel):
    prompt: str
    anylog_sse_url: Optional[str] = None
    ollama_model: Optional[str] = None
```

**Purpose**: Validates question requests.

**Fields**:
- `prompt`: Required user question
- `anylog_sse_url`, `ollama_model`: Optional overrides

**Response Model**:

```python
class MCPStatusResponse(BaseModel):
    connected: bool
    available_tools: List[str]
    ollama_available: bool
    mcp_available: bool
    current_model: Optional[str] = None
    anylog_url: Optional[str] = None
```

**Purpose**: Structured status information for frontend.

**Fields Explained**:
- `connected`: Whether agent is currently connected to MCP
- `available_tools`: List of tool names available from MCP
- `ollama_available`: Whether Ollama library is installed
- `mcp_available`: Whether MCP library is installed
- `current_model`: Currently configured Ollama model
- `anylog_url`: Currently configured AnyLog URL

#### 3. Global Agent Management (Lines 46-68)

**Design Decision**: Uses a single global agent instance.

**Why**: Simplifies implementation for single-user scenarios. For multi-user, use per-user sessions.

**Implementation**:

```python
_agent_instance: Optional[AnyLogMCPAgent] = None
_agent_lock = asyncio.Lock()
```

**Global Variables**:
- `_agent_instance`: The single agent instance (None if not connected)
- `_agent_lock`: Async lock to prevent race conditions

**Helper Functions**:

```python
async def get_or_create_agent(...) -> AnyLogMCPAgent:
    global _agent_instance
    async with _agent_lock:
        if _agent_instance is None:
            # Create and connect
        return _agent_instance
```

**Purpose**: Thread-safe lazy initialization of agent.

**Lock Usage**: `async with _agent_lock:` ensures only one coroutine can modify `_agent_instance` at a time.

```python
async def close_agent():
    global _agent_instance
    async with _agent_lock:
        if _agent_instance is not None:
            await _agent_instance.close()
            _agent_instance = None
```

**Purpose**: Thread-safe cleanup of agent.

#### 4. REST API Endpoints

##### `GET /` - Plugin Information (Lines 71-91)

```python
@api_router.get("/")
async def mcpclient_info():
```

**Purpose**: Returns plugin metadata and capability information.

**Response**:
```json
{
    "name": "MCP Client Plugin",
    "version": "1.0.0",
    "description": "Integrates Ollama with AnyLog MCP...",
    "ollama_available": true,
    "mcp_available": true,
    "dependencies": {
        "ollama": true,
        "mcp": true
    },
    "endpoints": [...]
}
```

**Use Case**: Frontend can check if plugin is available and what endpoints exist.

##### `GET /status` - Connection Status (Lines 93-137)

```python
@api_router.get("/status")
async def get_status():
```

**Purpose**: Returns current connection status and configuration.

**Logic Flow**:

1. **Check Agent Availability** (Lines 98-106):
   - If agent module not loaded, return disconnected status

2. **Check Connection** (Lines 108-116):
   - If `_agent_instance` is None or session is None, return disconnected
   - Include current model/URL from instance if it exists

3. **Get Active Status** (Lines 118-128):
   - Try to list tools from active session
   - If successful, return connected status with tools
   - If exception, return disconnected (connection may have dropped)

**Error Handling**: Catches exceptions and returns disconnected status rather than crashing.

**Response Examples**:

**Connected**:
```json
{
    "connected": true,
    "available_tools": ["executeQuery", "queryWithIncrement", ...],
    "ollama_available": true,
    "mcp_available": true,
    "current_model": "qwen2.5:7b-instruct",
    "anylog_url": "http://10.0.0.78:7849/mcp/sse"
}
```

**Disconnected**:
```json
{
    "connected": false,
    "available_tools": [],
    "ollama_available": true,
    "mcp_available": true,
    "current_model": null,
    "anylog_url": null
}
```

##### `POST /connect` - Connect to MCP (Lines 139-169)

```python
@api_router.post("/connect")
async def connect_mcp(request: MCPConnectRequest):
```

**Purpose**: Establishes connection to AnyLog MCP server.

**Request Body**:
```json
{
    "anylog_sse_url": "http://10.0.0.78:7849/mcp/sse",  // optional
    "ollama_model": "qwen2.5:7b-instruct"  // optional
}
```

**Process**:

1. **Validate Dependencies** (Lines 142-146):
   - Check if agent module is available
   - Return 500 error if dependencies missing

2. **Close Existing Connection** (Line 152):
   ```python
   await close_agent()
   ```
   - Ensures clean state before new connection

3. **Resolve Configuration** (Lines 155-156):
   ```python
   url = request.anylog_sse_url or os.getenv("ANYLOG_MCP_SSE_URL", DEFAULT_ANYLOG_MCP_SSE_URL)
   model = request.ollama_model or os.getenv("OLLAMA_MODEL", DEFAULT_OLLAMA_MODEL)
   ```
   - Priority: Request → Environment Variable → Default
   - Allows flexible configuration

4. **Create and Connect** (Lines 158-159):
   ```python
   _agent_instance = AnyLogMCPAgent(anylog_sse_url=url, ollama_model=model)
   tools = await _agent_instance.connect()
   ```
   - Creates new agent instance
   - Connects to MCP server
   - Gets list of available tools

5. **Return Success** (Lines 161-167):
   ```json
   {
       "success": true,
       "message": "Connected to AnyLog MCP",
       "available_tools": ["executeQuery", ...],
       "ollama_model": "qwen2.5:7b-instruct",
       "anylog_url": "http://10.0.0.78:7849/mcp/sse"
   }
   ```

**Error Handling**: Catches all exceptions and returns 500 with error message.

##### `POST /disconnect` - Disconnect from MCP (Lines 171-181)

```python
@api_router.post("/disconnect")
async def disconnect_mcp():
```

**Purpose**: Closes connection to MCP server.

**Process**:
1. Calls `close_agent()` to clean up resources
2. Returns success message

**Response**:
```json
{
    "success": true,
    "message": "Disconnected from AnyLog MCP"
}
```

**Error Handling**: Returns 500 if disconnect fails (shouldn't happen, but handled).

##### `GET /tools` - List Available Tools (Lines 183-215)

```python
@api_router.get("/tools")
async def list_tools():
```

**Purpose**: Returns detailed information about all available MCP tools.

**Validation**:
1. Check if agent module available (Lines 188-192)
2. Check if connected (Lines 194-198)

**Process**:
1. Query MCP session for tools (Line 201)
2. Transform to frontend-friendly format (Lines 202-208):
   ```python
   for t in tools_resp.tools:
       tools.append({
           "name": t.name,
           "description": t.description or "",
           "inputSchema": t.inputSchema or {}
       })
   ```

**Response**:
```json
{
    "success": true,
    "tools": [
        {
            "name": "executeQuery",
            "description": "Execute a SQL query on AnyLog",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "query": {"type": "string"}
                },
                "required": ["query"]
            }
        },
        ...
    ],
    "count": 5
}
```

**Use Case**: Frontend can display available tools to users, show tool documentation, etc.

##### `POST /ask` - Ask a Question (Lines 217-245)

```python
@api_router.post("/ask")
async def ask_question(request: MCPAskRequest):
```

**Purpose**: Processes a user question through the MCP agent.

**Request Body**:
```json
{
    "prompt": "What's the temperature of unit 250?",
    "anylog_sse_url": "http://...",  // optional
    "ollama_model": "qwen2.5:7b-instruct"  // optional
}
```

**Process**:

1. **Validate Dependencies** (Lines 220-224)

2. **Auto-Connect if Needed** (Lines 230-234):
   ```python
   if _agent_instance is None or _agent_instance.session is None:
       # Create and connect with provided/config values
       _agent_instance = AnyLogMCPAgent(...)
       await _agent_instance.connect()
   ```
   - **Design Decision**: Automatically connects if not connected
   - **Rationale**: User-friendly - don't require explicit connect step
   - **Trade-off**: May hide connection issues, but convenient

3. **Process Question** (Line 237):
   ```python
   answer = await _agent_instance.ask(request.prompt)
   ```
   - Calls agent's `ask()` method
   - This triggers the full agent loop (LLM + tool calls)

4. **Return Answer** (Lines 239-243):
   ```json
   {
       "success": true,
       "answer": "The temperature of unit 250 is 75.3°F...",
       "prompt": "What's the temperature of unit 250?"
   }
   ```

**Error Handling**: Returns 500 with error message if processing fails.

**Performance**: This endpoint may take several seconds as it:
- Calls Ollama (LLM inference)
- May execute multiple MCP tool calls
- Iterates through agent loop

**Consideration**: For production, consider adding timeout or async job processing.

#### 5. WebSocket Endpoint (Lines 247-330)

```python
@api_router.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
```

**Purpose**: Provides real-time bidirectional communication for streaming chat.

**Why WebSocket**: 
- Lower latency than HTTP polling
- Can support streaming responses (future enhancement)
- Better for interactive chat interfaces

**Connection Flow**:

1. **Accept Connection** (Line 250):
   ```python
   await websocket.accept()
   ```

2. **Validate Dependencies** (Lines 252-258):
   - Send error and close if agent not available

3. **Message Loop** (Lines 263-318):
   ```python
   while True:
       data = await websocket.receive_json()
       # Process message based on type
   ```

**Message Types**:

**a. `connect`** (Lines 266-279):
```json
{
    "type": "connect",
    "anylog_sse_url": "http://...",
    "ollama_model": "qwen2.5:7b-instruct"
}
```
- Creates agent instance and connects
- Returns connection confirmation with tools

**Response**:
```json
{
    "type": "connected",
    "tools": ["executeQuery", ...],
    "model": "qwen2.5:7b-instruct",
    "url": "http://..."
}
```

**b. `ask`** (Lines 281-304):
```json
{
    "type": "ask",
    "prompt": "What's the temperature?"
}
```
- Validates connection exists
- Processes question through agent
- Returns answer

**Response**:
```json
{
    "type": "answer",
    "answer": "The temperature is...",
    "prompt": "What's the temperature?"
}
```

**c. `disconnect`** (Lines 306-312):
```json
{
    "type": "disconnect"
}
```
- Closes agent connection
- Returns confirmation

**Response**:
```json
{
    "type": "disconnected"
}
```

**d. Unknown Type** (Lines 314-318):
- Returns error message for invalid message types

**Error Handling**:

1. **WebSocketDisconnect** (Lines 320-322):
   - Client closed connection
   - Clean up agent resources

2. **General Exceptions** (Lines 323-329):
   - Send error message to client
   - Clean up resources

**Agent Lifecycle**: Each WebSocket connection creates its own agent instance (unlike REST which uses global). This allows multiple concurrent WebSocket sessions.

---

## Error Handling Strategy

### Dependency Missing
- Plugin loads successfully
- Endpoints return helpful error messages
- Frontend can display "Install dependencies" message

### Connection Failures
- Caught and returned as HTTP 500 with descriptive message
- Status endpoint returns disconnected state
- Frontend can retry or show error

### Agent Loop Failures
- Exceptions caught in `ask()` endpoint
- Returned as HTTP 500
- User sees error message in chat

### Resource Cleanup
- `AsyncExitStack` ensures cleanup even on errors
- `close_agent()` always called on disconnect
- WebSocket cleanup on disconnect/error

---

## Configuration

### Environment Variables

1. **`ANYLOG_MCP_SSE_URL`**: AnyLog MCP server SSE endpoint
   - Default: `http://10.0.0.78:7849/mcp/sse`
   - Can be overridden per-request

2. **`OLLAMA_MODEL`**: Ollama model to use
   - Default: `qwen2.5:7b-instruct`
   - Options: `qwen2.5:7b-instruct`, `gpt-oss:20b`, `mistral:7b-instruct`, `llama3.1:8b-instruct`
   - Can be overridden per-request

### Configuration Priority

1. Request parameter (highest priority)
2. Environment variable
3. Default value (lowest priority)

---

## Security Considerations

### Current Implementation
- No authentication/authorization
- Global agent instance (shared state)
- No input sanitization beyond Pydantic validation

### Recommendations for Production
1. Add authentication middleware
2. Per-user agent instances (session management)
3. Rate limiting on `/ask` endpoint
4. Input validation/sanitization for prompts
5. Timeout on agent operations
6. Resource limits (max iterations, max tool calls)

---

## Performance Considerations

### Bottlenecks
1. **LLM Inference**: Ollama calls can take 1-10+ seconds
2. **MCP Tool Calls**: Network latency to AnyLog server
3. **Agent Loop**: Multiple iterations multiply latency

### Optimizations
1. **Async Operations**: All I/O is async (non-blocking)
2. **Thread Pool**: Ollama calls run in thread pool
3. **Connection Reuse**: Agent maintains persistent MCP connection

### Future Enhancements
1. Streaming responses (partial answers as they generate)
2. Caching common queries
3. Parallel tool execution when possible
4. Request queuing for high load

---

## Testing

### Manual Testing Checklist

1. **Dependency Check**:
   - Test with/without `ollama` installed
   - Test with/without `mcp` installed
   - Verify graceful error messages

2. **Connection**:
   - Connect with valid URL
   - Connect with invalid URL (should error)
   - Connect with default config
   - Connect with custom config

3. **Status**:
   - Check status when disconnected
   - Check status when connected
   - Verify tool list accuracy

4. **Ask**:
   - Simple question (no tools needed)
   - Question requiring tool calls
   - Question requiring multiple tool calls
   - Invalid question (should handle gracefully)

5. **WebSocket**:
   - Connect via WebSocket
   - Send questions
   - Disconnect
   - Test error handling

---

## Troubleshooting

### Common Issues

1. **"MCP agent not available"**
   - Install: `pip install ollama mcp`

2. **"Not connected"**
   - Call `/connect` endpoint first
   - Check AnyLog MCP server is running
   - Verify URL is correct

3. **"Too many tool-call iterations"**
   - Question may be too complex
   - Try breaking into smaller questions
   - Check MCP tools are working correctly

4. **Connection Timeout**
   - Verify `mcp-proxy` is in PATH
   - Check network connectivity to AnyLog server
   - Verify AnyLog MCP server is accessible

---

## Future Enhancements

1. **Streaming Responses**: Stream LLM output as it generates
2. **Multi-User Support**: Per-user agent instances
3. **Tool Result Caching**: Cache tool results for repeated queries
4. **Conversation History**: Persist conversations across sessions
5. **Custom System Prompts**: Allow users to customize agent behavior
6. **Tool Usage Analytics**: Track which tools are used most
7. **Response Formatting**: Better formatting for tool results (tables, charts)
8. **Async Job Processing**: Long-running queries as background jobs

---

## API Reference Summary

| Endpoint | Method | Purpose | Auth Required |
|----------|--------|---------|---------------|
| `/` | GET | Plugin info | No |
| `/status` | GET | Connection status | No |
| `/connect` | POST | Connect to MCP | No |
| `/disconnect` | POST | Disconnect from MCP | No |
| `/tools` | GET | List MCP tools | No |
| `/ask` | POST | Ask question | No |
| `/ws` | WebSocket | Streaming chat | No |

---

## Dependencies

### Required
- `fastapi` - Web framework
- `pydantic` - Data validation
- `asyncio` - Async support (built-in)

### Optional (for full functionality)
- `ollama` - Ollama Python client
- `mcp` - Model Context Protocol client

### External Tools
- `mcp-proxy` - Must be in system PATH
- Ollama server - Must be running locally or accessible
- AnyLog MCP server - Must be accessible at configured URL

---

## Conclusion

The MCP Client backend provides a robust integration between Ollama LLMs and AnyLog MCP servers, enabling natural language interaction with industrial data. The architecture separates concerns (agent logic vs. API), handles errors gracefully, and provides both REST and WebSocket interfaces for maximum flexibility.

