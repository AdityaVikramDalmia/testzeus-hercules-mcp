Feature: Web Search Functionality


Scenario:User Searches for InformationUser Searches for Information
    Given a user is on the Wikipedia main page at "https://en.wikipedia.org/wiki/Main_Page"
    And the user clicks on the search input field
    And the user enters "Artificial intelligence" into the search input field
    And the user clicks the search button
    Then the page should navigate to "https://en.wikipedia.org/wiki/Artificial_intelligence"
    And the first heading of the article should be "Artificial intelligence"