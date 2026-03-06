import subprocess
import sys
import os
from unittest.mock import MagicMock, patch, call

from behave import given, when, then

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))
from src.crawler.twitter_crawler import TwitterCrawler


@given("爬虫实例（max_retries=3，retry_base_delay=0）")
def step_crawler_retries_3(context):
    context.crawler = TwitterCrawler(cdp_port=18800, max_retries=3, retry_base_delay=0)


@given("爬虫实例（max_retries=2，retry_base_delay=0）")
def step_crawler_retries_2(context):
    context.crawler = TwitterCrawler(cdp_port=18800, max_retries=2, retry_base_delay=0)


@when("执行 navigate 命令，前两次失败第三次成功")
def step_navigate_fail_then_succeed(context):
    fail_result = MagicMock()
    fail_result.returncode = 1
    fail_result.stderr = "connection refused"

    ok_result = MagicMock()
    ok_result.returncode = 0
    ok_result.stdout = "ok"

    side_effects = [fail_result, fail_result, ok_result]
    context.call_count = 0

    def fake_run(cmd, **kwargs):
        result = side_effects[context.call_count]
        context.call_count += 1
        return result

    with patch("subprocess.run", side_effect=fake_run):
        context.output = context.crawler._run_browser_command("navigate", "https://twitter.com")


@then("命令最终成功，共调用 subprocess 3 次")
def step_assert_3_calls(context):
    assert context.output == "ok", f"Expected 'ok', got {context.output!r}"
    assert context.call_count == 3, f"Expected 3 calls, got {context.call_count}"


@when("执行 eval 命令，每次都失败")
def step_eval_always_fail(context):
    fail_result = MagicMock()
    fail_result.returncode = 1
    fail_result.stderr = "browser error"

    context.call_count = 0
    context.raised = None

    def fake_run(cmd, **kwargs):
        context.call_count += 1
        return fail_result

    try:
        with patch("subprocess.run", side_effect=fake_run):
            context.crawler._run_browser_command("eval", "1+1")
    except RuntimeError as e:
        context.raised = e


@then("抛出 RuntimeError，共调用 subprocess 2 次")
def step_assert_runtime_error_2_calls(context):
    assert context.raised is not None, "Expected RuntimeError but none was raised"
    assert context.call_count == 2, f"Expected 2 calls, got {context.call_count}"


@when("执行 click 命令，第一次就失败")
def step_click_fail(context):
    fail_result = MagicMock()
    fail_result.returncode = 1
    fail_result.stderr = "element not found"

    context.call_count = 0
    context.raised = None

    def fake_run(cmd, **kwargs):
        context.call_count += 1
        return fail_result

    try:
        with patch("subprocess.run", side_effect=fake_run):
            context.crawler._run_browser_command("click", "some-ref")
    except RuntimeError as e:
        context.raised = e


@then("抛出 RuntimeError，共调用 subprocess 1 次")
def step_assert_runtime_error_1_call(context):
    assert context.raised is not None, "Expected RuntimeError but none was raised"
    assert context.call_count == 1, f"Expected 1 call, got {context.call_count}"


@when("执行 open 命令，第一次超时第二次成功")
def step_open_timeout_then_succeed(context):
    ok_result = MagicMock()
    ok_result.returncode = 0
    ok_result.stdout = "done"

    context.call_count = 0
    context.raised_error = None

    def fake_run(cmd, **kwargs):
        context.call_count += 1
        if context.call_count == 1:
            raise subprocess.TimeoutExpired(cmd, 30)
        return ok_result

    with patch("subprocess.run", side_effect=fake_run):
        context.output = context.crawler._run_browser_command("open", "https://x.com/foo/status/1")


@then("命令最终成功，共调用 subprocess 2 次")
def step_assert_2_calls(context):
    assert context.output == "done", f"Expected 'done', got {context.output!r}"
    assert context.call_count == 2, f"Expected 2 calls, got {context.call_count}"
