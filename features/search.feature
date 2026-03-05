Feature: embedding 补偿机制

  Scenario: 缺失 embedding 的推文被补偿索引
    Given 数据库中有 is_ai_related=1 且 embedding 为 NULL 的推文
    When 调用 index_missing
    Then 该推文的 embedding 被生成并保存

  Scenario: embedding API 失败时重试并最终跳过
    Given 数据库中有 is_ai_related=1 且 embedding 为 NULL 的推文
    And embedding API 始终失败
    When 调用 index_missing
    Then 重试 2 次后跳过，不抛出异常
