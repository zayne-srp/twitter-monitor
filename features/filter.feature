Feature: 推文预过滤（去噪）

  Scenario: 纯转发推文被过滤
    Given 一组推文包含纯转发推文 "RT @ someuser some content"
    When 执行 pre_filter
    Then 该转发推文被移除

  Scenario: 有实质内容的推文即使含短链接也保留
    Given 一条推文含有短链接但正文超过 20 字 "这是一篇关于AI的深度文章，讲述了大模型的训练原理，值得一读 https://bit.ly/xyz"
    When 执行 pre_filter
    Then 该推文被保留

  Scenario: 空文本推文被过滤
    Given 一条推文文本为空或少于 10 字 "hi"
    When 执行 pre_filter
    Then 该推文被移除
