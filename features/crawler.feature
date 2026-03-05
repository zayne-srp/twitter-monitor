Feature: 爬虫基本行为

  Scenario: _is_truncated 判断截断符
    Given 爬虫实例
    When 检查文本 "Hello…" 是否被截断
    Then 返回 True

  Scenario: _is_truncated 正常文本不截断
    Given 爬虫实例
    When 检查文本 "Hello world" 是否被截断
    Then 返回 False

  Scenario: _parse_tweets_from_eval 解析双重编码 JSON
    Given 爬虫实例
    When 解析双重编码的推文 JSON（外层 JSON 包裹字符串）
    Then 成功返回推文列表
