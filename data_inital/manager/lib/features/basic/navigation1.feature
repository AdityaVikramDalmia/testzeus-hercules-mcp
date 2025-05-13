Feature: Navigation Test
  Scenario: Navigate to home page
    Given I am on the login page
    When I navigate to the home page
    Then I should see the dashboard