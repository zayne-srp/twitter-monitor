import os
import sys
import tempfile
import time
from unittest.mock import patch, MagicMock

from behave import given, when, then

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))
from src.follower.auto_follower import AutoFollower
from src.storage.db import TweetDatabase


@given('浏览器点击关注按钮成功')
def step_browser_click_follow_success(context):
    context.follower = AutoFollower.__new__(AutoFollower)
    context.follower.cdp_port = 18800
    context.follower.client = MagicMock()
    context.handle = "testuser"


@given('关注后页面确认状态为 "following"')
def step_confirm_following(context):
    context.confirm_status = "following"


@given('关注后页面确认状态为 "not_following"')
def step_confirm_not_following(context):
    context.confirm_status = "not_following"


@when('执行 follow_author')
def step_exec_follow_author(context):
    call_count = [0]

    def mock_browser_cmd(*args):
        if "eval" in args:
            js_arg = args[-1]
            if "unfollow" in js_arg or "Following" in js_arg:
                return context.confirm_status
            return '"clicked"'
        return ""

    with patch.object(context.follower, "_run_browser_command", side_effect=mock_browser_cmd):
        with patch("time.sleep"):
            context.result = context.follower.follow_author(context.handle)


@then('数据库中写入该账号')
def step_db_has_account(context):
    assert context.result is True


@then('数据库中不写入该账号')
def step_db_no_account(context):
    assert context.result is False


@given('数据库中已有关注记录 "@testuser"')
def step_db_has_followed_record(context):
    db_path = tempfile.mktemp(suffix=".db")
    context.db = TweetDatabase(db_path=db_path)
    context.db_path = db_path
    context.db.save_followed_account("testuser")

    context.follower = AutoFollower.__new__(AutoFollower)
    context.follower.cdp_port = 18800
    context.follower.client = MagicMock()


@when('执行 run 处理包含 "@testuser" 的推文列表')
def step_exec_run_with_testuser(context):
    tweets = [
        {
            "author": "testuser",
            "text": "AI is amazing",
            "url": "https://x.com/testuser/status/123",
        }
    ]
    scores = {"testuser": 9.0}

    with patch.object(context.follower, "evaluate_authors", return_value=scores):
        with patch.object(context.follower, "follow_author") as mock_follow:
            context.mock_follow = mock_follow
            context.follower.run(tweets, context.db)


@then('不调用 follow_author')
def step_follow_not_called(context):
    context.mock_follow.assert_not_called()
    if hasattr(context, 'db_path'):
        os.unlink(context.db_path)
