Feature: 浏览器命令重试机制

  Scenario: 可重试命令在瞬时失败后成功
    Given 爬虫实例（max_retries=3，retry_base_delay=0）
    When 执行 navigate 命令，前两次失败第三次成功
    Then 命令最终成功，共调用 subprocess 3 次

  Scenario: 可重试命令超过重试次数后抛出异常
    Given 爬虫实例（max_retries=2，retry_base_delay=0）
    When 执行 eval 命令，每次都失败
    Then 抛出 RuntimeError，共调用 subprocess 2 次

  Scenario: 不可重试命令失败后立即抛出异常
    Given 爬虫实例（max_retries=3，retry_base_delay=0）
    When 执行 click 命令，第一次就失败
    Then 抛出 RuntimeError，共调用 subprocess 1 次

  Scenario: 命令超时触发重试
    Given 爬虫实例（max_retries=2，retry_base_delay=0）
    When 执行 open 命令，第一次超时第二次成功
    Then 命令最终成功，共调用 subprocess 2 次
