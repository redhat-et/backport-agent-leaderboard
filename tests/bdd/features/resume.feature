Feature: Resume benchmark run
  As a benchmark operator
  I want to resume an interrupted benchmark
  So that I don't re-run entries that already have results

  Scenario: Skip entry with existing result
    Given a dataset with 2 backport entries
    And a result file already exists for the first entry
    When I run the benchmark
    Then only the second entry should be executed
    And the first entry should be reported as skipped
