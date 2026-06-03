# Remote-GUI

## Overview

The **Remote-GUI** is a command-line and web-based interface tool designed to simplify and automate tasks for local development.  
This guide will help you set up and run the project on your machine.

* [Documentation](#)
* [Dockerization](#dockerization)
  * [Package Docker](#package-docker-image)
  * [Run Image](#run-docker-image)
* [Prerequisites](#prerequisites)
* [Backend](#backend)
* [Frontend](#frontend)
* [Supabase](#supabase)
* [Anylog API](#anylog-api)
* [Usage](#usage)
* [Feature Docs](#feature-docs)

---

## Dockerization

### Package Docker Image

```bash
docker build -f Dockerfile . -t anylogco/remote-gui:latest
```

### Run Docker Image

**Volumes used:**  
- `image-vol:/app/CLI/local-cli-backend/static/` – stores images retrieved via query requests  
- `usr-mgm-vol:/app/CLI/local-cli/backend/usr-mgm/` – stores configurations and management files  

**Basic Docker Run:**

```bash
docker run -it -p 8000:8000 -p 3001:3001 --name gui-1 --rm anylogco/remote-gui
```

**Docker Compose:**

```bash
docker compose -f ./docker-compose.yaml up -d
```

---

## Prerequisites

Before you begin, ensure you have the following installed:

- [Node.js](https://nodejs.org/) (version 14 or higher)
- [npm](https://www.npmjs.com/) or [yarn](https://yarnpkg.com/)
- [Python 3](https://www.python.org/)
- A terminal or command-line interface

---

## Backend

1. Inside the `Local-CLI` directory, cd into `local-cli-backend`:
    ```bash
    python -m venv .
    ```

2. Activate the virtual environment:
    - Windows:
        ```bash
        .\venv\Scripts\activate
        ```
    - macOS/Linux:
        ```bash
        source ./venv/bin/activate
        ```

3. Install the required packages:
    ```bash
    pip install -r reqs.txt
    ```

   Additional useful packages:
    ```bash
    pip install python-dotenv psycopg2 psycopg2-binary
    ```

4. Run the backend server:
    ```bash
    fastapi dev main.py

    # Run on cloud
    fastapi dev CLI/Local_CLI/local_cli_backend/main.py --host 0.0.0.0 --port 8000
    ```

5. The backend server should now be running at:  
   👉 `http://127.0.0.1:8000`

---

## Frontend

1. Inside the `Local-CLI` directory, cd into `local-cli-fe-full` and install dependencies:
    ```bash
    npm install
    ```

2. Start the frontend server:
    ```bash
    npm start
    ```

   On Ubuntu:
    ```bash
    export NODE_OPTIONS=--openssl-legacy-provider
    npm start
    ```

3. Open your browser and go to 👉 `http://localhost:3000`

---

## Supabase

(Documentation pending – to be expanded in future versions.)

---

## Anylog API

Follow the instructions from the [AnyLog API GitHub Repository](https://github.com/AnyLog-co/AnyLog-API/tree/main).  

Run this while the backend venv is activated:

```bash
python3 -m pip install $HOME/AnyLog-API/dist/anylog_api-0.0.0-py2.py3-none-any.whl
```

---

## Usage

You can connect to a node in two ways:

- **Local node (via Docker Compose):** use the IP and port from the container (usually `127.0.0.1:32049`).  
- **Hosted node:** use `23.239.12.151:32349`.

---

## Docker (Alternative Build/Run)

1. Build:
   ```bash
   docker build -f Dockerfile . -t gui
   ```

2. Run (local):
   ```bash
   docker run -it --rm -p 8000:8000 -p 3001:3001      -e REACT_APP_API_URL=http://127.0.0.1:8000      --name gui oshadmon/gui:test
   ```

3. Run (production):
   ```bash
   docker run -d      --name gui      -p 8000:8000      -p 3001:3001      -e REACT_APP_API_URL=http://${EXTERNAL_IP}:8000      -e FRONTEND_URL=http://${EXTERNAL_IP}:3001      oshadmon/gui:test
   ```

---

# Feature Docs

## Client

(Coming soon)

## Monitor

(Coming soon)

## Policies

(Coming soon)

## AddData

(Coming soon)
