
"""
MCP Agent for AnyLog integration with Ollama
Based on ollama_demo.py
"""
import asyncio
import json
from contextlib import AsyncExitStack
from typing import Any, Dict, List, Optional
import os

try:
    import httpx
    HAS_HTTPX = True
except ImportError:
    HAS_HTTPX = False
    httpx = None

try:
    import ollama
    HAS_OLLAMA = True
except (ImportError, ValueError, json.JSONDecodeError) as e:
    # Catch ImportError, ValueError (which includes JSONDecodeError), and JSONDecodeError
    HAS_OLLAMA = False
    ollama = None
    if isinstance(e, json.JSONDecodeError) or "JSON" in str(e) or "Expecting value" in str(e):
        print(f"⚠️  Could not import ollama (JSON parsing error during import): {e}")
    elif isinstance(e, ImportError):
        # Normal import error - library not installed
        pass
    else:
        print(f"⚠️  Unexpected error importing ollama: {e}")

try:
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client
    HAS_MCP = True
except (ImportError, ValueError, json.JSONDecodeError, Exception) as e:
    # Catch ImportError, ValueError (which includes JSONDecodeError), JSONDecodeError, and any other Exception
    HAS_MCP = False
    ClientSession = None
    StdioServerParameters = None
    stdio_client = None
    if isinstance(e, json.JSONDecodeError) or "JSON" in str(e) or "Expecting value" in str(e):
        print(f"⚠️  Could not import mcp (JSON parsing error during import): {e}")
    elif isinstance(e, ImportError):
        # Normal import error - library not installed
        pass
    else:
        print(f"⚠️  Unexpected error importing mcp ({type(e).__name__}): {e}")

# Default configuration - can be overridden via environment variables
DEFAULT_ANYLOG_MCP_SSE_URL = os.getenv("ANYLOG_MCP_SSE_URL", "http://50.116.13.109:32349/mcp/sse")
DEFAULT_OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "qwen2.5:7b-instruct")

def sanitize_json_schema(schema: dict) -> dict:
    """
    Fix common JSON Schema mistakes that break Ollama tool validation.
    - Move 'required' out of properties if incorrectly placed there.
    - Fix properties that are lists instead of proper schema objects.
    - Recursively sanitize nested schemas.
    """
    if not isinstance(schema, dict):
        return {"type": "object", "properties": {}}

    # Make a copy to avoid mutating the original
    schema = dict(schema)
    
    # Recursively sanitize nested schemas (items, properties, etc.)
    if "items" in schema and isinstance(schema["items"], dict):
        schema["items"] = sanitize_json_schema(schema["items"])
    
    if "properties" in schema and isinstance(schema["properties"], dict):
        sanitized_props = {}
        for prop_name, prop_value in schema["properties"].items():
            # Skip 'required' if it's incorrectly nested in properties
            if prop_name == "required" and isinstance(prop_value, list):
                continue
            
            # Fix properties that are lists instead of objects
            if isinstance(prop_value, list):
                # If it's a list, convert to array type with items
                # This handles cases like: "nodes": [{"type": "string"}] 
                # Should become: "nodes": {"type": "array", "items": {"type": "string"}}
                if len(prop_value) > 0 and isinstance(prop_value[0], dict):
                    # Assume it's an array of objects
                    sanitized_props[prop_name] = {
                        "type": "array",
                        "items": sanitize_json_schema(prop_value[0])
                    }
                else:
                    # Fallback: make it a generic array
                    sanitized_props[prop_name] = {
                        "type": "array",
                        "items": {"type": "string"}
                    }
            elif isinstance(prop_value, dict):
                # Recursively sanitize nested property schemas
                sanitized_props[prop_name] = sanitize_json_schema(prop_value)
            else:
                # Keep as-is if it's already a valid type
                sanitized_props[prop_name] = prop_value
        
        schema["properties"] = sanitized_props
    
    # Move 'required' from properties to top-level if incorrectly placed
    props = schema.get("properties", {})
    if isinstance(props, dict) and "required" in props and isinstance(props["required"], list):
        schema_required = props["required"]
        props = dict(props)
        props.pop("required", None)
        schema["properties"] = props
        # Merge/override required at top-level
        if "required" not in schema or not isinstance(schema["required"], list):
            schema["required"] = schema_required
        else:
            # Merge if both exist
            existing = set(schema["required"])
            new = set(schema_required)
            schema["required"] = list(existing | new)

    return schema

