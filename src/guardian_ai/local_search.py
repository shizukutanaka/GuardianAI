"""Local Search: ファイル内検索機能（インターネットなし）"""
import fnmatch
import os
import re
from typing import Any, Dict, List, Set


class LocalSearch:
    """ローカルファイル検索 - 外部通信なし"""

    def __init__(self, root_path: str = "."):
        self.root_path = os.path.abspath(root_path)
        self.exclude_patterns: Set[str] = {
            '__pycache__',
            'venv',
            'env',
            '.venv',
            'node_modules',
            'dist',
            '*.pyc',
            '*.pyo',
            '*.so',
            '*.dll',
        }

    def _is_excluded(self, name: str) -> bool:
        """名前が除外対象か判定（隠しファイル・除外パターン）。"""
        if name.startswith('.'):
            return True
        for pattern in self.exclude_patterns:
            if any(c in pattern for c in '*?['):
                if fnmatch.fnmatch(name, pattern):
                    return True
            elif name == pattern:
                return True
        return False

    def search_files(self, pattern: str) -> List[str]:
        """拡張子でファイルを検索（カンマ区切りで複数可）"""
        results = []
        for ext in pattern.split(','):
            ext = ext.strip()
            if ext.startswith('*.'):
                ext = ext[1:]
            if not ext:
                continue
            if not ext.startswith('.'):
                ext = '.' + ext
            for root, dirs, files in os.walk(self.root_path):
                dirs[:] = [d for d in dirs if not self._is_excluded(d)]
                for file in files:
                    if not self._is_excluded(file) and file.endswith(ext):
                        results.append(os.path.join(root, file))
        return results

    def search_text(self, pattern: str, file: str, encoding: str = "utf-8") -> List[Dict[str, Any]]:
        """ファイル内テキスト検索"""
        try:
            with open(file, encoding=encoding) as f:
                content = f.read()
            matches = [(m.start(), m.group()) for m in re.finditer(pattern, content)]
            return [{"file": file, "matches": matches}]
        except Exception as e:
            return [{"file": file, "error": str(e)}]

    def search_all(self, pattern: str) -> Dict[str, List[Dict[str, Any]]]:
        """複数ファイル同時検索"""
        files = self.search_files('*.py,*.json,*.yaml,*.yml,*.txt,*.md,*.csv')
        return {file: self.search_text(pattern, file) for file in files}


__all__ = ["LocalSearch"]
