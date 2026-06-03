// MCP Client Plugin API
// API client for MCP Client plugin

const API_URL = window._env_?.REACT_APP_API_URL || "http://localhost:8000";

/**
 * Get MCP client information
 */
export const getMCPClientInfo = async () => {
  try {
    const response = await fetch(`${API_URL}/mcpclient/`);
    if (!response.ok) {
      throw new Error(`HTTP error! status: ${response.status}`);
    }
    return await response.json();
  } catch (error) {
    console.error('Error fetching MCP client info:', error);
    throw error;
  }
};

/**
 * Get MCP client status
 */
export const getMCPStatus = async () => {
  try {
    const response = await fetch(`${API_URL}/mcpclient/status`);
    if (!response.ok) {
      throw new Error(`HTTP error! status: ${response.status}`);
    }
    return await response.json();
  } catch (error) {
    console.error('Error fetching MCP status:', error);
    throw error;
  }
};

/**
 * List available models from Docker Ollama container or local Ollama
 */
export const listModels = async (llmEndpoint = null) => {
  try {
    const url = llmEndpoint 
      ? `${API_URL}/mcpclient/models?llm_endpoint=${encodeURIComponent(llmEndpoint)}`
      : `${API_URL}/mcpclient/models`;
    const response = await fetch(url);
    if (!response.ok) {
      const error = await response.json();
      throw new Error(error.detail || `HTTP error! status: ${response.status}`);
    }
    return await response.json();
  } catch (error) {
    console.error('Error listing models:', error);
    throw error;
  }
};

/**
 * @deprecated Use listModels instead
 * List available models from a Docker Ollama container
 */
export const listModelsFromDocker = async (llmEndpoint) => {
  return listModels(llmEndpoint);
};

/**
 * Connect to AnyLog MCP
 */
export const connectMCP = async (anylogSseUrl = null, ollamaModel = null, llmEndpoint = null) => {
  try {
    const response = await fetch(`${API_URL}/mcpclient/connect`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
      },
      body: JSON.stringify({
        anylog_sse_url: anylogSseUrl,
        ollama_model: ollamaModel,
        llm_endpoint: llmEndpoint,
      }),
    });
    if (!response.ok) {
      let errorMessage = `HTTP error! status: ${response.status}`;
      try {
        const error = await response.json();
        errorMessage = error.detail || error.message || errorMessage;
      } catch (parseError) {
        // If JSON parsing fails, try to get text
        try {
          const text = await response.text();
          if (text) errorMessage = text;
        } catch (textError) {
          // Use default error message
        }
      }
      throw new Error(errorMessage);
    }
    return await response.json();
  } catch (error) {
    console.error('Error connecting to MCP:', error);
    // Ensure we always throw an Error object with a message
    if (error instanceof Error) {
      throw error;
    } else {
      throw new Error(String(error));
    }
  }
};

/**
 * Disconnect from AnyLog MCP
 */
export const disconnectMCP = async () => {
  try {
    const response = await fetch(`${API_URL}/mcpclient/disconnect`, {
      method: 'POST',
    });
    if (!response.ok) {
      const error = await response.json();
      throw new Error(error.detail || `HTTP error! status: ${response.status}`);
    }
    return await response.json();
  } catch (error) {
    console.error('Error disconnecting from MCP:', error);
    throw error;
  }
};

/**
 * List available MCP tools
 */
export const listMCPTools = async () => {
  try {
    const response = await fetch(`${API_URL}/mcpclient/tools`);
    if (!response.ok) {
      const error = await response.json();
      throw new Error(error.detail || `HTTP error! status: ${response.status}`);
    }
    return await response.json();
  } catch (error) {
    console.error('Error listing MCP tools:', error);
    throw error;
  }
};

/**
 * Ask a question to the MCP agent
 */
export const askMCP = async (prompt, anylogSseUrl = null, ollamaModel = null, conversationHistory = null, llmEndpoint = null, abortSignal = null) => {
  try {
    console.log('🌐 Sending request to MCP...');
    const response = await fetch(`${API_URL}/mcpclient/ask`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
      },
      body: JSON.stringify({
        prompt,
        anylog_sse_url: anylogSseUrl,
        ollama_model: ollamaModel,
        conversation_history: conversationHistory,
        llm_endpoint: llmEndpoint,
      }),
      signal: abortSignal,
    });
    console.log('🌐 Response status:', response.status, response.statusText);
    if (!response.ok) {
      const error = await response.json();
      console.error('❌ HTTP error response:', error);
      throw new Error(error.detail || `HTTP error! status: ${response.status}`);
    }
    const result = await response.json();
    console.log('🌐 Response JSON received:', {
      hasAnswer: !!result.answer,
      hasSuccess: !!result.success,
      keys: Object.keys(result)
    });
    return result;
  } catch (error) {
    console.error('❌ Error asking MCP:', error);
    throw error;
  }
};

