
"""Simple YAML/JSON parser for Guardian AI"""

def load_config(path: str = "config/model_selector.yaml"):
    from pathlib import Path
    path_obj = Path(__file__).parent.parent / path
    
    with open(path_obj) as f:
        content = f.read().strip()
    
    # JSON 形式
    try:
        import json
        return json.loads(content)
    except:
        pass
    
    # シンプル YAML
    lines = content.strip().split('\n')
    result = {}
    current_section = None
    
    for line in lines:
        if not line.strip() or line.strip().startswith('#'):
            continue
        
        # 見出し
        if ':' in line and not line.strip().startswith('-'):
            key, value = line.split(':', 1)
            key = key.strip()
            value = value.strip()
            
            if value and value.startswith('"'):
                result[key] = value[1:-1]
            elif value:
                result[key] = value
            else:
                result[key] = {}
                current_section = key
        elif current_section and line.strip():
            if line.strip().startswith('- '):
                item = line.strip()[2:]
                if item.startswith('"'):
                    result[current_section].append(item[1:-1])
                else:
                    result[current_section].append(item)
    
    return result

# YAML パーサーを暴露
SimpleYAMLParser = None
load_config = load_config
