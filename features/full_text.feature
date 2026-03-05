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

  Scenario: 全文抓取达到上限后降级使用卡片文本
    Given 全文模式已启用
    And 全文抓取计数器已达上限 30
    When 爬虫处理一条截断推文
    Then 不触发详情页请求，保留卡片原文

  Scenario: 每次全文抓取之间有随机间隔
    Given 全文模式已启用
    And 一条推文文本末尾含有 "…"
    When 爬虫处理该截断推文并成功获取全文
    Then 详情页请求后有随机等待间隔
