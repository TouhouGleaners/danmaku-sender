"""打包前裁剪 PySide6 的 QML 运行时，只保留应用用到的模块与风格。

背景：Nuitka 的 pyside6 插件检测到 QtQuickWidgets 的使用即全量收录 PySide6/qml 模块树（日志原文 "Including 'qml' Qt plugins due to 'PySide6.QtQuickWidgets' usage."），
各模块的插件 DLL 还会经链接闭包引入其依赖的 Qt DLL——例如 qml/QtWebEngine 的插件引入 Qt6WebEngineCore.dll 约 203 MB。
应用的 .qml 只用 QtQuick / QtQuick.Controls / QtQuick.Layouts，其余模块运行时不会加载，可于打包前删除。

规则（改 QML import、改 QQuickStyle 风格或升级 PySide6 前先读）：

1. 应用 .qml 的模块 import 只允许白名单（QtQuick / QtQuick.Controls / QtQuick.Layouts）；
   新增模块先扩白名单再改代码，白名单外的 import 令本脚本报错退出。
   目录形态的 import（import "../../x"）指向仓库内文件，不进白名单。
2. QQC2 风格取源码中 QQuickStyle.setStyle 的设置值，连同其 qmldir 的 "import ... auto" 回退链整目录保留（如 FluentWinUI3 -> Fusion -> Basic）；
   Basic 恒保留（风格未覆盖某控件时的回退基底）。风格不出现在 import 里，不进白名单。
3. 保留集按 .qml 的 import 与 qmldir 的 depends / import 声明递推求闭包（如 QtQuick.Templates、QtQuick.Controls.impl 由风格模板与 qmldir 声明引入）。
   模块目录只保留本层文件与保留集内的子目录；
   风格目录整棵保留（含 dark / light / icons 等资源子目录）。
4. 本脚本默认仅检查；--trim 才执行移除。本地开发环境不要使用 --trim（会删除 venv 里的 QML 模块）；
   仅在 CI 的 pip install 之后、nuitka 之前执行。

用法：
    python scripts/slim_qml_runtime.py          # 检查，列出未使用的模块
    python scripts/slim_qml_runtime.py --trim   # 移除未使用的模块（CI 使用）
"""

import argparse
import re
import shutil
import struct
from collections import deque
from pathlib import Path

import PySide6

REPO_ROOT = Path(__file__).resolve().parents[1]
APP_SRC_ROOT = REPO_ROOT / "src" / "danmaku_sender"


