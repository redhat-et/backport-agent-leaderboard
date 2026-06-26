Feature: Add backport entry
  As a benchmark curator
  I want to add new backport entries to the dataset
  So that the benchmark covers more cases

  Scenario: Classification as Easy
    Given diffs with similarity 0.95 and file_overlap 0.90
    When I compute the classification
    Then the classification should be "Easy"

  Scenario: Classification as Medium
    Given diffs with similarity 0.75 and file_overlap 0.60
    When I compute the classification
    Then the classification should be "Medium"

  Scenario: Classification as Hard
    Given diffs with similarity 0.30 and file_overlap 0.30
    When I compute the classification
    Then the classification should be "Hard"

  Scenario: Append entry to CSV
    Given an existing dataset with 3 entries
    When I append a new backport entry
    Then the dataset should have 4 entries
    And the last entry should match the appended data
