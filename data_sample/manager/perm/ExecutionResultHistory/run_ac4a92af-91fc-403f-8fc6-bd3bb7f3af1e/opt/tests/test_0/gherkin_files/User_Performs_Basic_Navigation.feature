Feature: Basic Navigation Functionality


Scenario:User Performs Basic NavigationUser Performs Basic Navigation
    Given a user is on the test pages at "https://testpages.eviltester.com/styled/index.html"
    And the user clicks on the "About" button in the top nav
    Then the page should navigate to "https://testpages.eviltester.com/styled/page?app=testpages&t=About"
    And the first heading of the article should be "About TestPages"