"""打包前裁剪 PySide6 的 QML 运行时，只保留应用用到的模块与风格。

背景：Nuitka 的 pyside6 插件检测到 QtQuickWidgets 的使用即全量收录 PySide6/qml 模块树（日志原文 "Including 'qml' Qt plugins due to 'PySide6.QtQuickWidgets' usage."），
各模块的插件 DLL 还会经链接闭包引入其依赖的 Qt DLL——例如 qml/QtWebEngine 的插件引入 Qt6WebEngineCore.dll 约 203 MB。
应用的 .qml 只用 QtQuick / QtQuick.Controls / QtQuick.Layouts，其余模块运行时不会加载，可于打包前删除。

规则（改 QML import、改 QQuickStyle 风格或升级 PySide6 前先读）：

1. 应用 .qml 的模块 import 只允许白名单（QtQuick / QtQuick.Controls / QtQuick.Layouts）；新增模块先扩白名单再改代码，白名单外的 import 令本脚本报错退出。
   目录形态的 import（import "../../x"）指向仓库内文件，不进白名单。
2. QQC2 风格用 ast 从源码取 QQuickStyle.setStyle 的字符串字面量，取不出字面量即报错退出；风格连同其 qmldir 的 "import ... auto" 回退链整目录保留（如 FluentWinUI3 -> Fusion -> Basic）。
   Basic 恒保留（风格未覆盖某控件时的回退基底）。风格不出现在 import 里，不进白名单。
3. 保留集按 .qml 与 .js 辅助脚本的 import、qmldir 的 depends / import / default import 声明递推求闭包；字符串 import 指向文件时保留其所在目录。
   qmldir 的 optional 声明不入保留集——可选即非必需，风格的可选依赖已由 setStyle 链覆盖（如 Controls 对各风格的 optional import）。
   模块目录只保留本层文件与保留集内的子目录；风格目录整棵保留（含 dark / light / icons 等资源子目录）。
4. 本脚本默认仅检查；--trim 才执行移除。本地开发环境不要使用 --trim（会删除 venv 里的 QML 模块）；
   仅在 CI 的 pip install 之后、nuitka 之前执行。

Typical usage example::
    python scripts/trim_qml_runtime.py          # 检查，列出未使用的模块
    python scripts/trim_qml_runtime.py --trim   # 移除未使用的模块（CI 使用）
"""

import argparse
import ast
import re
import shutil
import time
from collections import deque
from collections.abc import Iterable
from pathlib import Path
from typing import NamedTuple, Protocol

import pefile
import PySide6

REPO_ROOT = Path(__file__).resolve().parents[1]
APP_SRC_ROOT = REPO_ROOT / "src" / "danmaku_sender"


class Plan(NamedTuple):
    """裁剪方案的推导结果。

    Attributes:
        keep_dirs (set[Path]): 保留目录集。
        keep_modules (set[str]): 保留模块集（模块名为点分路径）。
        tops (list[Path]): 待删目录，每棵不保留子树取顶端目录。
        chain (list[str]): 风格回退链，起始风格在前、逐级回退在后。
    """

    keep_dirs: set[Path]
    keep_modules: set[str]
    tops: list[Path]
    chain: list[str]


