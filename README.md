# TestZeus Hercules MCP Server

## Overview

TestZeus Hercules is a powerful Model Context Protocol (MCP) server that orchestrates automated test execution through a streamlined API. It specializes in template-based test management, real-time execution monitoring, and comprehensive result tracking.

The server provides a set of operations through the MCP adapter that allow clients to interact with the test execution framework, manage test definitions, and retrieve results.

## Core Technologies

* **Python 3.x**
* **FastAPI**: For building the high-performance API
* **FastApiMCP**: Extension for MCP server integration
* **Pydantic**: For data validation and settings management
* **Uvicorn**: As the ASGI server
* **SQLite**: For storing execution history, test results, and metadata
* **WebSockets**: For real-time logging

## MCP Operations

The TestZeus Hercules MCP server exposes the following operations through the MCP adapter:

### 1. `getAllTestDefinitionData`

**Endpoint**: `GET /test-definition-data`

**Purpose**: Retrieve complete content of all feature files and test data templates from the library.

**Features**:
- Scans feature files from the `data/manager/lib/features/` directory
- Retrieves test data files from the `data/manager/lib/test_data/` directory
- Provides both relative and absolute file paths
- Includes full content of each file with binary detection

**Response Structure**:
```json
{
  "feature_data_list": [
    {
      "path": "basic/login.feature",
      "content": "Feature: Login Test\n...",
      "is_binary": false
    }
  ],
  "test_data_list": [
    {
      "path": "credentials.txt",
      "content": "username=admin\npassword=secret",
      "is_binary": false
    }
  ]
}
```

### 2. `getExecutionList`

**Endpoint**: `GET /executions`

**Purpose**: Retrieve all test executions with optional filtering.

**Parameters**:
- `status` (optional): Filter by status (running, pending, completed, failed)

**Features**:
- Filter by execution status
- Automatic status validation and correction
- Progress tracking with completion statistics
- Source differentiation (memory vs database records)

**Response Structure**:
```json
{
  "executions": [
    {
      "execution_id": "12345-uuid",
      "status": "completed",
      "start_time": "2025-05-13T10:00:00",
      "end_time": "2025-05-13T10:05:00",
      "test_count": 3,
      "completed_tests": 3,
      "tests": [...]
    }
  ]
}
```

### 3. `getExecutionDetails`

**Endpoint**: `GET /executions/{execution_id}`

**Purpose**: Get comprehensive information about a specific test execution.

**Parameters**:
- `execution_id`: ID of the execution to retrieve details for

**Features**:
- Test execution status and timeline
- XML result analysis with pass/fail determination
- Database records of all associated tests
- Step-by-step execution details
- Test summary and final responses

**Response Structure**:
```json
{
  "execution_id": "12345-uuid",
  "status": "completed",
  "test_passed": true,
  "test_summary": "All tests passed successfully",
  "xml_results": [...],
  "database_records": [...],
  "completed_tests": 3,
  "total_tests": 3
}
```

### 4. `runningATemplate`

**Endpoint**: `POST /tests/run-from-template-new`

**Purpose**: Execute tests using predefined templates or custom scripts.

**Request Body**: Array of test configurations with the following structure:
```json
[
  {
    "order": 0,
    "feature": {
      "templatePath": "login/oauth.feature"
    },
    "testData": [
      {"templatePath": "prod_credentials.txt"}
    ],
    "headless": true,
    "timeout": 600,
    "browser": "chromium"
  }
]
```

**Features**:
- Support for feature templates and custom Gherkin scripts
- Data-driven testing with template substitution
- Multiple browser support (Chrome, Firefox, Safari)
- Environment-specific execution (dev, staging, production)
- Mock mode for testing without actual execution
- Parallel test execution with unique directory management

**Response Structure**:
```json
{
  "execution_id": "12345-uuid",
  "status": "pending",
  "start_time": "2025-05-13T10:00:00",
  "message": "Execution scheduled",
  "wsUrl": "ws://127.0.0.1:8003/ws/logs/12345-uuid"
}
```

**Additional Notes**:
- The `wsUrl` field provides a WebSocket URL to monitor the progress of the execution in real-time
- This WebSocket can be accessed using tools like `websocat`: `websocat ws://127.0.0.1:8003/ws/logs/12345-uuid`

### 5. `bulkUploadTestDefinitionFiles`

