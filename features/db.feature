Feature: 数据库存储

  Scenario: 保存普通推文
    Given 一个空数据库
    When 保存一条普通推文
    Then 数据库中存在该推文，thread_root_id 为空

  Scenario: 保存 thread 推文带 thread_root_id
    Given 一个空数据库
    When 保存一条 feed_type 为 thread 的推文，thread_root_id 为 "root123"
    Then 数据库中该推文的 thread_root_id 为 "root123"

  Scenario: 重复 id 的推文不覆盖
    Given 数据库已有 id 为 "tweet001" 的推文
    When 再次保存相同 id 的推文
    Then save_tweet 返回 False，数据库中只有一条