class KeepSet:
    """QML 运行时保留集的增量构建：目录与模块的登记及依赖扫描。"""

    def __init__(self, qml_root: Path) -> None:
        """初始化保留集。

        Args:
            qml_root (Path): PySide6/qml。
        """
        self.qml_root = qml_root
        self.dirs: set[Path] = set()
        self.modules: set[str] = set()
        self._scan_queue: deque[Path] = deque()

    def keep_dir(self, directory: Path, wholesale: bool) -> None:
        """登记保留目录；wholesale 为 True 时连同整棵子树登记。

        Args:
            directory (Path): 目录。
            wholesale (bool): 是否整棵保留（风格目录含 dark / light / icons 等资源子目录）。
        """
        if not directory.is_dir():
            return
        if directory not in self.dirs:
            self.dirs.add(directory)
            self._scan_queue.append(directory)
        if wholesale:
            for sub in (path for path in directory.rglob("*") if path.is_dir()):
                self.keep_dir(sub, False)

    def keep_module(self, module: str) -> None:
        """登记保留模块；模块目录不存在的名称不登记。

        Args:
            module (str): 点分模块名。
        """
        directory = QmlRuntimeTrimmer.module_dir(self.qml_root, module)
        if not directory.is_dir():
            return
        self.modules.add(module)
        self.keep_dir(directory, False)

    def scan(self) -> None:
        """按登记目录的依赖边递推登记，直到没有新增为止。"""
        while self._scan_queue:
            modules, dirs = QmlRuntimeTrimmer.dir_edges(self._scan_queue.popleft(), self.qml_root)
            for module in modules:
                self.keep_module(module)
            for directory in dirs:
                self.keep_dir(directory, False)


class _ImportEntry(Protocol):
    """pefile 导入表条目中用到的形状：dll 为被链接的 DLL 名。"""

    dll: bytes


