FROM python:3.11-slim

WORKDIR /app

# Copy requirements first for better caching
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy project files
COPY . .

# Environment variables
ENV TRANSPORT_TYPE=sse
ENV HTTP_HOST=0.0.0.0
ENV HTTP_PORT=8000
ENV SERVER_NAME=Docker-MCP-Server
ENV SERVER_DEBUG=false

# Expose the port used by the SSE transport
EXPOSE 8000

# Run the server with SSE transport by default
CMD ["python", "-m", "src.main", "--transport", "sse", "--host", "0.0.0.0"] 