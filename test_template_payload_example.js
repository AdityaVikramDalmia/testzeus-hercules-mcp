/**
 * Complete example payload for /tests/run-from-template API
 * 
 * This demonstrates all possible options and configurations with explanatory comments.
 */

const COMPLETE_TEST_TEMPLATE_PAYLOAD = `{
  "test_infos": [
    {
      "order": 0,
      "feature": {
        "templatePath": "basic/login.feature"
      },
      "testData": [
        {
          "templatePath": "credentials/production_users.txt"
        }
      ],
      "headless": false,
      "timeout": 300,
      "browser": "chromium"
    },
    {
      "order": 1,
      "feature": {
        "templatePath": "dashboard/view_reports.feature"
      },
      "testData": [
        {
          "templatePath": "sample_data/reports_data.txt"
        }
      ],
      "headless": true,
      "timeout": 180,
      "browser": "firefox"
    },
    {
      "order": 2,
      "feature": {
        "featureScript": "Feature: Custom One-time Feature\\n  Scenario: Test Custom Functionality\\n    Given I am on the custom page\\n    When I click the custom button\\n    Then I should see custom results"
      },
      "testData": [
        {
          "templatePath": "custom/one_time_data.txt"
        }
      ],
      "headless": true,
      "timeout": 120,
      "browser": "webkit"
    },
    {
      "order": 3,
      "feature": {
        "templatePath": "checkout/payment_flow.feature"
      },
      "testData": [
        {
          "templatePath": "checkout/payment_methods.txt"
        },
        {
          "templatePath": "checkout/shipping_addresses.txt"
        },
        {
          "templatePath": "checkout/product_catalog.txt"
        }
      ],
      "headless": false,
      "timeout": 600,
      "browser": "chromium"
    }
  ],
  "mock": false,
  "environment": "staging"
}`;

/**
 * Prompt template for generating API payload
 */
const TEST_TEMPLATE_PROMPT = `Create a payload for the TestZeus /tests/run-from-template API with the following requirements:

[FEATURES]
- Feature paths should be relative to data/manager/lib/features/
- Include the following feature templates: {LIST_FEATURES}
- Include any custom feature scripts: {CUSTOM_SCRIPTS}

[TEST DATA]
- Test data paths should be relative to data/manager/lib/test_data/
- Include the following test data templates: {LIST_TEST_DATA}

[EXECUTION SETTINGS]
- Run tests in {HEADLESS_MODE} mode
- Set timeout to {TIMEOUT} seconds
- Use {BROWSER_TYPE} browser
- Target {ENVIRONMENT} environment
- Mock mode: {MOCK_MODE}

The response should be a complete JSON payload ready to be used in a cURL command or API client.`;

module.exports = {
  COMPLETE_TEST_TEMPLATE_PAYLOAD,
  TEST_TEMPLATE_PROMPT
};

/**
 * Usage Example:
 * 
 * To create a customized payload, replace the placeholder values in TEST_TEMPLATE_PROMPT:
 * 
 * const prompt = TEST_TEMPLATE_PROMPT
 *   .replace('{LIST_FEATURES}', 'basic/login.feature, dashboard/reports.feature')
 *   .replace('{CUSTOM_SCRIPTS}', 'None')
 *   .replace('{LIST_TEST_DATA}', 'credentials/admin_users.txt, sample_data/reports.txt')
 *   .replace('{HEADLESS_MODE}', 'headless')
 *   .replace('{TIMEOUT}', '300')
 *   .replace('{BROWSER_TYPE}', 'chromium')
 *   .replace('{ENVIRONMENT}', 'staging')
 *   .replace('{MOCK_MODE}', 'false');
 * 
 * Then use an AI model or your own logic to generate the payload from this prompt.
 */ 