"""拆分 `app.py` 之后必须一直成立的结构约束。

拆分本身是机械的，但很容易被后来的改动慢慢推回单体：往 `app.py` 里塞一个新路由、
在 router 里重新实现一个 payload、加一条与已有路由互相竞争的新路径。这个文件把
那几件事都变成会失败的测试。

行为等价性不在这里断言 —— `server/tests/` 里的 123 个 API 测试就是那个证明。
"""

import ast
import re
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
PACKAGE = REPO_ROOT / "server" / "helpcat"
APP = PACKAGE / "app.py"
ROUTERS = PACKAGE / "routers"

DOMAIN_MODULES = {
    "admin",
    "auth_routes",
    "cats",
    "communities",
    "feeding",
    "health",
    "impact",
    "leads",
    "media",
    "public_profiles",
    "reviews",
    "tasks",
}

SHARED_MODULES = {"errors", "media", "pagination", "serializers", "domain", "dependencies", "auto_review", "reviews", "login_guard"}


class AppSplitContractTests(unittest.TestCase):
    def app_source(self):
        return APP.read_text(encoding="utf-8")

    def router_sources(self):
        return {path.stem: path.read_text(encoding="utf-8") for path in sorted(ROUTERS.glob("*.py"))}

    def test_app_is_only_a_composition_root(self):
        source = self.app_source()
        self.assertEqual([], re.findall(r"^\s*@app\.(?:get|post|put|patch|delete)", source, re.MULTILINE),
                         "路由必须定义在 helpcat/routers/ 下，不能再写回 app.py")
        self.assertLess(len(source.splitlines()), 120, "app.py 只能是组装点，别再长回单体")

    def test_every_domain_router_exists_and_exposes_a_router(self):
        sources = self.router_sources()
        self.assertEqual(DOMAIN_MODULES, set(sources) - {"__init__"})
        for name, source in sources.items():
            if name == "__init__":
                continue
            self.assertIn("router = APIRouter()", source, "%s 必须暴露一个 router" % name)

    def test_the_composition_root_wires_every_router(self):
        source = self.app_source()
        for name in DOMAIN_MODULES:
            self.assertIn(name, source, "app.py 忘了装上 %s 路由" % name)

    def test_no_ambiguous_route_pairs(self):
        """同方法下不允许字面量段与路径参数段竞争，否则注册顺序会改变行为。"""
        import tempfile

        from server.helpcat.app import create_app

        with tempfile.TemporaryDirectory() as tmp:
            app = create_app("sqlite://", storage_root=Path(tmp))
            routes = [(sorted(route.methods), route.path) for route in app.routes if hasattr(route, "methods")]

        def overlaps(left, right):
            left_segments, right_segments = left.split("/"), right.split("/")
            if len(left_segments) != len(right_segments):
                return False
            for one, two in zip(left_segments, right_segments):
                if one == two or one.startswith("{") or two.startswith("{"):
                    continue
                return False
            return True

            found = []
            for index, (methods, path) in enumerate(routes):
                for other_methods, other_path in routes[index + 1:]:
                    if path == other_path or not (set(methods) & set(other_methods)):
                        continue
                    if overlaps(path, other_path):
                        found.append("%s %s <-> %s" % (sorted(set(methods) & set(other_methods))[0], path, other_path))
            self.assertEqual([], found, "路由对互相竞争，注册顺序会影响行为")

    def test_routers_do_not_reimplement_shared_helpers(self):
        for name, source in self.router_sources().items():
            if name == "__init__":
                continue
            definitions = re.findall(r"^def (\w+)\(", source, re.MULTILINE)
            duplicated = [item for item in definitions if item in {"error", "audit", "paginated_items", "iso_utc"}]
            self.assertEqual([], duplicated, "%s 里重复实现了共享助手 %s" % (name, duplicated))
            self.assertEqual(
                [],
                [item for item in definitions if item.endswith("_payload")],
                "%s 里又手写了 payload，应放进 serializers.py" % name,
            )

    def test_serializers_has_no_dead_duplicate_definitions(self):
        """拆分前 `task_payload` 定义了两遍，第二份把第一份悄悄覆盖掉了。"""
        tree = ast.parse((PACKAGE / "serializers.py").read_text(encoding="utf-8"))
        definitions = [node.name for node in tree.body if isinstance(node, ast.FunctionDef)]
        duplicates = sorted({name for name in definitions if definitions.count(name) > 1})
        self.assertEqual([], duplicates, "serializers.py 里有重复定义：%s" % duplicates)

    def test_shared_modules_are_leaf_helpers(self):
        """共享模块不能反向 import routers —— 那会变成新的循环依赖。"""
        for name in SHARED_MODULES:
            source = (PACKAGE / (name + ".py")).read_text(encoding="utf-8")
            self.assertNotIn("routers", source, "%s 不应该依赖 routers" % name)


if __name__ == "__main__":
    unittest.main()
