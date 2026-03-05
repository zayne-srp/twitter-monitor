Feature: 推文全文抓取

  Scenario: 正常推文不需要点进去
    Given 全文模式已启用
    And 一条推文文本为 "Hello world"（不含截断符）
    When 爬虫判断是否需要抓全文
    Then 不触发详情页请求

  Scenario: 截断推文自动获取全文
    Given 全文模式已启用
    And 一条推文文本末尾含有 "…"
    When 爬虫处理该截断推文
    Then 导航到推文详情页并返回完整文本

  Scenario: 详情页请求失败时降级保留卡片文本
    Given 全文模式已启用
    And 一条被截断的推文
    When 导航到详情页失败（抛出异常）
    Then 降级返回空字符串，不中断爬取流程
