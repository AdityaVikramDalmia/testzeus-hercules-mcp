#!/usr/bin/env python

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

# Create FastAPI app
app = FastAPI(
    title="TestZeus Hercules API",
    description="API for running TestZeus Hercules tests",
    version="1.0.0",
    docs_url="/api/docs",
    redoc_url="/api/redoc",
    openapi_url="/api/openapi.json"
)

# Define root endpoint directly on the app
@app.get("/")
async def root():
    """Root endpoint that returns basic API information."""
    return {
        "status": "ok",
        "name": "TestZeus Hercules API",
        "version": "1.0.0"
    }

# Add CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)