class QmlRuntimeTrimmer:
    """PySide6/qml 保留集的推导与未使用模块的移除。"""

    WHITELIST = frozenset({"QtQuick", "QtQuick.Controls", "QtQuick.Layouts"})
    ALWAYS_KEEP_MODULES = frozenset({"QtQml"})
    ALWAYS_KEEP_STYLES = frozenset({"Basic"})
    RUNTIME_REQUIRED_MODULES = frozenset({"QtQuick.Templates", "QtQuick.Controls.impl"})  # QML Runtime 隐式依赖

    _IMPORT_RE = re.compile(r"^\s*\.?import\s+([A-Za-z_][\w.]*)")
    _STRING_IMPORT_RE = re.compile(r'^\s*\.?import\s+"([^"]+)"')
    _QMLDIR_EDGE_RE = re.compile(r"^\s*(?:(default|optional)\s+)?(depends|import)\s+([A-Za-z_][\w.]*)")
    _QT_DLL_RE = re.compile(r"Qt6(.+)\.dll", re.IGNORECASE)

    @staticmethod
    def parse_imports(source_file: Path) -> tuple[set[str], set[str]]:
        """读取一个 .qml 或 .js 源文件的 import 行。

        Args:
            source_file (Path): QML 或 JS 源文件。

        Returns:
            tuple[set[str], set[str]]: 模块 import 与目录形态 import 的路径原文。
        """
        modules: set[str] = set()
        paths: set[str] = set()
        for line in source_file.read_text(encoding="utf-8").splitlines():
            if match := QmlRuntimeTrimmer._IMPORT_RE.match(line):
                modules.add(match.group(1))
            elif match := QmlRuntimeTrimmer._STRING_IMPORT_RE.match(line):
                paths.add(match.group(1))
        return modules, paths

    @staticmethod
    def module_dir(qml_root: Path, module: str) -> Path:
        """把点分模块名折算为 qml 树下的目录。

        Args:
            qml_root (Path): PySide6/qml。
            module (str): 点分模块名，如 QtQuick.Controls。

        Returns:
            Path: 模块目录。
        """
        return qml_root.joinpath(*module.split("."))

    @staticmethod
    def qmldir_edges(qmldir: Path) -> tuple[set[str], set[str]]:
        """读取 qmldir 的依赖声明。

        Args:
            qmldir (Path): qmldir 文件。

        Returns:
            tuple[set[str], set[str]]: 必留模块（depends / import / default import，optional 除外）与其中的 import 边模块（供风格回退链游走）。
        """
        required: set[str] = set()
        fallbacks: set[str] = set()
        for line in qmldir.read_text(encoding="utf-8").splitlines():
            if match := QmlRuntimeTrimmer._QMLDIR_EDGE_RE.match(line):
                kind, word, module = match.groups()
                if kind == "optional":
                    continue
                required.add(module)
                if word == "import":
                    fallbacks.add(module)
        return required, fallbacks

    @staticmethod
    def dir_edges(directory: Path, qml_root: Path) -> tuple[set[str], set[Path]]:
        """收集一个目录的依赖边：qmldir 的必留声明与 .qml/.js 的 import，只含可解析的落点。

        Args:
            directory (Path): qml 树下的目录。
            qml_root (Path): PySide6/qml。

        Returns:
            tuple[set[str], set[Path]]: 依赖的模块名与字符串 import 指向的目录。
        """
        modules: set[str] = set()
        dirs: set[Path] = set()
        qmldir = directory / "qmldir"
        if qmldir.is_file():
            modules |= QmlRuntimeTrimmer.qmldir_edges(qmldir)[0]
        for script in [*directory.glob("*.qml"), *directory.glob("*.js")]:
            imported, paths = QmlRuntimeTrimmer.parse_imports(script)
            modules |= imported
            for path in paths:
                target = (directory / path).resolve()
                if target.is_relative_to(qml_root):
                    dirs.add(target.parent if target.is_file() else target)
        kept_modules = {module for module in modules if QmlRuntimeTrimmer.module_dir(qml_root, module).is_dir()}
        return kept_modules, dirs

    @staticmethod
    def collect_app_imports() -> set[str]:
        """汇总应用 .qml 与 .js 的模块 import，白名单外的报错退出。

        Returns:
            set[str]: 应用用到的 QML 模块集合。

        Raises:
            SystemExit: 存在白名单外的模块 import。
        """
        modules: set[str] = set()
        violations: list[tuple[str, str]] = []
        for source_file in sorted([*APP_SRC_ROOT.rglob("*.qml"), *APP_SRC_ROOT.rglob("*.js")]):
            for module in QmlRuntimeTrimmer.parse_imports(source_file)[0]:
                modules.add(module)
                if module not in QmlRuntimeTrimmer.WHITELIST:
                    violations.append((module, str(source_file.relative_to(REPO_ROOT))))
        if violations:
            print("白名单外的模块 import：")
            for module, location in violations:
                print(f"  {module} --> {location}")
            print("help: 新增 QML 模块须先扩充 QmlRuntimeTrimmer.WHITELIST。")
            raise SystemExit(1)
        return modules

    @staticmethod
    def app_py_facts() -> tuple[set[str], str | None]:
        """用 ast 从应用源码提取 PySide6 使用面（模块与 QQuickStyle 风格名）。

        Returns:
            tuple[set[str], str | None]: PySide6 模块名与风格名；源码未设置风格时后者为 None。

        Raises:
            SystemExit: QQuickStyle.setStyle 的风格名不是字符串字面量。
        """
        modules: set[str] = set()
        style: str | None = None
        for py_file in sorted(APP_SRC_ROOT.rglob("*.py")):
            tree = ast.parse(py_file.read_text(encoding="utf-8"))
            modules |= QmlRuntimeTrimmer._py_pyside_modules(tree)
            style = style or QmlRuntimeTrimmer._py_style(tree, py_file)
        return modules, style

    @staticmethod
    def _py_pyside_modules(tree: ast.AST) -> set[str]:
        """收集 ast 中 PySide6 的模块 import（含 from PySide6 import X 形态）。

        Args:
            tree (ast.AST): 源文件的 ast。

        Returns:
            set[str]: PySide6 模块名。
        """
        modules: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                modules.update(alias.name.split(".")[1] for alias in node.names if alias.name.startswith("PySide6."))
            elif isinstance(node, ast.ImportFrom) and node.module:
                module = node.module
                if module == "PySide6":
                    modules.update(alias.name for alias in node.names)
                elif module.startswith("PySide6."):
                    modules.add(module.split(".")[1])
        return modules

    @staticmethod
    def _py_style(tree: ast.AST, py_file: Path) -> str | None:
        """取 ast 中 QQuickStyle.setStyle 的风格名字面量，取不出即报错。

        Args:
            tree (ast.AST): 源文件的 ast。
            py_file (Path): 源文件，报错定位用。

        Returns:
            str | None: 风格名；未设置风格时为 None。

        Raises:
            SystemExit: 风格名不是字符串字面量。
        """
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and QmlRuntimeTrimmer._is_qquick_setstyle(node):
                literal = node.args[0] if node.args else None
                if not isinstance(literal, ast.Constant) or not isinstance(literal.value, str):
                    print(f"QQuickStyle.setStyle 的风格名不是字符串字面量：{py_file.relative_to(REPO_ROOT)}")
                    raise SystemExit(1)
                return literal.value
        return None

    @staticmethod
    def _is_qquick_setstyle(node: ast.AST) -> bool:
        """判断 ast 节点是否为 QQuickStyle.setStyle 调用。

        Args:
            node (ast.AST): ast 节点。

        Returns:
            bool: 是则为 True。
        """
        if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Attribute):
            return False
        return node.func.attr == "setStyle" and any(
            getattr(part, "id", getattr(part, "attr", "")) == "QQuickStyle" for part in ast.walk(node.func.value)
        )

    @staticmethod
    def style_chain(style: str, controls_dir: Path) -> list[str]:
        """沿 qmldir 的 "import ... auto" 推导风格回退链。

        Args:
            style (str): 风格名，如 FluentWinUI3。
            controls_dir (Path): PySide6/qml/QtQuick/Controls。

        Returns:
            list[str]: 风格名序列，起始风格在前、逐级回退在后。
        """
        chain = [style]
        for name in chain:
            qmldir = controls_dir / name / "qmldir"
            if not qmldir.is_file():
                continue
            for module in QmlRuntimeTrimmer.qmldir_edges(qmldir)[1]:
                if module.startswith("QtQuick.Controls.") and (fallback := module.removeprefix("QtQuick.Controls.")) not in chain:
                    chain.append(fallback)
        return chain

    @staticmethod
    def expand(qml_root: Path, app_modules: set[str], chain: list[str]) -> tuple[set[Path], set[str]]:
        """推导保留目录集与保留模块集。

        Args:
            qml_root (Path): PySide6/qml。
            app_modules (set[str]): 应用 import 的模块。
            chain (list[str]): 风格回退链，全部整目录保留。

        Returns:
            tuple[set[Path], set[str]]: 保留目录与保留模块。
        """
        controls_dir = QmlRuntimeTrimmer.module_dir(qml_root, "QtQuick.Controls")
        keep = KeepSet(qml_root)
        for module in app_modules | QmlRuntimeTrimmer.ALWAYS_KEEP_MODULES:
            keep.keep_module(module)
        for name in {*chain, *QmlRuntimeTrimmer.ALWAYS_KEEP_STYLES}:
            keep.keep_dir(controls_dir / name, wholesale=True)
        keep.scan()
        return keep.dirs, keep.modules

    @staticmethod
    def plan(qml_root: Path, style: str | None) -> Plan:
        """生成完整裁剪方案并做闭包自检。

        Args:
            qml_root (Path): PySide6/qml。
            style (str | None): QQuickStyle 风格名。

        Returns:
            Plan: 裁剪方案。

        Raises:
            SystemExit: 闭包自检失败（解析回归或环境异常）。
        """
        app_modules = QmlRuntimeTrimmer.collect_app_imports()
        controls_dir = QmlRuntimeTrimmer.module_dir(qml_root, "QtQuick.Controls")
        chain = QmlRuntimeTrimmer.style_chain(style, controls_dir) if style else []
        keep_dirs, keep_modules = QmlRuntimeTrimmer.expand(qml_root, app_modules, chain)
        tops = QmlRuntimeTrimmer.doomed_tops(qml_root, keep_dirs)

        missing = sorted(
            module
            for module in QmlRuntimeTrimmer.RUNTIME_REQUIRED_MODULES | QmlRuntimeTrimmer.ALWAYS_KEEP_MODULES | app_modules
            if module not in keep_modules
        )
        required_styles = set(chain) | QmlRuntimeTrimmer.ALWAYS_KEEP_STYLES
        missing.extend(
            sorted(f"QtQuick.Controls.{name}" for name in required_styles if (controls_dir / name) not in keep_dirs)
        )
        for directory in keep_dirs:
            modules, dirs = QmlRuntimeTrimmer.dir_edges(directory, qml_root)
            missing.extend(sorted(modules - keep_modules))
            missing.extend(sorted(str(path.relative_to(qml_root)) for path in dirs - keep_dirs))
        if missing:
            print(f"闭包自检失败，缺少保留项：{', '.join(missing)}")
            raise SystemExit(1)
        return Plan(keep_dirs=keep_dirs, keep_modules=keep_modules, tops=tops, chain=chain)

    @staticmethod
    def doomed_tops(qml_root: Path, keep_dirs: set[Path]) -> list[Path]:
        """计算待删目录（每棵不保留子树取顶端目录，整棵删除）。

        Args:
            qml_root (Path): PySide6/qml。
            keep_dirs (set[Path]): 保留目录集。

        Returns:
            list[Path]: 待删目录，按路径升序。
        """
        survivors = set(keep_dirs)
        for directory in keep_dirs:
            for parent in directory.parents:
                if parent == qml_root:
                    break
                survivors.add(parent)
        doomed = {path for path in qml_root.rglob("*") if path.is_dir() and path not in survivors}
        return sorted(path for path in doomed if path.parent not in doomed)

    @staticmethod
    def kept_files(keep_dirs: set[Path], qml_root: Path) -> list[Path]:
        """统计保留面内的全部文件（每个保留目录取本层文件，子目录各自是保留目录）。

        Args:
            keep_dirs (set[Path]): 保留目录集。
            qml_root (Path): PySide6/qml。

        Returns:
            list[Path]: 保留的文件。
        """
        files = [path for path in qml_root.glob("*") if path.is_file()]
        for directory in keep_dirs:
            files.extend(path for path in directory.glob("*") if path.is_file())
        return files

    @staticmethod
    def _remove_tree(directory: Path) -> None:
        """删除目录树；Windows 上安全软件可能短暂占用文件，失败后最多重试 5 次、间隔 1 秒。

        Args:
            directory (Path): 待删目录。

        Raises:
            PermissionError: 重试后文件仍被占用。
        """
        for attempt in range(6):
            try:
                shutil.rmtree(directory)
                return
            except PermissionError:
                if attempt == 5:
                    raise
                time.sleep(1)

    @staticmethod
    def tree_stats(files: Iterable[Path]) -> tuple[int, int]:
        """统计一批文件的个数与字节数。

        Args:
            files (Iterable[Path]): 文件。

        Returns:
            tuple[int, int]: 文件数、字节数。
        """
        sizes = [path.stat().st_size for path in files]
        return len(sizes), sum(sizes)

    @staticmethod
    def pe_imports(dll_path: Path) -> set[str]:
        """读取 PE 文件导入表与延迟导入表中的 DLL 名。

        Args:
            dll_path (Path): DLL 文件。

        Returns:
            set[str]: 被链接的 DLL 文件名；解析失败按无链接处理并打印告警。
        """
        try:
            pe = pefile.PE(str(dll_path), fast_load=True)
            try:
                pe.parse_data_directories(
                    directories=[
                        pefile.DIRECTORY_ENTRY["IMAGE_DIRECTORY_ENTRY_IMPORT"],
                        pefile.DIRECTORY_ENTRY["IMAGE_DIRECTORY_ENTRY_DELAY_IMPORT"],
                    ]
                )
                entries: list[_ImportEntry] = [
                    *getattr(pe, "DIRECTORY_ENTRY_IMPORT", []),
                    *getattr(pe, "DIRECTORY_ENTRY_DELAY_IMPORT", []),
                ]
                return {entry.dll.decode("ascii", "replace") for entry in entries}
            finally:
                pe.close()
        except (OSError, pefile.PEFormatError):
            print(f"PE 解析失败，按无链接处理：{dll_path.name}")
            return set()

    @staticmethod
    def walk_links(starts: Iterable[Path], index: dict[str, Path], memo: dict[str, set[str]]) -> set[Path]:
        """沿 PE 导入图广度优先求链接闭包，返回途经的全部文件（含起点）。

        PySide6 的二进制文件名互不重复，按文件名判等价。系统 DLL 不在索引内，自然跳过。

        Args:
            starts (Iterable[Path]): 起始二进制。
            index (dict[str, Path]): 文件名（小写）到文件的索引，导入名按此解析。
            memo (dict[str, set[str]]): 文件名到导入名集合的记忆化表，跨调用共享。

        Returns:
            set[Path]: 闭包内的全部文件。
        """
        starts = list(starts)
        seen = {path.name.lower() for path in starts}
        queue = deque(starts)
        reached = set(starts)
        while queue:
            path = queue.popleft()
            key = path.name.lower()
            if key not in memo:
                memo[key] = QmlRuntimeTrimmer.pe_imports(path)
            deps = memo[key]
            for dep in deps:
                target = index.get(dep.lower())
                if target is None or target.name.lower() in seen:
                    continue
                seen.add(target.name.lower())
                reached.add(target)
                queue.append(target)
        return reached

    @staticmethod
    def shipped_pyds(
        pyside_dir: Path, modules: set[str], index: dict[str, Path], memo: dict[str, set[str]]
    ) -> list[Path]:
        """推导随包收录的 PySide6 pyd（应用 import 加链接闭包隐含的绑定）。

        绑定发现规则：闭包内出现 Qt6X.dll 即隐含 QtX.pyd（与 Nuitka 的 getImplicitImports 同义），反复扩展直到没有新增。

        Args:
            pyside_dir (Path): PySide6 目录。
            modules (set[str]): 应用 import 的 PySide6 模块。
            index (dict[str, Path]): 文件名（小写）到文件的索引。
            memo (dict[str, set[str]]): 导入名集合的记忆化表。

        Returns:
            list[Path]: 随包收录的 pyd 文件。
        """
        batch = [pyside_dir / f"{name}.pyd" for name in sorted(modules) if (pyside_dir / f"{name}.pyd").is_file()]
        seen = set(batch)
        reached: set[Path] = set()
        while batch:
            reached |= QmlRuntimeTrimmer.walk_links(batch, index, memo)
            batch = [pyd for pyd in QmlRuntimeTrimmer._qt_pyds(reached, pyside_dir) if pyd not in seen]
            seen.update(batch)
        return sorted(path for path in reached if path.suffix == ".pyd")

    @staticmethod
    def _qt_pyds(reached: Iterable[Path], pyside_dir: Path) -> list[Path]:
        """取出闭包内 Qt6 DLL 对应的 PySide6 绑定 pyd。

        Args:
            reached (Iterable[Path]): 闭包内的文件。
            pyside_dir (Path): PySide6 目录。

        Returns:
            list[Path]: 命中的绑定 pyd。
        """
        pyds: list[Path] = []
        for path in reached:
            if match := QmlRuntimeTrimmer._QT_DLL_RE.fullmatch(path.name):
                pyd = pyside_dir / f"Qt{match.group(1)}.pyd"
                if pyd.is_file():
                    pyds.append(pyd)
        return pyds


