# ------------------------------------------------------------------
# 本地覆盖官方的 hook-torch（--additional-hooks-dir 的 hook 优先级更高）。
#
# 原因：官方 hook 第 43 行执行 `collect_submodules("torch")`，
# 它会启动一个隔离子进程、逐个导入 torch 的全部子模块来做枚举；
# 在 torch 2.x + Windows 的组合下，该子进程在处理
# torch._inductor.template_heuristics 时以访问冲突（0xC0000005）崩溃，
# 导致打包整体中止（普通解释器里导入同一模块却完全正常，属于
# 隔离子进程环境的已知问题类型）。
#
# 处理：本 hook 不做子模块枚举。
# torch 的必需子模块由两条静态路径进入打包图——
#   1. torch 自身源码里的 import 语句（modulegraph 静态分析）；
#   2. transformers / sentence-transformers 等调用方的 import。
# 二进制（torch/lib 下的 DLL）与数据文件仍完整收集，保证推理可用。
# 若打包后运行时报某个 torch 子模块 ModuleNotFoundError，
# 再用 --hiddenimport torch.<子模块> 单独补上即可。
# ------------------------------------------------------------------

from PyInstaller.utils.hooks import (
    collect_data_files,
    collect_dynamic_libs,
    is_module_satisfies,
)

if is_module_satisfies("PyInstaller >= 6.0"):
    from PyInstaller import compat
    from PyInstaller.utils.hooks import PY_DYLIB_PATTERNS

    #/ 与官方 hook 保持一致：torch 源码以 pyz+py 模式随包携带。
    module_collection_mode = "pyz+py"
    warn_on_missing_hiddenimports = False

    datas = collect_data_files(
        "torch",
        excludes=[
            "**/*.h",
            "**/*.hpp",
            "**/*.cuh",
            "**/*.lib",
            "**/*.cpp",
            "**/*.pyi",
            "**/*.cmake",
        ],
    )

    #/ 不再调用 collect_submodules("torch")——这是崩溃源头。
    hiddenimports = []

    binaries = collect_dynamic_libs(
        "torch",
        # 确保带版本号的 .so/.dll 也被收集
        search_patterns=PY_DYLIB_PATTERNS + ['*.so.*'],
    )

    #/ 官方 hook 在 Windows 下还会收集 MKL 相关 DLL（仅当 torch 依赖 mkl 时
    #/ 才有结果；PyPI 的 CPU 轮子通常没有）。保留该逻辑以兼容不同来源的 torch。
    if compat.is_win:
        def _collect_mkl_dlls():
            import packaging.requirements
            from _pyinstaller_hooks_contrib.compat import importlib_metadata

            dist = importlib_metadata.distribution("torch")
            requirements = [packaging.requirements.Requirement(req) for req in dist.requires or []]
            requirements = [req.name for req in requirements if req.marker is None or req.marker.evaluate()]
            if 'mkl' not in requirements:
                return []

            try:
                dist = importlib_metadata.distribution("mkl")
            except importlib_metadata.PackageNotFoundError:
                return []
            requirements = ['mkl'] + requirements

            mkl_binaries = []
            for requirement in requirements:
                try:
                    dist = importlib_metadata.distribution(requirement)
                except importlib_metadata.PackageNotFoundError:
                    continue

                for dist_file in (dist.files or []):
                    dll_file = dist.locate_file(dist_file).resolve()
                    if not dll_file.match('**/Library/bin/*.dll'):
                        continue
                    mkl_binaries.append((str(dll_file), '.'))

            return mkl_binaries

        try:
            mkl_binaries = _collect_mkl_dlls()
        except Exception:
            mkl_binaries = []
        binaries += mkl_binaries
