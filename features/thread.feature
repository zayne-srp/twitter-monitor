Feature: Thread 增量存储

  Scenario: 详情页只有一条推文（非 thread）
    Given 详情页返回单条推文
    When 爬虫抓取 thread
    Then 返回单条推文列表，无 thread_root_id 关联

  Scenario: 详情页有多条推文（thread）
    Given 详情页返回 3 条连续推文
    When 爬虫抓取 thread
    Then 返回 3 条推文，每条 thread_root_id 等于第一条的 id

  Scenario: Thread 推文已存在时不重复存储
    Given 数据库已有某 thread 的前两条推文
    When 保存同一 thread 的 3 条推文
    Then 只新增第 3 条，已存在的跳过