class QmlRuntimeSlimmer:
    """PySide6/qml 保留集的推导与未使用模块的移除。"""

    WHITELIST = frozenset({"QtQuick", "QtQuick.Controls", "QtQuick.Layouts"})
    ALWAYS_KEEP_MODULES = frozenset({"QtQml"})
    ALWAYS_KEEP_STYLES = frozenset({"Basic"})

    _IMPORT_RE = re.compile(r"^\s*import\s+([A-Za-z_][\w.]*)")
    _STRING_IMPORT_RE = re.compile(r'^\s*import\s+"([^"]+)"')
    _QMDDIR_DEP_RE = re.compile(r"^\s*(?:depends|import)\s+([A-Za-z_][\w.]*)")
    _STYLE_RE = re.compile(r"""QQuickStyle\.setStyle\(\s*["']([^"']+)["']\s*\)""")
    _FALLBACK_RE = re.compile(r"^\s*import\s+QtQuick\.Controls\.([A-Za-z_]\w*)\s+auto\b")

    @staticmethod
    def parse_imports(qml_file: Path) -> tuple[set[str], set[str]]:
        """读取一个 .qml 文件的 import 行。

        Args:
            qml_file (Path): QML 文件。

        Returns:
            tuple[set[str], set[str]]: 模块 import 与目录形态 import 的路径原文。
        """
        modules: set[str] = set()
        paths: set[str] = set()
        for line in qml_file.read_text(encoding="utf-8").splitlines():
            match = QmlRuntimeSlimmer._IMPORT_RE.match(line)
            if match:
                modules.add(match.group(1))
                continue
            match = QmlRuntimeSlimmer._STRING_IMPORT_RE.match(line)
            if match:
                paths.add(match.group(1))
        return modules, paths

    @staticmethod
    def collect_app_imports() -> set[str]:
        """汇总应用 .qml 的模块 import，白名单外的报错退出。

        Returns:
            set[str]: 应用用到的 QML 模块集合。

        Raises:
            SystemExit: 存在白名单外的模块 import。
        """
        modules: set[str] = set()
        violations: list[tuple[str, str]] = []
        for qml_file in sorted(APP_SRC_ROOT.rglob("*.qml")):
            for module in QmlRuntimeSlimmer.parse_imports(qml_file)[0]:
                modules.add(module)
                if module not in QmlRuntimeSlimmer.WHITELIST:
                    violations.append((module, str(qml_file.relative_to(REPO_ROOT))))
        if violations:
            print("白名单外的模块 import：")
            for module, location in violations:
                print(f"  {module} --> {location}")
            print("help: 新增 QML 模块须先扩充 QmlRuntimeSlimmer.WHITELIST。")
            raise SystemExit(1)
        return modules

    @staticmethod
    def configured_style() -> str | None:
        """从源码读取 QQuickStyle.setStyle 的风格名。

        Returns:
            str | None: 风格名；源码未设置时为 None。
        """
        for py_file in sorted(APP_SRC_ROOT.rglob("*.py")):
            match = QmlRuntimeSlimmer._STYLE_RE.search(py_file.read_text(encoding="utf-8"))
            if match:
                return match.group(1)
        return None

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
        pending = [style]
        while pending:
            qmldir = controls_dir / pending.pop() / "qmldir"
            if not qmldir.is_file():
                continue
            for line in qmldir.read_text(encoding="utf-8").splitlines():
                match = QmlRuntimeSlimmer._FALLBACK_RE.match(line)
                if match and match.group(1) not in chain:
                    chain.append(match.group(1))
                    pending.append(match.group(1))
        return chain

    @staticmethod
    def expand(qml_root: Path, app_modules: set[str], style: str | None) -> tuple[set[Path], set[str]]:
        """推导保留目录集与保留模块集。

        Args:
            qml_root (Path): PySide6/qml。
            app_modules (set[str]): 应用 import 的模块。
            style (str | None): QQuickStyle 风格名。

        Returns:
            tuple[set[Path], set[str]]: 保留目录与保留模块（模块名为点分路径）。
        """
        controls_dir = qml_root / "QtQuick" / "Controls"
        styles = set(QmlRuntimeSlimmer.ALWAYS_KEEP_STYLES)
        if style:
            styles.update(QmlRuntimeSlimmer.style_chain(style, controls_dir))

        keep_dirs: set[Path] = set()
        keep_modules: set[str] = set()
        scan_queue: deque[Path] = deque()

        def keep_dir(directory: Path, wholesale: bool) -> None:
            if not directory.is_dir() or directory in keep_dirs:
                return
            keep_dirs.add(directory)
            scan_queue.append(directory)
            if wholesale:
                for sub in directory.rglob("*"):
                    if sub.is_dir() and sub not in keep_dirs:
                        keep_dirs.add(sub)
                        scan_queue.append(sub)

        def keep_module(module: str) -> None:
            keep_modules.add(module)
            keep_dir(qml_root.joinpath(*module.split(".")), wholesale=False)

        for module in app_modules | QmlRuntimeSlimmer.ALWAYS_KEEP_MODULES:
            keep_module(module)
        for style_name in styles:
            keep_dir(controls_dir / style_name, wholesale=True)

        while scan_queue:
            directory = scan_queue.popleft()
            qmldir = directory / "qmldir"
            if qmldir.is_file():
                for line in qmldir.read_text(encoding="utf-8").splitlines():
                    match = QmlRuntimeSlimmer._QMDDIR_DEP_RE.match(line)
                    if match and (qml_root / match.group(1).replace(".", "/")).is_dir():
                        keep_module(match.group(1))
            for qml_file in directory.glob("*.qml"):
                modules, paths = QmlRuntimeSlimmer.parse_imports(qml_file)
                for module in modules:
                    if (qml_root / module.replace(".", "/")).is_dir():
                        keep_module(module)
                for path in paths:
                    target = (directory / path).resolve()
                    if target.is_relative_to(qml_root):
                        keep_dir(target, wholesale=False)
        return keep_dirs, keep_modules

    @staticmethod
    def plan(qml_root: Path) -> tuple[set[Path], set[str], str | None]:
        """生成完整裁剪方案并做闭包自检。

        Args:
            qml_root (Path): PySide6/qml。

        Returns:
            tuple[set[Path], set[str], str | None]: 保留目录、保留模块、风格名。

        Raises:
            SystemExit: 闭包自检失败（解析回归或环境异常）。
        """
        app_modules = QmlRuntimeSlimmer.collect_app_imports()
        style = QmlRuntimeSlimmer.configured_style()
        keep_dirs, keep_modules = QmlRuntimeSlimmer.expand(qml_root, app_modules, style)

        required = QmlRuntimeSlimmer.WHITELIST | QmlRuntimeSlimmer.ALWAYS_KEEP_MODULES
        required |= {"QtQuick.Templates", "QtQuick.Controls.impl"}
        missing = sorted(
            module
            for module in required
            if not (qml_root / module.replace(".", "/")) in keep_dirs
        )
        controls_dir = qml_root / "QtQuick" / "Controls"
        required_styles = set(QmlRuntimeSlimmer.ALWAYS_KEEP_STYLES)
        if style:
            required_styles.update(QmlRuntimeSlimmer.style_chain(style, controls_dir))
        for style_name in sorted(required_styles):
            if controls_dir / style_name not in keep_dirs:
                missing.append(f"QtQuick.Controls.{style_name}")
        if missing:
            print(f"闭包自检失败，缺少保留项：{', '.join(missing)}")
            raise SystemExit(1)
        return keep_dirs, keep_modules, style

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
        doomed = [
            path
            for path in qml_root.rglob("*")
            if path.is_dir() and path not in survivors
        ]
        doomed.sort(key=lambda path: len(path.parts))
        tops: list[Path] = []
        for path in doomed:
            if any(path.is_relative_to(top) for top in tops):
                continue
            tops.append(path)
        return sorted(tops)

    @staticmethod
    def tree_stats(root: Path) -> tuple[int, int]:
        """统计目录树的文件数与字节数。

        Args:
            root (Path): 目录。

        Returns:
            tuple[int, int]: 文件数、字节数。
        """
        files = [path for path in root.rglob("*") if path.is_file()]
        return len(files), sum(path.stat().st_size for path in files)

    @staticmethod
    def shipped_pyds(pyside_dir: Path) -> list[Path]:
        """推导随包收录的 PySide6 pyd。

        以应用源码 import 的模块为起点，再沿 pyd 与其 Qt6 DLL 的链接闭包补上隐含模块
        （Qt6Widgets.dll 即隐含 QtWidgets.pyd）——与 Nuitka 的 pyside6 插件
        getImplicitImports 同一意图，但从已安装的二进制推导，换 PySide6 或 Nuitka 版本无需维护静态表。

        Args:
            pyside_dir (Path): PySide6 目录。

        Returns:
            list[Path]: 随包收录的 pyd 文件。
        """
        modules: set[str] = set()
        for py_file in APP_SRC_ROOT.rglob("*.py"):
            modules.update(re.findall(r"PySide6\.([A-Za-z_]\w*)", py_file.read_text(encoding="utf-8")))

        dll_index = {path.name.lower(): path for path in pyside_dir.glob("*.dll")}
        seen: set[Path] = set()
        queue: deque[Path] = deque()

        def enqueue(module: str) -> None:
            pyd = pyside_dir / f"{module}.pyd"
            if pyd.is_file() and pyd.resolve() not in seen:
                seen.add(pyd.resolve())
                queue.append(pyd)

        for module in sorted(modules):
            enqueue(module)
        while queue:
            for name in QmlRuntimeSlimmer.pe_imports(queue.popleft()):
                target = dll_index.get(name.lower())
                if target is None or target.resolve() in seen:
                    continue
                seen.add(target.resolve())
                queue.append(target)
                match = re.fullmatch(r"Qt6(.+)\.dll", target.name, re.IGNORECASE)
                if match:
                    enqueue("Qt" + match.group(1))
        return sorted(path for path in seen if path.suffix == ".pyd")

    @staticmethod
    def pe_imports(dll_path: Path) -> set[str]:
        """读取 PE 文件导入表与延迟导入表中的 DLL 名。

        Args:
            dll_path (Path): DLL 文件。

        Returns:
            set[str]: 被链接的 DLL 文件名；解析失败时为空集。
        """
        names: set[str] = set()
        try:
            with dll_path.open("rb") as handle:
                head = handle.read(8192)
                if head[:2] != b"MZ":
                    return names
                pe = struct.unpack_from("<I", head, 0x3C)[0]
                if head[pe : pe + 4] != b"PE\0\0":
                    return names
                optional = pe + 24
                magic = struct.unpack_from("<H", head, optional)[0]
                directories = optional + (112 if magic == 0x20B else 96)
                section_table = optional + struct.unpack_from("<H", head, pe + 20)[0]
                sections = []
                for index in range(struct.unpack_from("<H", head, pe + 6)[0]):
                    entry = section_table + index * 40
                    virtual_size, virtual_addr, raw_size, raw_addr = struct.unpack_from(
                        "<IIII", head, entry + 8
                    )
                    sections.append((virtual_addr, max(virtual_size, raw_size), raw_addr))

                def rva_to_offset(rva: int) -> int | None:
                    for virtual_addr, span, raw_addr in sections:
                        if virtual_addr <= rva < virtual_addr + span:
                            return raw_addr + (rva - virtual_addr)
                    return None

                for directory, stride, name_field in ((1, 20, 12), (13, 32, 4)):
                    entry_rva = struct.unpack_from("<I", head, directories + directory * 8)[0]
                    offset = rva_to_offset(entry_rva) if entry_rva else None
                    while offset is not None:
                        handle.seek(offset + name_field)
                        name_rva = struct.unpack_from("<I", handle.read(4))[0]
                        if name_rva == 0:
                            break
                        name_offset = rva_to_offset(name_rva)
                        if name_offset is None:
                            break
                        handle.seek(name_offset)
                        names.add(handle.read(256).split(b"\0", 1)[0].decode("ascii", "replace"))
                        offset += stride
        except (OSError, struct.error):
            return set()
        return names

    @staticmethod
    def linked_closure(starts: list[Path], root: Path) -> dict[str, int]:
        """计算起始 DLL 的链接闭包中位于 root 下的 DLL。

        Args:
            starts (list[Path]): 起始 DLL（模块插件等）。
            root (Path): PySide6 目录，Qt6 DLL 的所在地。

        Returns:
            dict[str, int]: 闭包命中的 root 下 DLL（文件名 -> 字节数），不含起始 DLL 自身。
        """
        index = {path.name.lower(): path for path in root.glob("*.dll")}
        starts_resolved = {path.resolve() for path in starts}
        found: dict[str, int] = {}
        queue = deque(starts)
        seen = set(starts_resolved)
        while queue:
            for name in QmlRuntimeSlimmer.pe_imports(queue.popleft()):
                target = index.get(name.lower())
                if target is None or target.resolve() in seen:
                    continue
                seen.add(target.resolve())
                if target.resolve() not in starts_resolved:
                    found[target.name] = target.stat().st_size
                queue.append(target)
        return found


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

    keep_dirs, keep_modules, style = QmlRuntimeSlimmer.plan(qml_root)
    tops = QmlRuntimeSlimmer.doomed_tops(qml_root, keep_dirs)

    if not tops:
        print("PySide6/qml 无未使用模块。")
        return

    rows: list[tuple[str, int, int]] = []
    for top in tops:
        count, size = QmlRuntimeSlimmer.tree_stats(top)
        rows.append((str(top.relative_to(qml_root)) + "/", count, size))

    baseline_starts = [dll for directory in keep_dirs for dll in directory.rglob("*.dll")]
    baseline_starts += QmlRuntimeSlimmer.shipped_pyds(pyside_dir)
    baseline_starts += list((pyside_dir / "qt-plugins").rglob("*.dll"))
    baseline = QmlRuntimeSlimmer.linked_closure(baseline_starts, pyside_dir)
    closure_rows: list[tuple[str, dict[str, int]]] = []
    union: dict[str, int] = {}
    for top in tops:
        pulled = {
            name: size
            for name, size in QmlRuntimeSlimmer.linked_closure(list(top.rglob("*.dll")), pyside_dir).items()
            if name not in baseline
        }
        if pulled:
            closure_rows.append((str(top.relative_to(qml_root)) + "/", pulled))
            union.update(pulled)
    closure_rows.sort(key=lambda row: -sum(row[1].values()))

    total_files, total_bytes = QmlRuntimeSlimmer.tree_stats(qml_root)
    removed_files = sum(count for _, count, _ in rows)
    removed_bytes = sum(size for _, _, size in rows)
    verb = "已移除" if args.trim else "未使用"
    print(f"PySide6/qml {verb}模块 {len(rows)} 个（{removed_files} 个文件, {removed_bytes / 1e6:.1f} MB）：")
    for name, count, size in rows:
        print(f"  {name:<30}{count:>6} 个文件{size / 1e6:>7.1f} MB")

    if closure_rows:
        print()
        print(f"连带移除的 Qt6 DLL（插件链接闭包扣除保留侧所需，去重合计 {sum(union.values()) / 1e6:.1f} MB）：")
        for name, pulled in closure_rows:
            print(f"  {name:<30}{sum(pulled.values()) / 1e6:>7.1f} MB")
            for dll, size in sorted(pulled.items(), key=lambda item: -item[1]):
                print(f"    {dll:<30}{size / 1e6:>7.1f} MB")

    chain = QmlRuntimeSlimmer.style_chain(style, qml_root / "QtQuick" / "Controls") if style else []
    chain_text = " -> ".join(chain) if style else "未设置（仅 Basic）"
    print()
    print(
        f"PySide6/qml 保留模块 {len(keep_modules)} 个"
        f"（{total_files - removed_files} 个文件, {(total_bytes - removed_bytes) / 1e6:.1f} MB）："
    )
    print(f"  白名单 {', '.join(sorted(QmlRuntimeSlimmer.WHITELIST))}")
    print(f"  风格 {chain_text}")
    if args.trim:
        for name, _, _ in rows:
            shutil.rmtree(qml_root / name.rstrip("/"))
    else:
        print()
        print("警告：--trim 会删除 venv 里的 QML 模块，仅限打包流水线使用；非打包场景且不确定后果时不要执行。")


if __name__ == "__main__":
    main()