def main() -> None:
    """检查或移除 QML 运行时中未使用的模块。"""
    parser = argparse.ArgumentParser(description="检查 PySide6/qml 中未被应用使用的模块")
    parser.add_argument("--trim", action="store_true", help="移除未使用的模块（默认仅检查）")
    args = parser.parse_args()

    pyside_dir = Path(PySide6.__file__).resolve().parent
    qml_root = pyside_dir / "qml"
    if not (qml_root / "QtQuick" / "Controls").is_dir():
        print(f"未找到 QML 运行时目录：{qml_root}")
        raise SystemExit(1)

    pyside_modules, style = QmlRuntimeTrimmer.app_py_facts()
    trim_plan = QmlRuntimeTrimmer.plan(qml_root, style)
    if not trim_plan.tops:
        print("PySide6/qml 无未使用模块。")
        return

    index = {path.name.lower(): path for path in pyside_dir.glob("*.dll")}
    memo: dict[str, set[str]] = {}
    rows = [(top, *QmlRuntimeTrimmer.tree_stats(path for path in top.rglob("*") if path.is_file())) for top in trim_plan.tops]
    removed_files = sum(count for _, count, _ in rows)
    removed_bytes = sum(size for _, _, size in rows)
    kept_count, kept_bytes = QmlRuntimeTrimmer.tree_stats(QmlRuntimeTrimmer.kept_files(trim_plan.keep_dirs, qml_root))
    total_files, total_bytes = removed_files + kept_count, removed_bytes + kept_bytes

    baseline_starts = [dll for dll in QmlRuntimeTrimmer.kept_files(trim_plan.keep_dirs, qml_root) if dll.suffix == ".dll"]
    baseline_starts += QmlRuntimeTrimmer.shipped_pyds(pyside_dir, pyside_modules, index, memo)
    baseline_starts += list((pyside_dir / "qt-plugins").rglob("*.dll"))
    baseline_names = {
        path.name
        for path in QmlRuntimeTrimmer.walk_links(baseline_starts, index, memo)
        if path.parent == pyside_dir and path.suffix == ".dll"
    }
    closure_rows: list[tuple[str, dict[str, int]]] = []
    union: dict[str, int] = {}
    for top, _, _ in rows:
        pulled = {
            path.name: path.stat().st_size
            for path in QmlRuntimeTrimmer.walk_links(top.rglob("*.dll"), index, memo)
            if path.parent == pyside_dir and path.suffix == ".dll" and path.name not in baseline_names
        }
        if pulled:
            closure_rows.append((str(top.relative_to(qml_root)) + "/", pulled))
            union.update(pulled)
    closure_rows.sort(key=lambda row: -sum(row[1].values()))

    if args.trim:
        for top, _, _ in rows:
            QmlRuntimeTrimmer._remove_tree(top)

    verb = "已移除" if args.trim else "未使用"
    print(f"PySide6/qml {verb}模块 {len(rows)} 个（{removed_files} 个文件, {removed_bytes / 1e6:.1f} MB）：")
    for top, count, size in rows:
        print(f"  {str(top.relative_to(qml_root)) + '/':<30}{count:>6} 个文件{size / 1e6:>7.1f} MB")

    if closure_rows:
        print()
        print(f"连带移除的 Qt6 DLL（插件链接闭包扣除保留侧所需，去重合计 {sum(union.values()) / 1e6:.1f} MB）：")
        for name, pulled in closure_rows:
            print(f"  {name:<30}{sum(pulled.values()) / 1e6:>7.1f} MB")
            for dll, size in sorted(pulled.items(), key=lambda item: -item[1]):
                print(f"    {dll:<30}{size / 1e6:>7.1f} MB")

    chain_text = " -> ".join(trim_plan.chain) if trim_plan.chain else "未设置（仅 Basic）"
    print()
    print(f"PySide6/qml 保留模块 {len(trim_plan.keep_modules)} 个（{total_files - removed_files} 个文件, {(total_bytes - removed_bytes) / 1e6:.1f} MB）：")
    print(f"  白名单 {', '.join(sorted(QmlRuntimeTrimmer.WHITELIST))}")
    print(f"  风格 {chain_text}")
    if not args.trim:
        print()
        print("警告：--trim 会删除 venv 里的 QML 模块，仅限打包 Workflow 使用；非打包场景且不确定后果时不要执行。")


if __name__ == "__main__":
    main()
