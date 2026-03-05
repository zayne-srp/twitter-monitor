Feature: 报告生成

  Scenario: 同一作者多条推文在报告中聚合为一条
    Given 推文列表包含同一作者 "@alice" 的 3 条推文
    When 生成报告
    Then 报告中 "@alice" 只出现一次，并注明另有 2 条

  Scenario: 不同作者的推文各自独立展示
    Given 推文列表包含 "@alice" 和 "@bob" 各 1 条推文
    When 生成报告
    Then 报告中 "@alice" 和 "@bob" 各出现一次

  Scenario: 推文按 AI 生成的话题分组
    Given 推文列表包含多条关于不同话题的推文
    And OpenAI cluster_topics 返回话题分组
    When 生成报告
    Then 报告按话题分组展示

  Scenario: OpenAI 调用失败时降级为默认分类
    Given 推文列表包含多条推文
    And OpenAI cluster_topics 抛出异常
    When 生成报告
    Then 报告使用默认关键字分类展示
