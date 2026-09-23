"""密码登录失败限速。

背景：`/api/v1/auth/login` 原来对失败次数没有任何限制 —— 实测连试 6 次全是 401，
没有 429、没有锁定。加上"后台是明文 HTTP"，脚本猜密码的代价极低。

这里按**账号**和**来源 IP**两条线计数（都在库里，所以多 worker 也一致）：

* 同一账号窗口内失败到阈值 → 拒绝（挡住针对某个账号的猜解）；
* 同一 IP 窗口内失败到阈值 → 拒绝（挡住拿一个字典横扫很多账号）。

成功登录会清掉该账号/IP 的失败记录（"成功即清零"），避免自己把自己锁在外面。
失败记录只在**未触发限速时**才写，所以表不会因为被刷而膨胀。
"""

from datetime import datetime, timedelta, timezone

from sqlalchemy import delete, func, select

from .models import LoginAttempt


def _window_start(settings) -> datetime:
    return datetime.now(timezone.utc) - timedelta(minutes=settings.login_window_minutes)


def check(db, username: str, client_ip: str, settings) -> None:
    """超限就抛 429。调用方在验证密码之前调用。"""
    from .errors import error

    since = _window_start(settings)
    account_key = (username or "").strip()

    failures = db.scalar(
        select(func.count()).select_from(LoginAttempt).where(
            LoginAttempt.username == account_key,
            LoginAttempt.succeeded.is_(False),
            LoginAttempt.created_at >= since,
        )
    ) or 0
    if account_key and failures >= settings.login_rate_limit_per_account:
        error(429, "too_many_login_attempts",
              "这个账号密码错误次数太多，请 %d 分钟后再试。" % settings.login_window_minutes)

    if client_ip:
        ip_failures = db.scalar(
            select(func.count()).select_from(LoginAttempt).where(
                LoginAttempt.client_ip == client_ip,
                LoginAttempt.succeeded.is_(False),
                LoginAttempt.created_at >= since,
            )
        ) or 0
        if ip_failures >= settings.login_rate_limit_per_ip:
            error(429, "too_many_login_attempts",
                  "尝试次数过多，请 %d 分钟后再试。" % settings.login_window_minutes)


def record_failure(db, username: str, client_ip: str) -> None:
    db.add(LoginAttempt(username=(username or "").strip(), client_ip=client_ip or "", succeeded=False))


def clear(db, username: str, client_ip: str) -> None:
    """登录成功：清掉这两条线的失败记录。顺带做一次窗口外清理，表不会无限增长。"""
    account_key = (username or "").strip()
    db.execute(delete(LoginAttempt).where(LoginAttempt.username == account_key, LoginAttempt.succeeded.is_(False)))
    if client_ip:
        db.execute(delete(LoginAttempt).where(LoginAttempt.client_ip == client_ip, LoginAttempt.succeeded.is_(False)))


def prune(db, settings) -> None:
    db.execute(delete(LoginAttempt).where(LoginAttempt.created_at < _window_start(settings) - timedelta(days=1)))
