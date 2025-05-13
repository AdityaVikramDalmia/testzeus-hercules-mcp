Feature: Wikipedia Article Navigation and Information Verification


Scenario:User Navigates Between Wikipedia Articles and Verifies InformationUser Navigates Between Wikipedia Articles and Verifies Information
    Given a user is on the Wikipedia main page at "https://en.wikipedia.org/wiki/Main_Page"
    When the user clicks on the search input field
    And the user enters "Python programming language" into the search input field
    And the user clicks the search button
    Then the page should navigate to "https://en.wikipedia.org/wiki/Python_(programming_language)"
    And the first heading of the article should be "Python (programming language)"
    And the article should contain information about "Guido van Rossum"
    When the user clicks on the link "Guido van Rossum"
    Then the page should navigate to a URL containing "Guido_van_Rossum"
    And the first heading of the article should be "Guido van Rossum"