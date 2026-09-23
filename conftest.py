"""测试环境的全局开关。

`fake:` 微信登录默认在生产关闭（它等于万能登录后门），这里是唯一打开它的地方：
测试里大量用 `fake:openid` 来构造会话，所以在这个进程启动时把开关打开。
"""
import os

os.environ.setdefault("HELPCAT_ALLOW_FAKE_WECHAT", "1")
