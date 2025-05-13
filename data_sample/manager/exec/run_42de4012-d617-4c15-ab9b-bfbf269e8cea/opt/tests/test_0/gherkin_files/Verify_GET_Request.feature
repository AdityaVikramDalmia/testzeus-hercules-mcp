Feature: RESTful API Testing


Scenario:Verify GET RequestVerify GET Request
    Given the API endpoint is "https://jsonplaceholder.typicode.com/todos/1"
    When the user sends a GET request
    Then the response status code should be 200
    And the response should include "userId"
    And the response should include "title"
    And the response should include "completed" with value "false"