def mcp_tools_to_ollama_tools(mcp_tools) -> List[Dict[str, Any]]:
    """
    Convert MCP tool schema to Ollama tool schema:
    Ollama expects: [{"type":"function","function":{"name","description","parameters"}}]
    """
    out = []
    for t in mcp_tools:
        out.append(
            {
                "type": "function",
                "function": {
                    "name": t.name,
                    "description": t.description or "",
                    "parameters": sanitize_json_schema(t.inputSchema or {"type": "object", "properties": {}}),
                },
            }
        )
    return out


async def list_models_from_local_ollama(timeout: float = 10.0) -> List[Dict[str, Any]]:
    """
    List available models from local Ollama installation.
    
    Args:
        timeout: Request timeout in seconds
    
    Returns:
        List of model dictionaries with name, size, etc.
    """
    if not HAS_OLLAMA:
        raise RuntimeError("Ollama is not installed. Please install it with: pip install ollama")
    
    try:
        # Use ollama.list() to get local models
        # This is a sync call, so run it in a thread
        models = await asyncio.to_thread(ollama.list)
        
        # Convert to list of dicts
        model_list = []
        for model in models.get("models", []):
            # Ollama.list() returns models as dicts with 'name' key
            # But let's be defensive and check multiple possible fields
            model_name = (
                model.get("name") or 
                model.get("model") or 
                model.get("model_name") or
                ""
            )
            
            # Debug logging
            if not model_name:
                print(f"⚠️  Warning: Model object has no name. Keys: {list(model.keys()) if isinstance(model, dict) else 'not a dict'}, Full object: {model}")
            else:
                print(f"✅ Found model: {model_name}")
            
            # Only add models that have a name
            if model_name:
                model_list.append({
                    "name": model_name,
                    "model": model_name,  # For consistency with Docker format
                    "size": model.get("size", 0),
                    "modified_at": model.get("modified_at", ""),
                    "details": {
                        "parameter_size": model.get("details", {}).get("parameter_size", ""),
                        "quantization_level": model.get("details", {}).get("quantization_level", ""),
                        "family": model.get("details", {}).get("family", ""),
                    } if model.get("details") else {}
                })
        print(f"📋 Local Ollama models found: {[m['name'] for m in model_list]}")
        
        return model_list
    except Exception as e:
        raise RuntimeError(f"Failed to list models from local Ollama: {str(e)}")


async def list_models_from_docker(endpoint: str, timeout: float = 10.0) -> List[Dict[str, Any]]:
    """
    List available models from a Docker-based Ollama container.
    
    Args:
        endpoint: Base URL of the Ollama container (e.g., "http://localhost:11434")
        timeout: Request timeout in seconds
    
    Returns:
        List of model dictionaries with name, size, etc.
    """
    if not HAS_HTTPX:
        raise RuntimeError("httpx is not installed. Please install it with: pip install httpx")
    
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            # Ollama API endpoint for listing models
            url = f"{endpoint.rstrip('/')}/api/tags"
            response = await client.get(url)
            response.raise_for_status()
            data = response.json()
            models = data.get("models", [])
            print(f"🔍 Docker API response: {data}")
            print(f"🔍 Docker models found: {[m.get('name', m.get('model', 'unknown')) for m in models]}")
            return models
    except httpx.TimeoutException:
        raise RuntimeError(f"Request to Docker Ollama container timed out after {timeout}s")
    except httpx.HTTPStatusError as e:
        raise RuntimeError(f"Docker Ollama container returned error {e.response.status_code}: {e.response.text}")
    except Exception as e:
        raise RuntimeError(f"Failed to list models from Docker container at {endpoint}: {str(e)}")


