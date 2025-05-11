import os
import json
import asyncio
import httpx
from pathlib import Path
from typing import Dict, Any, Optional, List, Tuple

from src.utils.logger import logger
from src.utils.filesystem import FileSystemManager
from src.utils.paths import get_data_dir
from src.api.utils import APIUtils


class TestTools:
    """Test tools implementation for MCP server.

    This class provides tools for TestZeus Hercules test execution,
    test results analysis, and test management.
    """

    @staticmethod
    async def run_test(test_id: str, options: Optional[Dict[str, Any]] = None, env_file: Optional[str] = None, metadata: Optional[Dict[str, Any]] = None) -> str:
        """Execute a test case by ID or file path.

        Args:
            test_id: Test case ID or path to feature file
            options: Optional configuration for test execution
                {
                    "browser": "chromium|firefox|webkit",
                    "headless": true|false,
                    "record_video": true|false,
                    "llm_model": "gpt-4o|anthropic.claude-3-opus-20240229",
                    "timeout": 600
                }
            env_file: Optional path to environment file containing variables for test execution
            metadata: Optional metadata about the execution context (execution_id, etc.)

        Returns:
            Test execution result summary
        """
        logger.debug(f"Run test tool called: {test_id}")

        if not os.getenv("ENABLE_TEST_TOOLS", "false").lower() == "true":
            return "Error: Test tools are disabled in server configuration"

        try:
            # Normalize test ID to a valid file path
            # Extract base test_id without extension for directory naming
            base_test_id = test_id
            if test_id.endswith(".feature"):
                base_test_id = test_id[:-8]  # Remove .feature extension for directory purposes

            # Set default options if not provided
            if options is None:
                options = {}

            # Always use bulk mode
            bulk_mode = True
            
            # Base directory configuration
            data_dir = get_data_dir()
            hercules_root = data_dir / "manager" / "exec"
            
            if bulk_mode:
                # Use the directories specified in options for bulk mode
                input_path = Path(options.get("input_dir"))
                output_path = Path(options.get("output_dir"))
                test_data_path = Path(options.get("test_data_dir"))
                logs_path = Path(options.get("logs_dir"))
                proofs_path = Path(options.get("proofs_dir"))
                
                logger.info(f"Running in bulk mode with custom directories:\n" +
                          f"- Input: {input_path}\n" +
                          f"- Output: {output_path}\n" +
                          f"- Test Data: {test_data_path}\n" +
                          f"- Logs: {logs_path}\n" +
                          f"- Proofs: {proofs_path}")
            else:
                # Standard single-test mode directories
                input_path = hercules_root / "opt" / "input"
                output_path = hercules_root / "opt" / "output"
                test_data_path = hercules_root / "opt" / "test_data"
            
            # Ensure directories exist
            FileSystemManager.ensure_dir(input_path)
            FileSystemManager.ensure_dir(output_path)
            FileSystemManager.ensure_dir(test_data_path)

            # In non-bulk mode with individual test directories, hercules expects the feature
            # file to always be named 'test.feature' regardless of the test directory name
            feature_filename = "test.feature"
            test_file = input_path / feature_filename
            
            # Log what we're looking for
            logger.info(f"Looking for standard feature file: {test_file}")
            
            # Check if we're in dynamic path mode
            bulk_mode = 'input_dir' in options and 'output_dir' in options and 'test_data_dir' in options
            
            # Log what we're looking for to help with debugging
            logger.info(f"Looking for feature file: {test_file}")
            
            if not test_file.exists():
                error_msg = f"Error: Feature file not found at {test_file} for test '{test_id}'"
                logger.error(error_msg)
                
                # List directory contents to help debug
                logger.info(f"Contents of input directory {input_path}:")
                if input_path.exists():
                    for item in input_path.iterdir():
                        logger.info(f"  - {item.name}")
                else:
                    logger.info(f"  (Input directory does not exist)")
                    
                return error_msg

            # Initialize environment variables container
            custom_env = os.environ.copy()
            
            # Configure the command based on the path structure
            cmd = []
            
            # Extract the necessary path components for individual test execution
            # The input_dir path structure is expected to be like:
            # /path/to/run_<execution_id>/opt/tests/test_X/input
            path_parts = str(input_path).split('/')
            
            try:
                # Find the 'opt' index in the path
                if 'opt' in path_parts:
                    opt_index = path_parts.index('opt')
                    
                    # Extract the test directory from the path (should be after 'tests')
                    test_dir_path = None
                    if 'tests' in path_parts:
                        tests_index = path_parts.index('tests')
                        if tests_index + 1 < len(path_parts):
                            test_dir_name = path_parts[tests_index + 1]
                            # Get the path up to and including the test directory
                            test_dir_parts = path_parts[:tests_index+2]
                            test_dir_path = '/'.join(test_dir_parts)
                    
                    if test_dir_path:
                        logger.info(f"Running test for specific test directory: {test_dir_path}")
                        
                        # We're running an individual test based on service approach
                        # Direct path to the test directory instead of using bulk mode
                        cmd = [
                            "testzeus-hercules",
                            "--project-base", test_dir_path
                        ]
                        
                        # Set necessary environment variables
                        # But don't set EXECUTE_BULK=true since we're running tests individually
                        custom_env['HERCULES_ROOT'] = str(Path(test_dir_path).parent.parent)
                        custom_env['PROJECT_BASE'] = test_dir_path
                        
                        logger.info(f"Running individual test with project base: {test_dir_path}")
                    else:
                        # Fallback to using the input file directly if we can't determine test_dir_path
                        logger.warning("Could not determine test directory path, using direct file paths.")
                        cmd = [
                            "testzeus-hercules",
                            "--input-file", str(test_file),
                            "--output-path", str(output_path),
                            "--test-data-path", str(test_data_path)
                        ]
                else:
                    # Fallback to direct file paths if 'opt' isn't in the path
                    logger.warning("'opt' not found in path, using direct file paths.")
                    cmd = [
                        "testzeus-hercules",
                        "--input-file", str(test_file),
                        "--output-path", str(output_path),
                        "--test-data-path", str(test_data_path)
                    ]
            except (ValueError, IndexError) as e:
                # Fallback to direct paths if there's any error
                logger.warning(f"Error parsing path structure: {e}. Using direct paths.")
                cmd = [
                    "testzeus-hercules",
                    "--input-file", str(test_file),
                    "--output-path", str(output_path),
                    "--test-data-path", str(test_data_path)
                ]
            
            # Add other options from the options dictionary
            if "browser" in options:
                cmd.extend(["--browser", options["browser"]])
                
            if options.get("headless", False):
                cmd.append("--headless")
                
            if options.get("record_video", False):
                cmd.append("--record-video")
                
            # Log the full command for debugging
            logger.info(f"Executing command: {' '.join(cmd)}")
            logger.info(f"Directory: {os.getcwd()}")
            
            # Environment is already initialized above
            # No need to check if it's None
                
            # Load environment variables from file if specified
            if env_file:
                env_file_path = Path(env_file)
                if not env_file_path.exists():
                    logger.error(f"Environment file not found: {env_file}")
                    return f"Error: Environment file '{env_file}' not found"
                
                # Load variables from .env file
                try:
                    logger.info(f"Loading environment variables from {env_file_path}")
                    # We already initialized custom_env above, so don't reset it here
                    env_var_count = 0
                    with open(env_file_path, 'r') as f:
                        for line in f:
                            line = line.strip()
                            if line and not line.startswith('#') and '=' in line:
                                key, value = line.split('=', 1)
                                custom_env[key.strip()] = value.strip().strip('"\'')
                                env_var_count += 1
                    
                    # Log number of variables loaded without exposing actual values
                    logger.info(f"Successfully loaded {env_var_count} environment variables")
                except Exception as e:
                    logger.error(f"Error loading environment file: {e}")
                    return f"Error loading environment file: {str(e)}"

            # Add test execution options to command
            if "llm_model" in options:
                logger.info(f"Using LLM model: {options['llm_model']}")
                cmd.extend(["--llm-model", options["llm_model"]])
                
            if "browser" in options:
                logger.info(f"Using browser: {options['browser']}")
                cmd.extend(["--browser", options["browser"]])
                
            if "headless" in options and options["headless"]:
                logger.info("Running tests in headless mode")
                cmd.append("--headless")
                
            if "record_video" in options and options["record_video"]:
                logger.info("Recording video of test execution")
                cmd.append("--record-video")

            # Create log prefix with metadata
            log_prefix = f"[HERCULES:{test_id}]"
            if metadata:
                exec_id = metadata.get("execution_id", "unknown")
                browser = metadata.get("browser", "unknown")
                headless = "HL" if metadata.get("headless", False) else "GUI"
                log_prefix = f"[EXEC:{exec_id}][{browser.upper()}:{headless}][{test_id}]"
                
            # Log test execution start with metadata
            if metadata:
                logger.info(f"{log_prefix} Starting test execution. Metadata: {metadata}")
            else:
                logger.info(f"{log_prefix} Starting test execution.")
                
            # Execute the command
            return_code, stdout, stderr = await APIUtils.run_command(
                cmd,
                timeout=options.get("timeout", 600),
                env=custom_env,
                log_prefix=log_prefix
            )
            # return_code=0
            
            # Log test completion
            if return_code == 0:
                logger.info(f"Test execution for '{test_id}' completed successfully")
            else:
                logger.error(f"Test execution for '{test_id}' failed with return code {return_code}")
            # Check for execution errors
            if return_code != 0:
                return f"Error: Test execution failed with return code {return_code}\n{stderr}"

            # Get result file path
            result_file = output_path / f"{test_id}_result.json"

            # Check if result file exists
            if not result_file.exists():
                logger.info(f"JSON result file not found: {result_file}")
                
                # Try to generate JSON result from HTML or XML result files
                html_result = output_path / f"{test_id}_result.html"
                xml_result = output_path / f"{test_id}_result.xml"
                
                # Create default result data
                result_data = {
                    "status": "completed",
                    "passed_steps": 0,
                    "failed_steps": 0,
                    "total_steps": 0,
                    "duration": 0
                }
                
                # Check for error indicators
                status = "completed"
                if return_code != 0:
                    status = "failed"
                    result_data["status"] = status
                
                # If we have an HTML result, the test probably ran successfully
                if html_result.exists():
                    logger.info(f"Found HTML result file: {html_result}")
                    try:
                        # Try to extract basic information from the result HTML
                        with open(html_result, 'r') as f:
                            content = f.read()
                            
                        # Check for failure indicators in the HTML
                        if "Passed</td>" in content:
                            status = "passed"
                        elif "Failed</td>" in content:
                            status = "failed"
                        
                        # Get test steps if available
                        steps = []
                        step_count = content.count("<tr><th>Step</th>")
                        if step_count > 0:
                            result_data["total_steps"] = step_count
                            
                            # Count passed steps
                            passed_steps = content.count("Passed</td>")
                            result_data["passed_steps"] = passed_steps
                            
                            # Count failed steps
                            failed_steps = content.count("Failed</td>")
                            result_data["failed_steps"] = failed_steps
                    except Exception as e:
                        logger.error(f"Error extracting data from HTML result: {e}")
                
                # Extract more detailed information from XML if available
                if xml_result.exists():
                    logger.info(f"Found XML result file: {xml_result}")
                    try:
                        # Parse basic XML information
                        import xml.etree.ElementTree as ET
                        tree = ET.parse(xml_result)
                        root = tree.getroot()
                        
                        # Extract test duration if available
                        duration_elem = root.find(".//testcase")
                        if duration_elem is not None and "time" in duration_elem.attrib:
                            result_data["duration"] = float(duration_elem.attrib["time"])
                    except Exception as e:
                        logger.error(f"Error extracting data from XML result: {e}")
                
                # Save the generated result data
                try:
                    # Convert any Path objects to strings for JSON serialization
                    json_safe_result_data = TestTools._path_to_json(result_data)
                    with open(result_file, 'w') as f:
                        json.dump(json_safe_result_data, f, indent=2)
                    logger.info(f"Generated JSON result file: {result_file}")
                except Exception as e:
                    logger.error(f"Error creating JSON result file: {e}")
                    return "Test executed, but failed to generate JSON result file. Check logs for details."

            # Read and return results summary
            with open(result_file, 'r') as f:
                result_data = json.load(f)

            # Return a summary of the test results
            summary = {
                "test_id": test_id,
                "status": result_data.get("status", "unknown"),
                "passed_steps": result_data.get("passed_steps", 0),
                "failed_steps": result_data.get("failed_steps", 0),
                "total_steps": result_data.get("total_steps", 0),
                "duration": result_data.get("duration", 0),
                "result_file": result_file  # This will be converted by _path_to_json
            }

            # Convert any Path objects to strings for JSON serialization
            json_safe_summary = TestTools._path_to_json(summary)
            return json.dumps(json_safe_summary, indent=2)
        except Exception as e:
            logger.error(f"Error running test: {e}")
            return f"Error: Failed to run test: {str(e)}"

    @staticmethod
    async def analyze_results(test_id: str, include_screenshots: bool = False) -> str:
        """Analyze test results for a specific test case.

        Args:
            test_id: Test case ID or path
            include_screenshots: Whether to include screenshots in the analysis

        Returns:
            Detailed analysis of test results
        """
        logger.debug(f"Analyze results tool called: {test_id}")

        if not os.getenv("ENABLE_TEST_TOOLS", "false").lower() == "true":
            return "Error: Test tools are disabled in server configuration"

        try:
            # Normalize test ID
            if not test_id.endswith(".feature"):
                test_id += ".feature"

            # Base directory configuration
            data_dir = get_data_dir()
            hercules_root = data_dir / "manager" / "exec"
            output_path = hercules_root / "opt" / "output"
            proofs_path = hercules_root / "opt" / "proofs"
            log_files_path = hercules_root / "opt" / "log_files"

            # Get result file
            result_file = output_path / f"{test_id}_result.json"
            if not result_file.exists():
                return f"Error: Test results for '{test_id}' not found"

            # Read results data
            with open(result_file, 'r') as f:
                result_data = json.load(f)

            # Get test name without extension for finding proof directories
            test_name = Path(test_id).stem

            # Find proof directories related to this test
            proof_dirs = []
            if proofs_path.exists():
                for item in proofs_path.iterdir():
                    if item.is_dir() and item.name.startswith(test_name):
                        proof_dirs.append(item.name)

            # Find log directories related to this test
            log_dirs = []
            if log_files_path.exists():
                for item in log_files_path.iterdir():
                    if item.is_dir() and item.name.startswith(test_name):
                        log_dirs.append(item.name)

            # Create comprehensive analysis
            analysis = {
                "test_id": test_id,
                "status": result_data.get("status", "unknown"),
                "execution_time": result_data.get("execution_time", "unknown"),
                "steps": result_data.get("steps", []),
                "assertions": result_data.get("assertions", []),
                "failures": [step for step in result_data.get("steps", []) if step.get("status") == "failed"],
                "proof_directories": proof_dirs,
                "log_directories": log_dirs
            }

            # Add screenshots if requested
            if include_screenshots and proof_dirs:
                screenshots = []
                for proof_dir in proof_dirs:
                    screenshots_dir = proofs_path / proof_dir / "screenshots"
                    if screenshots_dir.exists():
                        screenshots.extend([str(screenshots_dir / img) for img in os.listdir(screenshots_dir) 
                                           if img.endswith((".png", ".jpg"))])

                analysis["screenshots"] = screenshots

            # Convert any Path objects to strings for JSON serialization
            json_safe_analysis = TestTools._path_to_json(analysis)
            return json.dumps(json_safe_analysis, indent=2)
        except Exception as e:
            logger.error(f"Error analyzing results: {e}")
            return f"Error: Failed to analyze results: {str(e)}"

    @staticmethod
    async def generate_test(description: str, application_type: str) -> str:
        """Generate a test case from description.

        Args:
            description: Description of the test case to generate
            application_type: Type of application to test (web, mobile, api)

        Returns:
            Generated test case in Gherkin format
        """
        logger.debug(f"Generate test tool called: {description}")

        if not os.getenv("ENABLE_TEST_TOOLS", "false").lower() == "true":
            return "Error: Test tools are disabled in server configuration"

        try:
            # Validate application type
            valid_types = ["web", "mobile", "api"]
            if application_type.lower() not in valid_types:
                return f"Error: Invalid application type '{application_type}'. Supported types: {', '.join(valid_types)}"

            # Base directory configuration
            hercules_root = os.getenv("HERCULES_ROOT", "/testzeus-hercules")

            # Set LLM model and API key from environment or use default
            llm_model = os.getenv("LLM_MODEL_NAME", "gpt-4o")
            llm_api_key = os.getenv("LLM_MODEL_API_KEY", "")

            if not llm_api_key:
                return "Error: LLM API key not configured in server environment"

            # Create prompt for test generation
            prompt = f"""
            Generate a Gherkin feature file for testing a {application_type} application based on the following description:

            {description}

            The test should follow best practices for {application_type} testing and include:
            1. A clear Feature description
            2. At least one Scenario with Given, When, Then steps
            3. Appropriate assertions
            4. Any necessary test data placeholders

            Output should be valid Gherkin format only.
            """

            # Make API call to generate test
            if "gpt" in llm_model.lower():
                # OpenAI API call
                async with httpx.AsyncClient() as client:
                    response = await client.post(
                        "https://api.openai.com/v1/chat/completions",
                        headers={"Authorization": f"Bearer {llm_api_key}"},
                        json={
                            "model": llm_model,
                            "messages": [{"role": "user", "content": prompt}],
                            "temperature": 0.7
                        },
                        timeout=30.0
                    )
                    response.raise_for_status()
                    result = response.json()
                    generated_test = result.get("choices", [{}])[0].get("message", {}).get("content", "")

            elif "claude" in llm_model.lower():
                # Anthropic API call
                async with httpx.AsyncClient() as client:
                    response = await client.post(
                        "https://api.anthropic.com/v1/messages",
                        headers={
                            "x-api-key": llm_api_key,
                            "anthropic-version": "2023-06-01"
                        },
                        json={
                            "model": llm_model,
                            "messages": [{"role": "user", "content": prompt}],
                            "max_tokens": 2000
                        },
                        timeout=30.0
                    )
                    response.raise_for_status()
                    result = response.json()
                    generated_test = result.get("content", [{}])[0].get("text", "")
            else:
                return f"Error: Unsupported LLM model type: {llm_model}"

            # Create output file
            timestamp = asyncio.get_event_loop().time()
            output_file = os.path.join(hercules_root, "opt/input", f"generated_test_{int(timestamp)}.feature")

            # Save the generated test
            with open(output_file, 'w') as f:
                f.write(generated_test)

            return f"Test case generated and saved to: {output_file}\n\n{generated_test}"
        except Exception as e:
            logger.error(f"Error generating test: {e}")
            return f"Error: Failed to generate test: {str(e)}"

    @staticmethod
    async def list_test_steps(test_id: str) -> str:
        """List execution steps for a test.

        Args:
            test_id: Test case ID or file path

        Returns:
            List of test steps in execution order
        """
        logger.debug(f"List test steps tool called: {test_id}")

        if not os.getenv("ENABLE_TEST_TOOLS", "false").lower() == "true":
            return "Error: Test tools are disabled in server configuration"

        try:
            # Normalize test ID
            if not test_id.endswith(".feature"):
                test_id += ".feature"

            # Base directory configuration
            hercules_root = os.getenv("HERCULES_ROOT", "/testzeus-hercules")
            input_path = os.path.join(hercules_root, "opt/input")

            # Find test file
            test_file = os.path.join(input_path, test_id)
            if not os.path.exists(test_file):
                return f"Error: Test case '{test_id}' not found"

            # Read test file content
            with open(test_file, 'r') as f:
                content = f.read()

            # Extract steps from file content
            steps = []
            for line in content.split('\n'):
                line = line.strip()
                if line.startswith(('Given ', 'When ', 'Then ', 'And ', 'But ')):
                    steps.append(line)

            # Create steps response
            steps_info = {
                "test_id": test_id,
                "step_count": len(steps),
                "steps": steps
            }

            # Convert any Path objects to strings for JSON serialization
            json_safe_steps = TestTools._path_to_json(steps_info)
            return json.dumps(json_safe_steps, indent=2)
        except Exception as e:
            logger.error(f"Error listing test steps: {e}")
            return f"Error: Failed to list test steps: {str(e)}"

    @staticmethod
    async def explain_failure(test_id: str, step_index: Optional[int] = None) -> str:
        """Explain why a test step failed.

        Args:
            test_id: Test case ID or file path
            step_index: Index of the failed step (0-based)

        Returns:
            Explanation of the failure with context
        """
        logger.debug(f"Explain failure tool called: {test_id}, step: {step_index}")

        if not os.getenv("ENABLE_TEST_TOOLS", "false").lower() == "true":
            return "Error: Test tools are disabled in server configuration"

        try:
            # Normalize test ID
            if not test_id.endswith(".feature"):
                test_id += ".feature"

            # Base directory configuration
            hercules_root = os.getenv("HERCULES_ROOT", "/testzeus-hercules")
            output_path = os.path.join(hercules_root, "opt/output")
            log_files_path = os.path.join(hercules_root, "opt/log_files")

            # Get test result file
            result_file = os.path.join(output_path, f"{test_id}_result.json")
            if not os.path.exists(result_file):
                return f"Error: Test results for '{test_id}' not found"

            # Read results data
            with open(result_file, 'r') as f:
                result_data = json.load(f)

            # Find failed steps
            failed_steps = []
            for i, step in enumerate(result_data.get("steps", [])):
                if step.get("status") == "failed":
                    failed_steps.append((i, step))

            if not failed_steps:
                return f"No failed steps found for test '{test_id}'"

            # If step_index is provided, find that specific step
            if step_index is not None:
                if step_index < 0 or step_index >= len(result_data.get("steps", [])):
                    return f"Error: Invalid step index {step_index}. Valid range: 0-{len(result_data.get('steps', [])) - 1}"

                target_step = result_data.get("steps", [])[step_index]
                if target_step.get("status") != "failed":
                    return f"Step {step_index} did not fail. Status: {target_step.get('status', 'unknown')}"

                explanation = {
                    "test_id": test_id,
                    "step_index": step_index,
                    "step_text": target_step.get("text", ""),
                    "failure_reason": target_step.get("failure_reason", "Unknown error"),
                    "context": target_step.get("context", {}),
                    "screenshot": target_step.get("screenshot", "")
                }
            else:
                # Provide information about all failed steps
                explanations = []
                for i, step in failed_steps:
                    explanations.append({
                        "step_index": i,
                        "step_text": step.get("text", ""),
                        "failure_reason": step.get("failure_reason", "Unknown error")
                    })

                explanation = {
                    "test_id": test_id,
                    "failed_step_count": len(failed_steps),
                    "failed_steps": explanations
                }

            # Convert any Path objects to strings for JSON serialization
            json_safe_explanation = TestTools._path_to_json(explanation)
            return json.dumps(json_safe_explanation, indent=2)
        except Exception as e:
            logger.error(f"Error explaining failure: {e}")
            return f"Error: Failed to explain failure: {str(e)}"

    @staticmethod
    def _path_to_json(obj):
        """Convert Path objects to strings for JSON serialization.
        
        Args:
            obj: Object to convert
            
        Returns:
            JSON-serializable object
        """
        if isinstance(obj, Path):
            return str(obj)
        elif isinstance(obj, dict):
            return {k: TestTools._path_to_json(v) for k, v in obj.items()}
        elif isinstance(obj, list):
            return [TestTools._path_to_json(item) for item in obj]
        else:
            return obj