**Endpoint**: `POST /bulk-upload-files1`

**Purpose**: Upload multiple test files in a single operation.

**Request Body**: Array of file objects with the following structure:
```json
[
  {
    "path": "relative path within the appropriate directory",
    "type": "feature|test_data",
    "content": "The full text content of the file"
  }
]
```

**Features**:
- Upload multiple feature files and test data files in one request
- Save files to appropriate directories based on type (`feature` or `test_data`)
- Path sanitization for security
- Automatic parent directory creation
- Detailed success/failure reporting for each file

**Response Structure**:
```json
{
  "operation_id": "12345-uuid",
  "total_files": 5,
  "successful": 4,
  "failed": 1,
  "results": [
    {
      "path": "basic/login.feature",
      "status": "success",
      "message": "File successfully written to /path/to/file"
    }
  ]
}
```

### 6. `getTestChecking`

**Endpoint**: `GET /test/checking`

**Purpose**: Health check endpoint for the server.

**Features**:
- Simple ping check to verify server is running
- No parameters required

**Response Structure**:
```json
{
  "status": "ok",
  "message": "Server is running"
}
```

### 7. `main_op`

**Endpoint**: `GET /`

**Purpose**: Root endpoint that provides basic information about the server.

**Response Structure**:
```json
{
  "name": "TestZeus Hercules MCP Server",
  "version": "1.0.0",
  "status": "running"
}
```

## WebSocket Endpoints

In addition to the REST API endpoints, the server provides WebSocket endpoints for real-time logging:

### Global Logging

**Endpoint**: `ws://<host>:<port>/ws/logs`

**Purpose**: Stream logs from all executions in real-time.

### Execution-specific Logging

**Endpoint**: `ws://<host>:<port>/ws/logs/{execution_id}`

**Purpose**: Stream logs from a specific execution in real-time.

**Parameters**:
- `execution_id`: ID of the execution to stream logs from

## Setup and Running

1. **Prerequisites**:
   * Python 3.10 (recommended)

2. **Create and Activate Virtual Environment**:
   ```bash
   # Create a virtual environment with Python 3.10
   python3.10 -m venv venv
   
   # Activate the virtual environment
   source venv/bin/activate  # On Windows: venv\Scripts\activate
   ```

3. **Install Dependencies**:
   ```bash
   # After activating the virtual environment
   pip install -r requirements.txt
   ```

3. **Configure Environment Variables**:
   * Create a `.env` file with the required configuration:
   ```env
   DATA_DIR=./data
   ```

4. **Run the Server**:
   ```bash
   python server.py
   ```
   The server will start on the configured host and port (default: 127.0.0.1:8003).

## Using the MCP Client

### MCP Connection Configuration

To connect to the TestZeus Hercules MCP server, you can use the following configuration in your MCP client settings:

```json
{
  "hercules": {
    "name": "DemoStreamable",
    "transport": "streamable-http",
    "url": "http://localhost:8000/mcp",
    "headers": {
      "Mcp-Session-Id": "<your-session-id>"
    }
  }
}
```

This configuration specifies:
- **name**: A user-friendly name for the MCP connection
- **transport**: The transport protocol (streamable-http for HTTP with streaming capabilities)
- **url**: The endpoint URL for the MCP server
- **headers**: Additional headers required for authentication/session management

### Example Client Implementation

To interact with the MCP server programmatically, you can use the provided `mcpClient.py` script:

```python
from mcpClient import MCPClient

async def main():
    client = MCPClient("http://127.0.0.1:8003/mcp")
    
    # Get all test definition data
    test_data = await client.call_operation("getAllTestDefinitionData")
    
    # Run a test from template
    test_config = [{
        "order": 0,
        "feature": {
            "templatePath": "login/basic.feature"
        },
        "browser": "chromium"
    }]
    result = await client.call_operation("runningATemplate", {"test_infos": test_config})
    
    # Get execution details
    execution_id = result["execution_id"]
    details = await client.call_operation("getExecutionDetails", {"execution_id": execution_id})
    
    # Stream logs from the execution
    async for message in await client.call_operation("getExecutionList", {}, stream=True):
        print(message)

if __name__ == "__main__":
    import asyncio
    asyncio.run(main())
```

## License

(Placeholder: Specify the license for the project, e.g., MIT, Apache 2.0.)
