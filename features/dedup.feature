Feature: 语义去重

  Scenario: 高度相似的推文被标记为重复
    Given 数据库中有一条推文，embedding 为 [0.1, 0.2, 0.3]
    And 新爬取到一条推文，embedding 与已有推文余弦相似度为 0.95
    When 执行语义去重
    Then 新推文被标记为 is_duplicate=1

  Scenario: 相似度低于阈值的推文不被标记
    Given 数据库中有一条推文，embedding 为 [0.1, 0.2, 0.3]
    And 新爬取到一条推文，embedding 与已有推文余弦相似度为 0.80
    When 执行语义去重
    Then 新推文 is_duplicate 仍为 0

  Scenario: 没有 embedding 的推文跳过语义去重
    Given 一条没有 embedding 的新推文
    When 执行语义去重
    Then 该推文不被标记为重复

  Scenario: 报告只包含非重复推文
    Given 数据库中有3条 AI 相关推文，其中1条被标记为语义重复
    When 查询非重复推文生成报告
    Then 报告只包含2条推文
