"""投稿自动预检：规则能判的自动放行，判不了的留给人。

公开页面有两条红线：**不泄露精确位置**、**不对未确认的医疗信息作推断**。这两件事
规则判不了 —— 能判的只是"这份投稿看起来是不是常规、干净"。所以这里的规则刻意保守：
**任一条不满足就照旧进待审**，而不是反过来"默许放行"。

`HELPCAT_AUTO_REVIEW` 三种取值：

* `off`（默认）—— 完全关闭，一切照旧进待审；
* `shadow` —— 只计算并写审计，**不改变任何状态**（先观察判定结果再决定是否开启）；
* `on` —— 判定通过就直接公开。

规则写成 `[(名字, 是否通过, 中文说明)]`，所以审计和界面都能说清"因为哪几条通过 /
哪一条没过"，而不是只给一个布尔值。
"""

import re
from dataclasses import dataclass
from typing import Sequence, Tuple

MODE_OFF = "off"
MODE_SHADOW = "shadow"
MODE_ON = "on"
MODES = (MODE_OFF, MODE_SHADOW, MODE_ON)

# 精确到楼栋/门牌的描述不进公开页（隐私红线）。
PRECISE_ADDRESS = re.compile(r"(\d+\s*[号栋幢]|\d+\s*单元|\d+\s*[室楼]|\d+\s*层|楼[栋幢]\s*\d|单元\s*\d)")
# 联系方式、测试标记与链接：这些不该出现在公开档案里。
CONTACT_OR_JUNK = re.compile(r"(1[3-9]\d{9})|(\[QA-)|(测试)|(https?://)|(www\.)|(asdf)|(微信|wechat|加我|私聊|qq)", re.IGNORECASE)
# 名字/小区名：中英文数字 + 少量常见符号，2–40 字。
NAME_SHAPE = re.compile(r"^[\u4e00-\u9fa5A-Za-z0-9·\-—()（）\s]{2,40}$")

RuleResult = Tuple[str, bool, str]


@dataclass(frozen=True)
class Decision:
    """一次预检的结果：通过与否 + 依据。

    `passed`/`failed` 是规则名（机器可读，进审计）；`*_labels` 是中文说明（给人看）。
    """

    approved: bool
    passed: Tuple[str, ...] = ()
    failed: Tuple[str, ...] = ()
    passed_labels: Tuple[str, ...] = ()
    failed_labels: Tuple[str, ...] = ()

    def as_audit(self):
        return {
            "auto_approved": self.approved,
            "passed": list(self.passed), "failed": list(self.failed),
            "failed_labels": list(self.failed_labels),
        }

    def describe(self) -> str:
        # 规则的中文说明写的是"要求"（有照片 / 小区已开放…），所以不通过时必须加
        # "未满足："，否则审计读起来像列表里的都是通过项。
        if self.approved:
            return "自动通过（满足：" + "、".join(self.passed_labels) + "）"
        return "未自动通过（未满足：" + "、".join(self.failed_labels) + "）"


def decide(rules: Sequence[RuleResult]) -> Decision:
    passed = tuple(name for name, ok, _ in rules if ok)
    failed = tuple(name for name, ok, _ in rules if not ok)
    labels = {name: label for name, _, label in rules}
    return Decision(
        approved=not failed,
        passed=passed, failed=failed,
        passed_labels=tuple(labels[name] for name in passed),
        failed_labels=tuple(labels[name] for name in failed),
    )


def describe_rules(rules: Sequence[RuleResult]) -> list:
    """给界面/日志用：每条规则的名字、中文说明与结果。"""
    return [{"rule": name, "label": label, "passed": ok} for name, ok, label in rules]


def cat_rules(*, nickname, location_note, health_status, has_photo, community_is_active) -> Tuple[RuleResult, ...]:
    text = "%s %s" % (nickname or "", location_note or "")
    return (
        ("has_photo", bool(has_photo), "有照片"),
        ("community_active", bool(community_is_active), "所属小区已开放"),
        ("location_not_precise", not PRECISE_ADDRESS.search(location_note or ""), "位置描述不含门牌号"),
        ("not_medical", (health_status or "").strip().upper() != "NEEDS_HELP", "不是医疗待助类"),
        ("clean_text", not CONTACT_OR_JUNK.search(text), "文字里没有联系方式或测试标记"),
        ("name_shape", bool(NAME_SHAPE.match((nickname or "").strip())), "名字格式正常"),
    )


def community_rules(*, name, street, known_streets) -> Tuple[RuleResult, ...]:
    normalized_street = (street or "").strip()
    return (
        ("name_shape", bool(NAME_SHAPE.match((name or "").strip())), "小区名格式正常"),
        ("street_known", normalized_street in {item.strip() for item in known_streets}, "街道已经存在"),
        ("clean_text", not CONTACT_OR_JUNK.search(name or ""), "名字里没有联系方式或测试标记"),
    )


def cat_decision(**kwargs) -> Decision:
    return decide(cat_rules(**kwargs))


def community_decision(**kwargs) -> Decision:
    return decide(community_rules(**kwargs))
