Feature: 自动关注幂等性

  Scenario: 关注后确认成功才写入数据库
    Given 浏览器点击关注按钮成功
    And 关注后页面确认状态为 "following"
    When 执行 follow_author
    Then 数据库中写入该账号

  Scenario: 关注后确认失败不写入数据库，下次重试
    Given 浏览器点击关注按钮成功
    And 关注后页面确认状态为 "not_following"
    When 执行 follow_author
    Then 数据库中不写入该账号

  Scenario: 已关注的作者不重复尝试关注
    Given 数据库中已有关注记录 "@testuser"
    When 执行 run 处理包含 "@testuser" 的推文列表
    Then 不调用 follow_author
