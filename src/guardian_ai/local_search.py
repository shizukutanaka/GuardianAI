
"""Local Search: ファイル内検索機能（インターネットなし）"""
import os
import re
from typing import List, Dict, Any, Set

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
    
    def _should_exclude(self, path: str, name: str) -> bool:
        """排除チェック"""
        if name.startswith('.'):
            return True
        if name in self.exclude_patterns:
            return True
        for pattern in self.exclude_patterns:
            if pattern.startswith('*') and pattern.endswith('*'):
                if pattern.replace('*', '').replace('.', '').replace('*', '') in name:
                    continue
            if path.endswith(pattern):
                return True
        return False
    
    def search_files(self, pattern: str) -> List[str]:
        """拡張子でファイルを検索"""
        results = []
        for ext in pattern.split(','):
            ext = ext.strip()
            if ext.startswith('*.'):
                ext = ext[2:]
            if ext:
                for root, dirs, files in os.walk(self.root_path):
                    # 除外ディレクトリを排除
                    dirs[:] = [d for d in dirs if not d.startswith('.')]
                    for file in files:
                        if not self._should_exclude(root, file):
                            if file.endswith(ext):
                                results.append(os.path.join(root, file))
        return results
    
    def search_text(self, pattern: str, file: str, encoding: str = "utf-8") -> List[tuple]:
        """ファイル内テキスト検索"""
        results = []
        try:
            with open(file, encoding=encoding) as f:
                content = f.read()
                matches = [(m.start(), m.group()) for m in re.finditer(pattern, content)]
                results.append({"file": file, "matches": matches})
        except Exception as e:
            results.append({"file": file, "error": str(e)})
        return results
    
    def search_all(self, pattern: str) -> Dict[str, List[tuple]]:
        """複数ファイル同時検索"""
        files = self.search_files('*.py,*.json,*.yaml,*.txt,*.md,*.csv')
        results = {}
        
        for file in files:
            results[file] = self.search_text(pattern, file)
        
        return results

__all__ = ["LocalSearch"]
