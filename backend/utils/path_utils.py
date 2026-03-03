from pathlib import Path


def get_dir_depth(path: str) -> int:
    """计算路径的目录层级深度（以盘符根目录为第 0 层）。"""
    return len(Path(path).parts) - 1


def get_short_parent(path: str, levels: int = 2) -> str:
    """返回父目录路径的末尾 N 级，用于搜索结果展示。"""
    parts = Path(path).parent.parts
    return str(Path(*parts[-levels:])) if len(parts) >= levels else str(Path(path).parent)


def is_excluded(path: str, exclude_dirs: list[str], exclude_patterns: list[str]) -> bool:
    """判断路径是否应被排除（目录名匹配或文件名 glob 匹配）。"""
    import fnmatch
    p = Path(path)
    # 检查目录名
    for part in p.parts:
        if part in exclude_dirs:
            return True
    # 检查文件名 glob 模式
    for pattern in exclude_patterns:
        if fnmatch.fnmatch(p.name, pattern):
            return True
    return False
