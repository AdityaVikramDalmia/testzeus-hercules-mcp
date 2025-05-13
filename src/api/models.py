#!/usr/bin/env python
from datetime import datetime
from typing import Dict, Any, Optional, List, Union
from pydantic import BaseModel, field_validator

class FeatureSpec(BaseModel):
    """Specification for a feature file to be used in testing."""
    templatePath: Optional[str] = None
    featureScript: Optional[str] = None
    
    @field_validator('*')
    def validate_feature(cls, v, info):
        """Validate that either templatePath or featureScript is provided."""
        field_name = info.field_name
        
        if field_name == 'templatePath' and v is None:
            # Check if featureScript is also None
            values = info.data
            if 'featureScript' in values and values['featureScript'] is None:
                raise ValueError("Either templatePath or featureScript must be provided")
        
        return v

class TestDataSpec(BaseModel):
    """Specification for test data to be used in testing."""
    templatePath: str

class TestInfo(BaseModel):
    """Information about a test to be executed."""
    order: int
    feature: FeatureSpec
    testData: Optional[List[TestDataSpec]] = None
    headless: bool = False
    timeout: int = 300

class TestInfosRequest(BaseModel):
    """Request containing multiple test information objects."""
    test_infos: List[TestInfo]
    mock: bool = False

class HSingleFile(BaseModel):
    """Request containing multiple test information objects."""
    path: str
    type: str
    content: str


class HFileRequest(BaseModel):
    """Request containing multiple test information objects."""
    files: List[HSingleFile]



class TestRequest(BaseModel):
    """Request for a single test execution."""
    test_id: str
    options: Optional[Dict[str, Any]] = None
    mock: bool = False

class TestResponse(BaseModel):
    """Response for a test execution request."""
    execution_id: str
    test_id: str
    status: str
    start_time: str

class TestResult(BaseModel):
    """Result of a test execution."""
    execution_id: str
    test_id: str
    status: str
    start_time: str
    end_time: Optional[str] = None
    result: Optional[Dict[str, Any]] = None
    error: Optional[str] = None
    archived_path: Optional[str] = None