async def ollama_chat_async(
    model: str,
    messages: List[Dict[str, Any]],
    tools: Optional[List[Dict[str, Any]]] = None,
    stream: bool = False,
    llm_endpoint: Optional[str] = None,
    timeout: float = 300.0  # Increased to 5 minutes to match ask() timeout
) -> Dict[str, Any]:
    """
    Run ollama.chat - supports both local Ollama library and Docker-based Ollama containers.
    
    Args:
        model: Model name to use
        messages: List of message dictionaries
        tools: Optional list of tool definitions
        stream: Whether to stream responses (not supported for Docker yet)
        llm_endpoint: Optional Docker container endpoint (e.g., "http://localhost:11434")
                     If None, uses local Ollama library
        timeout: Request timeout in seconds
    
    Returns:
        Response dictionary with "message" key containing the assistant's response
    """
    # If Docker endpoint is provided, use HTTP API
    if llm_endpoint:
        print(f"🐳 Using Docker LLM endpoint: {llm_endpoint} with model: {model}")
        return await _ollama_chat_docker(llm_endpoint, model, messages, tools, timeout)
    
    # Otherwise, use local Ollama library
    if not HAS_OLLAMA:
        raise RuntimeError("Ollama is not installed. Please install it with: pip install ollama")
    
    if stream:
        raise NotImplementedError("Streaming not yet supported for local Ollama")
    
    # ollama.chat is sync; run it without blocking the event loop
    return await asyncio.to_thread(ollama.chat, model=model, messages=messages, tools=tools, stream=False)


async def _ollama_chat_docker(
    endpoint: str,
    model: str,
    messages: List[Dict[str, Any]],
    tools: Optional[List[Dict[str, Any]]] = None,
    timeout: float = 300.0  # Increased to 5 minutes to match ask() timeout
) -> Dict[str, Any]:
    """
    Call Ollama API via HTTP to a Docker container.
    Handles streaming response format (multiple JSON objects).
    
    Args:
        endpoint: Base URL of the Ollama container (e.g., "http://localhost:11434")
        model: Model name
        messages: List of message dictionaries
        tools: Optional list of tool definitions
        timeout: Request timeout in seconds
    
    Returns:
        Response dictionary compatible with local Ollama format
    """
    if not HAS_HTTPX:
        raise RuntimeError("httpx is not installed. Please install it with: pip install httpx")
    
    try:
        # Set timeout for both connect and read operations
        # httpx timeout: (connect timeout, read timeout, write timeout, pool timeout)
        httpx_timeout = httpx.Timeout(timeout, connect=10.0, read=timeout, write=30.0, pool=10.0)
        
        async with httpx.AsyncClient(timeout=httpx_timeout) as client:
            # Ollama API endpoint for chat
            url = f"{endpoint.rstrip('/')}/api/chat"
            
            payload = {
                "model": model,
                "messages": messages,
                "stream": False  # Non-streaming response
            }
            
            print(f"🐳 Docker LLM Request - URL: {url}, Model: {model}, Messages: {len(messages)}")
            
            if tools:
                payload["tools"] = tools
            
            # When stream=False, Ollama returns a single JSON object
            # Use regular POST request instead of streaming
            response = await client.post(url, json=payload, timeout=timeout)
            
            print(f"🐳 Docker LLM Response - Status: {response.status_code}")
            
            # Check for errors
            if response.status_code != 200:
                try:
                    error_json = response.json()
                    error_msg = error_json.get("error", {}).get("message", str(error_json)) if isinstance(error_json, dict) else str(error_json)
                except Exception:
                    error_msg = response.text or f"HTTP {response.status_code}"
                
                # Check if error is about tools not being supported
                error_lower = error_msg.lower()
                if "does not support tools" in error_lower or ("tool" in error_lower and "not support" in error_lower):
                    # MCP agent requires tools to function, so we can't proceed without them
                    if tools:
                        raise RuntimeError(
                            f"Model '{model}' does not support function calling (tools), which is required for MCP. "
                            f"Please use a model that supports tools, such as 'qwen2.5:7b-instruct' or other instruction-tuned models. "
                            f"Original error: {error_msg}"
                        )
                    else:
                        # Tools weren't used, so this is a different error
                        raise RuntimeError(f"Docker Ollama container returned error {response.status_code}: {error_msg}")
                else:
                    # Different error, raise normally
                    raise RuntimeError(f"Docker Ollama container returned error {response.status_code}: {error_msg}")
            
            # Parse the JSON response (single object when stream=False)
            try:
                response_json = response.json()
            except Exception as e:
                raise RuntimeError(f"Failed to parse Docker LLM response as JSON: {str(e)}")
            
            # Extract message content
            # Response format: {"model": "...", "message": {"role": "assistant", "content": "..."}, "done": true, ...}
            if "message" not in response_json:
                raise RuntimeError("Docker LLM response missing 'message' field")
            
            msg = response_json["message"]
            content = msg.get("content", "")
            
            # Build result message
            result_message = {
                "role": msg.get("role", "assistant"),
                "content": content or ""
            }
            
            # Check for tool calls
            if "tool_calls" in msg:
                result_message["tool_calls"] = msg["tool_calls"]
                print(f"🐳 Docker LLM Response - Found {len(msg.get('tool_calls', []))} tool call(s)")
            else:
                print(f"🐳 Docker LLM Response - No tool_calls in response (model may not be making tool calls)")
            
            print(f"🐳 Docker LLM Response - Total content length: {len(content)} chars")
            
            if not content:
                print(f"⚠️  Warning: Docker LLM returned empty content. Response structure: {list(response_json.keys())}")
            
            return {
                "message": result_message
            }
                
    except httpx.TimeoutException:
        raise RuntimeError(f"Request to Docker Ollama container timed out after {timeout}s")
    except httpx.HTTPStatusError as e:
        # Extract error message from response
        error_text = e.response.text
        try:
            error_json = e.response.json()
            error_msg = error_json.get("error", {}).get("message", error_text) if isinstance(error_json, dict) else error_text
        except:
            error_msg = error_text
        raise RuntimeError(f"Docker Ollama container returned error {e.response.status_code}: {error_msg}")
    except Exception as e:
        raise RuntimeError(f"Failed to communicate with Docker Ollama container: {str(e)}")


