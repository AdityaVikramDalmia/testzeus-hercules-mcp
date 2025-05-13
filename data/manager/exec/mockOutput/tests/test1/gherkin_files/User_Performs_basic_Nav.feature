Feature: Basic Nav perfomance functionality


Scenario:User Performs basic NavUser Performs basic Nav
    Given a user is on the Wikipedia main page at the URL
    And the user clicks on the "About" button in the top nav
    Then the page should navigate to "https://testpages.eviltester.com/styled/page?app=testpages&t=About"
    And the first heading of the article should be "About TestPages"