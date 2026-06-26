Feature: Run benchmark
  As a benchmark operator
  I want to run a backporting tool against the dataset
  So that I can evaluate its effectiveness

  Scenario: Successful benchmark run
    Given a dataset with 1 "Easy" backport entry for "owner/repo"
    And a tool "test-tool" configured with a generate_diff command
    And a config file with the tool registered
    When I run the benchmark with tool "test-tool"
    Then a result file should be created
    And the result should have a non-null timestamp
    And the result should have tool_key "test-tool"

  Scenario: Tool timeout
    Given a dataset with 1 "Easy" backport entry for "owner/repo"
    And a tool "slow-tool" with a generate_diff command that sleeps for 10 seconds
    And a config file with timeout set to 1 second
    When I run the benchmark with tool "slow-tool"
    Then the result should have an error message containing "Timeout"

  Scenario: Setup command failure
    Given a dataset with 1 "Easy" backport entry for "owner/repo"
    And a tool "broken-tool" with a setup command that exits with code 1
    And a config file with the tool registered
    When I run the benchmark with tool "broken-tool"
    Then the result should have an error message containing "Setup failed"
