# Running LLMs in Docker - Setup Guide

## Overview

This guide explains how to run LLMs in Docker containers and access them from the MCP Client plugin. There are two main approaches:

1. **Docker Model Runner** (Docker Desktop 4.40+ on macOS Apple Silicon)
2. **Standalone Docker Containers** (Ollama, vLLM, etc.)

---

## Approach 1: Docker Model Runner (Recommended for macOS)

Docker Model Runner is integrated into Docker Desktop and provides an OpenAI-compatible API.

### Prerequisites

- Docker Desktop 4.40+ for macOS on Apple Silicon
- Model Runner enabled in Docker Desktop

### Step 1: Enable Docker Model Runner

```bash
# Enable Model Runner (default: accessible via Docker socket)
docker desktop enable model-runner

# OR enable with TCP access (for host processes)
docker desktop enable model-runner --tcp 12434
```

### Step 2: Pull a Model

```bash
# Pull a small model for testing (SmolLM2 with 360M parameters, 4-bit quantized)
docker model pull ai/smollm2:360M-Q4_K_M

# Or pull other models from Docker Hub (ai/ namespace)
docker model pull ai/llama3.2:3B-Q4_K_M
docker model pull ai/mistral:7B-Q4_K_M
```

**Model Tag Format**: `{model}:{parameters}-{quantization}`
- Example: `ai/smollm2:360M-Q4_K_M` = SmolLM2 model, 360M parameters, 4-bit quantization

### Step 3: Test the Model

```bash
# Run a quick test
docker model run ai/smollm2:360M-Q4_K_M "Give me a fact about whales."
```

### Step 4: Access the API

**From within containers:**
- Endpoint: `http://model-runner.docker.internal/engines/v1`
- Model name: `ai/smollm2:360M-Q4_K_M`

**From host processes (if TCP enabled):**
- Endpoint: `http://localhost:12434/engines/v1`
- Model name: `ai/smollm2:360M-Q4_K_M`

### Step 5: Verify API is Working

```bash
# Test with curl (if TCP enabled)
curl http://localhost:12434/engines/v1/models

# Or test a chat completion
curl -X POST http://localhost:12434/engines/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{
    "model": "ai/smollm2:360M-Q4_K_M",
    "messages": [{"role": "user", "content": "Hello!"}]
  }'
```

**Note**: The model must be pulled locally before use. Model Runner loads models on-demand and keeps them in memory for 5 minutes of inactivity.

---

## Approach 2: Standalone Docker Containers

### Option A: Ollama in Docker

#### Step 1: Run Ollama Container

```bash
# Run Ollama in Docker with isolated storage
# The volume 'ollama-data' is a Docker volume (separate from ~/.ollama)
docker run -d \
  --name ollama \
  -p 11434:11434 \
  -v ollama-data:/root/.ollama \
  ollama/ollama

# Pull a model (this only downloads to the Docker container, NOT your local Ollama)
docker exec -it ollama ollama pull qwen2.5:7b-instruct

# Pull other models
docker exec -it ollama ollama pull tinyllama:latest
docker exec -it ollama ollama pull llama3.1:8b-instruct
```

**Important**: The `ollama-data` volume is a **Docker named volume** stored at `/var/lib/docker/volumes/ollama-data/_data`, which is completely separate from your local `~/.ollama` directory.

**If models appear in both places**, it's likely because:
- Your local `ollama` CLI is connecting to the Docker container on port 11434
- To use local Ollama separately, either:
  - Stop the Docker container: `docker stop ollama`
  - Or use a different port for Docker: `-p 11435:11434` (then use `http://localhost:11435` in the MCP client)

#### Step 2: Access Ollama API

- **If using Option A (different port)**: Endpoint: `http://localhost:11435`
- **If using Option B (same port)**: Endpoint: `http://localhost:11434`
- API: OpenAI-compatible at `/api/chat`
- Model: `qwen2.5:7b-instruct`

**Important**: Use the correct port in the MCP Client's Docker LLM Endpoint field!

#### Step 3: Test the API

```bash
curl http://localhost:11434/api/tags  # List models

curl http://localhost:11434/api/chat \
  -H "Content-Type: application/json" \
  -d '{
    "model": "qwen2.5:7b-instruct",
    "messages": [{"role": "user", "content": "Hello!"}]
  }'
```

> **Tip: Fast, Small Models**
>
> For the **fastest** and **smallest** LLM that works well for local/Docker testing and low resource usage, try:
>
> - **For Docker Model Runner:**
>   - `ai/smollm2:360M-Q4_K_M` &nbsp; ← (~0.5GB RAM; very quick responses, suitable for sanity checks and development)
>   - Command:  
>     ```
>     docker model pull ai/smollm2:360M-Q4_K_M
>     ```
>
> - **For Ollama:**  
>   - `tinyllama:latest`  (~1.1GB RAM)  
>   - Command:  
>     ```
>     docker exec -it ollama ollama pull tinyllama:latest
>     ```
>
> **Note:** These small models are not as capable as larger models, but are great for testing infrastructure, low latency experiments, and environments with limited resources.


### Option B: vLLM (for GPU acceleration)

```bash
# Run vLLM container
docker run --gpus all \
  -p 8000:8000 \
  -v ~/.cache/huggingface:/root/.cache/huggingface \
  vllm/vllm-openai:latest \
  --model meta-llama/Llama-3.2-3B-Instruct

# Access at http://localhost:8000/v1/chat/completions
```

### Option C: Other LLM Containers

Many LLM providers offer Docker containers:
- **Text Generation Inference (TGI)**: HuggingFace's inference server
- **LocalAI**: OpenAI-compatible API server
- **LM Studio**: Desktop app with Docker support

---

## Integration with MCP Client

### Current Implementation

The MCP Client currently uses the `ollama` Python library, which connects to:
- Default: `http://localhost:11434` (Ollama service)

### Required Changes

To support Docker-based LLMs, we need to:

1. **Add configuration option** for LLM endpoint (instead of hardcoded Ollama)
2. **Support OpenAI-compatible API** (Docker Model Runner and many containers use this)
3. **Update `ollama_chat_async()`** to use HTTP client instead of `ollama` library when Docker endpoint is specified

### Proposed Architecture

```
User Configuration:
  - LLM Type: "ollama" | "docker-model-runner" | "docker-container" | "openai-compatible"
  - LLM Endpoint: "http://localhost:11434" | "http://localhost:12434/engines/v1" | "http://<ip>:<port>"
  - Model Name: "qwen2.5:7b-instruct" | "ai/smollm2:360M-Q4_K_M" | etc.

Backend Logic:
  - If LLM Type == "ollama": Use ollama library (current behavior)
  - If LLM Type == "docker-model-runner" or "openai-compatible": Use HTTP client with OpenAI API format
  - If LLM Type == "docker-container": Use HTTP client with container endpoint
```

---

## Testing Checklist

### Docker Model Runner
- [ ] Enable Model Runner in Docker Desktop
- [ ] Pull a test model (`ai/smollm2:360M-Q4_K_M`)
- [ ] Verify API is accessible at `http://localhost:12434/engines/v1`
- [ ] Test chat completion endpoint
- [ ] Verify model loads on-demand

### Ollama in Docker
- [ ] Run Ollama container
- [ ] Pull a model inside container
- [ ] Verify API at `http://localhost:11434`
- [ ] Test chat completion
- [ ] Verify persistence (volumes)

### Integration
- [ ] Update MCP Client to accept LLM endpoint configuration
- [ ] Add OpenAI-compatible API client
- [ ] Test with a simple chat completion