class AnyLogMCPAgent:
    def __init__(
        self,
        anylog_sse_url: str,
        ollama_model: str = DEFAULT_OLLAMA_MODEL,
        llm_endpoint: Optional[str] = None
    ):
        self.anylog_sse_url = anylog_sse_url
        self.ollama_model = ollama_model
        self.llm_endpoint = llm_endpoint  # Docker container endpoint (e.g., "http://localhost:11434")
        self.session: Optional[ClientSession] = None
        self.exit_stack: Optional[AsyncExitStack] = None
        self.stdio = None
        self.write = None
        self.cached_tools: List[str] = []  # Cache tools to avoid redundant API calls

    async def connect(self, timeout: float = 10.0):
        """Connect to AnyLog MCP server via mcp-proxy with timeout"""
        if not HAS_MCP:
            raise RuntimeError("MCP libraries are not installed. Please install them with: pip install mcp")
        
        # Create a new exit stack for this connection
        self.exit_stack = AsyncExitStack()
        
        # Start mcp-proxy as a stdio "server" process that bridges to remote SSE
        server_params = StdioServerParameters(
            command="mcp-proxy",
            args=[self.anylog_sse_url],  # stdio -> remote SSE
            env=None,
        )
        
        # Connect with timeout to prevent hanging
        try:
            stdio_transport = await asyncio.wait_for(
                self.exit_stack.enter_async_context(stdio_client(server_params)),
                timeout=timeout
            )
            self.stdio, self.write = stdio_transport
            self.session = await asyncio.wait_for(
                self.exit_stack.enter_async_context(ClientSession(self.stdio, self.write)),
                timeout=timeout
            )
            await asyncio.wait_for(self.session.initialize(), timeout=timeout)

            # Cache tools for fast status checks (with timeout)
            tools_resp = await asyncio.wait_for(self.session.list_tools(), timeout=timeout)
            self.cached_tools = [t.name for t in tools_resp.tools]
            return self.cached_tools
        except asyncio.TimeoutError:
            # Clean up on timeout
            try:
                await self.close()
            except Exception:
                pass
            raise RuntimeError(f"Connection timeout after {timeout}s. MCP server may be unreachable or overloaded.")

    async def health_check(self, timeout: float = 3.0) -> bool:
        """Verify the MCP connection is actually working with timeout"""
        if not self.session:
            return False
        
        try:
            # Try a lightweight operation to verify connection is alive
            # Use a short timeout to avoid blocking
            await asyncio.wait_for(self.session.list_tools(), timeout=timeout)
            return True
        except (asyncio.TimeoutError, Exception) as e:
            # Connection is dead, mark as disconnected
            print(f"Health check failed: {e}")
            return False

    async def ask(self, user_prompt: str, conversation_history: Optional[List[Dict[str, str]]] = None, timeout: float = 300.0) -> str:
        """Ask a question to the MCP agent using Ollama with timeout and conversation history"""
        if not self.session:
            raise RuntimeError("Not connected. Call connect() first.")
        
        # Check if we have a way to call LLM (either local Ollama or Docker endpoint)
        if not self.llm_endpoint and not HAS_OLLAMA:
            raise RuntimeError(
                "No LLM available. Either install Ollama locally (pip install ollama) "
                "or provide a Docker container endpoint (llm_endpoint parameter)."
            )

        print(f"⏱️  Starting ask() with timeout={timeout}s")
        start_time = asyncio.get_event_loop().time()
        
        try:
            # Pull MCP tools and expose them to Ollama as tool schemas (with timeout)
            print(f"🔍 Fetching MCP tools...")
            tools_resp = await asyncio.wait_for(self.session.list_tools(), timeout=10.0)
            ollama_tools = mcp_tools_to_ollama_tools(tools_resp.tools)
            print(f"🛠️  Loaded {len(ollama_tools)} MCP tools: {[t['function']['name'] for t in ollama_tools]}")
            elapsed = asyncio.get_event_loop().time() - start_time
            print(f"⏱️  Tool fetching took {elapsed:.2f}s")

            # Build message history with system prompt
            messages: List[Dict[str, Any]] = [
                {
                    "role": "system",
                    "content": (
                        "You are a maintenance copilot for PLC-controlled units. "
                        "You cannot access AnyLog data unless you call tools. "
                        "ALWAYS call tools to fetch facts before concluding. "
                        "If the user asks about trends or anomalies, call executeQuery or queryWithIncrement. "
                        "Never guess signal values. "
                        "If required identifiers are missing, ask for dbms/table/unit/device."
                    ),
                },
            ]
            
            # Add conversation history (limit to last 10 exchanges = 20 messages for efficiency)
            if conversation_history:
                # Take last 20 messages to keep context manageable for small LLMs
                recent_history = conversation_history[-20:]
                for msg in recent_history:
                    # Only include user and assistant messages, skip errors
                    if msg.get("role") in ["user", "assistant"]:
                        messages.append({
                            "role": msg.get("role"),
                            "content": msg.get("content", "")
                        })
            
            # Add current user prompt
            messages.append({"role": "user", "content": user_prompt})

            # Agent loop: model decides tool calls; we execute them via MCP; feed results back
            # Wrap entire loop in timeout to prevent hanging
            print(f"🔄 Starting agent loop with {len(messages)} messages...")
            try:
                result = await asyncio.wait_for(self._agent_loop(messages, ollama_tools), timeout=timeout)
                elapsed = asyncio.get_event_loop().time() - start_time
                print(f"✅ Agent loop completed in {elapsed:.2f}s")
                return result
            except asyncio.TimeoutError:
                elapsed = asyncio.get_event_loop().time() - start_time
                print(f"❌ Request timed out after {elapsed:.2f}s (limit: {timeout}s)")
                raise RuntimeError(f"Request timed out after {timeout}s. The MCP server may be overloaded or unresponsive. Elapsed time: {elapsed:.2f}s")
        except asyncio.TimeoutError:
            elapsed = asyncio.get_event_loop().time() - start_time
            print(f"❌ Operation timed out after {elapsed:.2f}s")
            raise

    async def _agent_loop(self, messages: List[Dict[str, Any]], ollama_tools: List[Dict[str, Any]]) -> str:
        """Internal agent loop with timeouts on individual operations"""
        print(f"🔧 Agent loop starting with {len(ollama_tools)} tools available")
        for iteration in range(12):  # safety loop cap
            iteration_start = asyncio.get_event_loop().time()
            print(f"🔄 Agent loop iteration {iteration + 1}/12")
            print(f"⏱️  Calling LLM ({self.ollama_model})...")
            resp = await ollama_chat_async(
                model=self.ollama_model,
                messages=messages,
                tools=ollama_tools,
                stream=False,
                llm_endpoint=self.llm_endpoint,
            )
            iteration_elapsed = asyncio.get_event_loop().time() - iteration_start
            print(f"⏱️  LLM call completed in {iteration_elapsed:.2f}s")

            msg = resp["message"]
            messages.append(msg)
            
            # Debug: Log what we received
            print(f"📥 LLM Response - Content length: {len(msg.get('content', ''))}")
            print(f"📥 LLM Response - Has tool_calls: {bool(msg.get('tool_calls'))}")
            if msg.get("tool_calls"):
                print(f"📥 LLM Response - Tool calls: {len(msg.get('tool_calls', []))}")
                for tc in msg.get("tool_calls", []):
                    print(f"   - Tool: {tc.get('function', {}).get('name', 'unknown')}")

            tool_calls = msg.get("tool_calls") or []
            if not tool_calls:
                print(f"⚠️  No tool calls detected. Model returned direct answer (may be too small or not understanding tool usage)")
                content_preview = msg.get('content', '')[:200]
                print(f"   Response preview: {content_preview}...")
                return msg.get("content", "")

            # Execute each tool call against AnyLog MCP (with timeout per call)
            print(f"🔨 Executing {len(tool_calls)} tool call(s)")
            for tc in tool_calls:
                fn = tc["function"]
                tool_name = fn["name"]
                tool_args = fn.get("arguments") or {}
                print(f"🔨 Calling tool: {tool_name} with args: {tool_args}")
                if isinstance(tool_args, str):
                    try:
                        # Handle empty string or invalid JSON
                        if not tool_args.strip():
                            tool_args = {}
                        else:
                            tool_args = json.loads(tool_args)
                    except (json.JSONDecodeError, ValueError) as e:
                        # If JSON parsing fails, log and use empty dict
                        print(f"⚠️  Warning: Failed to parse tool arguments as JSON for {tool_name}: {e}")
                        print(f"   Raw arguments: {tool_args}")
                        tool_args = {}

                try:
                    tool_start = asyncio.get_event_loop().time()
                    print(f"⏱️  Calling tool '{tool_name}'...")
                    result = await asyncio.wait_for(
                        self.session.call_tool(tool_name, tool_args),
                        timeout=60.0  # 60s timeout per tool call (increased from 30s)
                    )
                    tool_elapsed = asyncio.get_event_loop().time() - tool_start
                    print(f"✅ Tool '{tool_name}' completed in {tool_elapsed:.2f}s")
                except asyncio.TimeoutError:
                    tool_elapsed = asyncio.get_event_loop().time() - tool_start
                    print(f"❌ Tool call '{tool_name}' timed out after {tool_elapsed:.2f}s")
                    raise RuntimeError(f"Tool call '{tool_name}' timed out after 60s. The MCP server may be overloaded or unresponsive.")

                # Feed tool result back to the model
                messages.append(
                    {
                        "role": "tool",
                        "tool_name": tool_name,
                        "content": json.dumps(result.model_dump() if hasattr(result, "model_dump") else result, default=str),
                    }
                )

        return "Stopped (too many tool-call iterations). Try narrowing the question."

    async def close(self, timeout: float = 5.0):
        """Close the MCP connection with timeout"""
        try:
            # Close the exit stack if it exists (with timeout)
            if self.exit_stack is not None:
                try:
                    await asyncio.wait_for(self.exit_stack.aclose(), timeout=timeout)
                except asyncio.TimeoutError:
                    # Force cleanup on timeout
                    print(f"Warning: Connection close timed out after {timeout}s, forcing cleanup")
                except RuntimeError as e:
                    # Handle "Attempted to exit cancel scope in a different task" error
                    # This happens when AsyncExitStack is closed from a different async task
                    # than where it was created. We'll just reset the state.
                    error_msg = str(e).lower()
                    if "different task" in error_msg or "cancel scope" in error_msg:
                        # Can't clean up properly from different task, just reset state
                        pass
                    else:
                        raise
                except Exception:
                    # Other errors - just reset state
                    pass
                finally:
                    self.exit_stack = None
            
            # Reset all state
            self.session = None
            self.stdio = None
            self.write = None
            self.cached_tools = []
        except Exception:
            # Ensure state is reset even if cleanup fails
            self.session = None
            self.exit_stack = None
            self.stdio = None
            self.write = None
            self.cached_tools = []

