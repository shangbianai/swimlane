#!/usr/bin/env python3
"""
泳道图智能设计工具 - AI API 代理服务器
用于将前端请求转发到 Doubao-Seed-1.8 API
"""
import os
import json
import sys
import mimetypes
from pathlib import Path
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs
import requests

# 日志文件路径，可通过环境变量覆盖，便于本地开发和服务器部署共用。
LOG_FILE = os.getenv('SWIMLANE_LOG_FILE', str(Path(__file__).resolve().parent / 'backend.log'))

def log_debug(message):
    """记录DEBUG日志到文件和控制台"""
    log_message = f"[DEBUG] {message}"
    print(log_message)
    try:
        with open(LOG_FILE, 'a', encoding='utf-8') as f:
            f.write(f"{log_message}\n")
            f.flush()
    except:
        pass

def log_error(message):
    """记录ERROR日志到文件和控制台"""
    log_message = f"[ERROR] {message}"
    print(log_message)
    try:
        with open(LOG_FILE, 'a', encoding='utf-8') as f:
            f.write(f"{log_message}\n")
            f.flush()
    except:
        pass

# 尝试加载环境变量（可选，作为 config.json 之外的兜底）
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

# ============================================================
# 多 Provider 配置体系
# config.json 优先；不存在时从环境变量初始化；前端可在线修改并持久化
# ============================================================

CONFIG_FILE = os.getenv(
    'SWIMLANE_CONFIG_FILE',
    str(Path(__file__).resolve().parent / 'config.json')
)

PROVIDERS = {
    'doubao': {
        'name': 'Doubao（火山方舟）',
        'api_url': 'https://ark.cn-beijing.volces.com/api/v3/chat/completions',
        'default_model': 'doubao-seed-1-8-251228',
        'models': [
            'doubao-seed-1-8-251228',
            'doubao-pro-256k',
            'doubao-pro-32k',
            'doubao-pro-4k',
            'doubao-lite-32k'
        ],
        'docs': 'https://www.volcengine.com/docs/82379'
    },
    'deepseek': {
        'name': 'DeepSeek',
        'api_url': 'https://api.deepseek.com/v1/chat/completions',
        'default_model': 'deepseek-chat',
        'models': [
            'deepseek-chat',
            'deepseek-reasoner'
        ],
        'docs': 'https://platform.deepseek.com/api_keys'
    }
}

# 当前活跃配置（运行时可修改）
RUNTIME_CONFIG = {
    'provider': 'doubao',
    'providers': {
        p: {'api_key': '', 'model': meta['default_model']}
        for p, meta in PROVIDERS.items()
    }
}


def load_config():
    """优先从 config.json 加载；不存在时尝试从环境变量初始化（向后兼容）。"""
    cfg = None
    try:
        if os.path.exists(CONFIG_FILE):
            with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
                cfg = json.load(f)
    except Exception as e:
        log_error(f"读取 config.json 失败: {e}")

    if cfg and isinstance(cfg, dict):
        provider = cfg.get('provider')
        if provider in PROVIDERS:
            RUNTIME_CONFIG['provider'] = provider
        for p, info in (cfg.get('providers') or {}).items():
            if p in RUNTIME_CONFIG['providers'] and isinstance(info, dict):
                RUNTIME_CONFIG['providers'][p]['api_key'] = info.get('api_key', '') or ''
                RUNTIME_CONFIG['providers'][p]['model'] = (
                    info.get('model') or PROVIDERS[p]['default_model']
                )
        log_debug(f"已从 config.json 加载配置，当前 provider={RUNTIME_CONFIG['provider']}")
        return

    # 兜底：从环境变量初始化
    env_doubao_key = os.getenv('DOUBAO_API_KEY', '')
    env_doubao_model = os.getenv('DOUBAO_MODEL', '')
    if env_doubao_key:
        RUNTIME_CONFIG['providers']['doubao']['api_key'] = env_doubao_key
    if env_doubao_model:
        RUNTIME_CONFIG['providers']['doubao']['model'] = env_doubao_model

    env_ds_key = os.getenv('DEEPSEEK_API_KEY', '')
    env_ds_model = os.getenv('DEEPSEEK_MODEL', '')
    if env_ds_key:
        RUNTIME_CONFIG['providers']['deepseek']['api_key'] = env_ds_key
    if env_ds_model:
        RUNTIME_CONFIG['providers']['deepseek']['model'] = env_ds_model


def save_config():
    """把 RUNTIME_CONFIG 写入 config.json。"""
    try:
        with open(CONFIG_FILE, 'w', encoding='utf-8') as f:
            json.dump(RUNTIME_CONFIG, f, ensure_ascii=False, indent=2)
        try:
            os.chmod(CONFIG_FILE, 0o600)
        except Exception:
            pass
        log_debug("config.json 已保存")
        return True
    except Exception as e:
        log_error(f"保存 config.json 失败: {e}")
        return False


def mask_key(key):
    if not key:
        return ''
    if len(key) <= 8:
        return '*' * len(key)
    return f"{key[:4]}{'*' * max(4, len(key) - 8)}{key[-4:]}"


def get_public_config():
    """对外暴露的配置（脱敏）。"""
    out = {
        'provider': RUNTIME_CONFIG['provider'],
        'providers': {}
    }
    for p, meta in PROVIDERS.items():
        rc = RUNTIME_CONFIG['providers'].get(p, {})
        out['providers'][p] = {
            'name': meta['name'],
            'api_url': meta['api_url'],
            'default_model': meta['default_model'],
            'models': meta['models'],
            'docs': meta.get('docs', ''),
            'has_key': bool(rc.get('api_key')),
            'key_masked': mask_key(rc.get('api_key', '')),
            'model': rc.get('model') or meta['default_model']
        }
    return out


def get_active_credentials():
    """获取当前 provider 的 (api_url, api_key, model)。"""
    p = RUNTIME_CONFIG['provider']
    if p not in PROVIDERS:
        p = 'doubao'
    rc = RUNTIME_CONFIG['providers'].get(p, {})
    return (
        PROVIDERS[p]['api_url'],
        rc.get('api_key', ''),
        rc.get('model') or PROVIDERS[p]['default_model'],
        p,
        PROVIDERS[p]['name']
    )


load_config()

class SwimlaneProxyHandler(BaseHTTPRequestHandler):
    """处理泳道图工具的 API 请求"""
    
    def _send_cors_headers(self):
        """发送CORS头"""
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Access-Control-Allow-Methods', 'GET, POST, OPTIONS')
        self.send_header('Access-Control-Allow-Headers', 'Content-Type, Authorization')
        self.send_header('Access-Control-Max-Age', '3600')
    
    def do_OPTIONS(self):
        """处理 CORS 预检请求"""
        self.send_response(200)
        self._send_cors_headers()
        self.end_headers()
    
    def _read_json_body(self):
        try:
            length = int(self.headers.get('Content-Length', 0))
            body = self.rfile.read(length) if length > 0 else b''
            return json.loads(body.decode('utf-8')) if body else {}
        except Exception:
            return None

    def _send_json(self, status, payload):
        body = json.dumps(payload, ensure_ascii=False).encode('utf-8')
        self.send_response(status)
        self.send_header('Content-Type', 'application/json; charset=utf-8')
        self.send_header('Content-Length', str(len(body)))
        self._send_cors_headers()
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self):
        """处理 POST 请求"""
        try:
            # ---- /api/config: 保存配置 ----
            if self.path == '/api/config':
                data = self._read_json_body()
                if data is None:
                    return self._send_json(400, {"success": False, "error": "Invalid JSON"})
                provider = data.get('provider')
                api_key = data.get('api_key')
                model = data.get('model')
                if provider not in PROVIDERS:
                    return self._send_json(400, {
                        "success": False,
                        "error": f"未知 provider: {provider}",
                        "supported": list(PROVIDERS.keys())
                    })
                # 仅当显式提供 api_key（含空字符串）才覆盖；None 表示保留原值
                if api_key is not None:
                    RUNTIME_CONFIG['providers'][provider]['api_key'] = (api_key or '').strip()
                if model:
                    if model not in PROVIDERS[provider]['models']:
                        # 允许自定义 model 名（不限制白名单），仅做记录
                        log_debug(f"使用非预设 model: {provider}/{model}")
                    RUNTIME_CONFIG['providers'][provider]['model'] = model
                # 切换为当前 provider
                if data.get('activate', True):
                    RUNTIME_CONFIG['provider'] = provider
                ok = save_config()
                return self._send_json(200 if ok else 500, {
                    "success": ok,
                    "config": get_public_config(),
                    "message": "配置已保存" if ok else "保存失败，请查看后端日志"
                })

            # ---- /api/convert: 调用 LLM ----
            if self.path != '/api/convert':
                return self._send_json(404, {"error": "Not Found"})

            data = self._read_json_body()
            if data is None:
                return self._send_json(400, {"success": False, "error": "Invalid JSON"})

            user_input = data.get('input', '')
            input_type = data.get('type', 'text')

            if not user_input:
                return self._send_json(400, {"success": False, "error": "Input is required"})

            prompt = self._build_prompt(user_input, input_type)

            api_url, api_key, model, provider, provider_name = get_active_credentials()

            if not api_key:
                return self._send_json(500, {
                    "success": False,
                    "error": f"{provider_name} API Key 未配置",
                    "code": "API_KEY_MISSING",
                    "provider": provider,
                    "message": "请在前端右上角「设置」中配置 API Key"
                })

            payload = {
                "model": model,
                "messages": [{"role": "user", "content": prompt}],
                "temperature": 0.7,
                "max_tokens": 4000
            }
            headers = {
                'Content-Type': 'application/json',
                'Authorization': f'Bearer {api_key}'
            }

            log_debug(f"调用 {provider_name} | model={model} | url={api_url}")

            try:
                response = requests.post(api_url, headers=headers, json=payload, timeout=60)
                log_debug(f"API响应状态码: {response.status_code}")

                if response.status_code != 200:
                    error_detail = response.text[:500] if response.text else "无详细信息"
                    raise Exception(f"API返回错误 {response.status_code}: {error_detail}")
                
                response.raise_for_status()
                result = response.json()
                
                # 详细记录API响应
                log_debug(f"API响应完整内容: {json.dumps(result, ensure_ascii=False)[:1000]}")
                    
                # 提取生成的Markdown内容
                markdown_content = ""
                if 'choices' in result and len(result['choices']) > 0:
                    if 'message' in result['choices'][0] and 'content' in result['choices'][0]['message']:
                        markdown_content = result['choices'][0]['message']['content']
                    else:
                        log_error(f"choices[0]结构异常: {json.dumps(result['choices'][0], ensure_ascii=False)}")
                        markdown_content = "生成失败，API响应格式异常：缺少message.content字段"
                elif 'content' in result:
                    markdown_content = result['content']
                else:
                    log_error(f"API响应格式异常，完整响应: {json.dumps(result, ensure_ascii=False)[:500]}")
                    markdown_content = "生成失败，请检查API响应格式。"
                
                log_debug(f"API调用成功，生成内容长度: {len(markdown_content)}")
                log_debug(f"生成内容前500字符: {markdown_content[:500]}")
                
                # 检查生成内容是否有效
                if not markdown_content or markdown_content.strip() == "":
                    markdown_content = "生成失败，API返回内容为空。"
                elif "生成成功" in markdown_content and len(markdown_content.strip()) < 50:
                    log_error(f"生成内容可能异常，内容: {markdown_content}")
                
                # 返回响应
                response_data = {
                    "success": True,
                    "markdown": markdown_content
                }
                response_body = json.dumps(response_data, ensure_ascii=False).encode('utf-8')
                
                self.send_response(200)
                self.send_header('Content-Type', 'application/json; charset=utf-8')
                self.send_header('Content-Length', str(len(response_body)))
                self._send_cors_headers()
                self.end_headers()
                
                self.wfile.write(response_body)
                self.wfile.flush()  # 确保数据立即发送
                
            except requests.exceptions.HTTPError as e:
                error_detail = e.response.text[:500] if e.response.text else "无详细信息"
                last_error = f"HTTP错误 {e.response.status_code}: {error_detail}"
                log_error(f"HTTP错误: {last_error}")
                
                self.send_response(500)
                self.send_header('Content-Type', 'application/json')
                self._send_cors_headers()
                self.end_headers()
                error_response = {
                    "success": False,
                    "error": last_error,
                    "message": "API调用失败，请检查API Key和网络连接"
                }
                self.wfile.write(json.dumps(error_response, ensure_ascii=False).encode('utf-8'))
                
            except requests.exceptions.Timeout as e:
                last_error = f"API调用超时: {str(e)}"
                log_error(f"API调用超时: {last_error}")
                log_error(f"这可能是网络问题或API响应过慢")
            except requests.exceptions.RequestException as e:
                last_error = f"请求失败: {str(e)}"
                log_error(f"请求异常: {last_error}")
                log_error(f"异常类型: {type(e).__name__}")
                
                self.send_response(500)
                self.send_header('Content-Type', 'application/json')
                self._send_cors_headers()
                self.end_headers()
                error_response = {
                    "success": False,
                    "error": last_error,
                    "message": "网络请求失败，请检查网络连接"
                }
                self.wfile.write(json.dumps(error_response, ensure_ascii=False).encode('utf-8'))
                
        except Exception as e:
            self.send_response(500)
            self.send_header('Content-Type', 'application/json')
            self._send_cors_headers()
            self.end_headers()
            error_response = {
                "success": False,
                "error": f"服务器错误: {str(e)}"
            }
            self.wfile.write(json.dumps(error_response, ensure_ascii=False).encode('utf-8'))
    
    def _build_prompt(self, user_input, input_type):
        """构造AI提示词（支持步骤ID和跨泳道关系）。"""
        format_spec = """格式要求（严格按此输出，仅输出 Markdown，不要任何解释）：

参与部门：部门A | 部门B | 部门C

部门A：
  ├─ A1 步骤标题 (一句话说明)
  ├─ A2 步骤标题 (说明)
  └─ A3 步骤标题 (说明)

部门B：
  ├─ B1 步骤标题 (说明)
  └─ B2 步骤标题 (说明)

部门C：
  └─ C1 步骤标题 (说明)

跨泳道关系：
  A2 → B1
  B1 → C1
  C1 → B2
  B2 → A3

写作规则：
1. 第一行用「参与部门：」开头，部门用「 | 」分隔，按参与流程的左→右顺序排列。
2. 每个部门以「部门名：」单独成行，下面用「  ├─ 」「  └─ 」列出该泳道内的步骤。
3. 每个步骤必须有一个简短编号 ID，放在标题最前面：建议用「部门首字母 + 顺序数字」，如 A1、A2、B1、B2、C1。同一编号在全文唯一。
4. 步骤标题简洁（不超过 12 字），括号里的说明可选，写一句话补充。
5. 末尾单独加一段「跨泳道关系：」，用「 → 」连接产生交接的两个步骤 ID（一行一条或一行多个均可，例如 `A2 → B1 → C1`）。
   - 只在跨部门交接（不同泳道之间）时添加；同部门内的顺序由 ├─/└─ 自然表达，不需要重复写。
   - 至少给出主流程的关键交接关系；如果有反向回流（例如审核退回）也用 → 表示流向。
6. 不要输出多余的空段落、注释或代码块包裹。"""

        if input_type == 'mermaid':
            prompt = f"""你是一个资深的业务流程分析专家，擅长把流程图翻译成可读性强的泳道结构。请将以下 Mermaid 流程图转写成下面规定的 Markdown：

Mermaid 代码：
```mermaid
{user_input}
```

{format_spec}"""
        else:
            prompt = f"""你是一个资深的业务流程分析专家，擅长根据业务描述设计跨部门的泳道流程。请根据以下需求生成指定格式的 Markdown 泳道图：

需求描述：
{user_input}

{format_spec}"""

        return prompt
    
    def do_GET(self):
        # 处理 GET 请求：健康检查 + 配置 + 静态前端页面
        parsed_path = urlparse(self.path).path

        if parsed_path == '/api/health':
            api_url, api_key, model, provider, provider_name = get_active_credentials()
            return self._send_json(200, {
                "status": "ok",
                "service": "swimlane-tool",
                "provider": provider,
                "provider_name": provider_name,
                "model": model,
                "has_key": bool(api_key)
            })

        if parsed_path == '/api/config':
            return self._send_json(200, {
                "success": True,
                "config": get_public_config()
            })

        if parsed_path in ('/', '/index.html'):
            file_path = Path(__file__).resolve().parent / 'index.html'
        else:
            safe_path = parsed_path.lstrip('/')
            file_path = Path(__file__).resolve().parent / safe_path

        base_dir = Path(__file__).resolve().parent
        try:
            resolved = file_path.resolve()
            if not str(resolved).startswith(str(base_dir)) or not resolved.is_file():
                raise FileNotFoundError
            content = resolved.read_bytes()
            content_type = mimetypes.guess_type(str(resolved))[0] or 'application/octet-stream'
            if resolved.suffix.lower() in ('.html', '.css', '.js'):
                content_type += '; charset=utf-8'
            self.send_response(200)
            self.send_header('Content-Type', content_type)
            self.send_header('Content-Length', str(len(content)))
            self._send_cors_headers()
            self.end_headers()
            self.wfile.write(content)
        except Exception:
            self.send_response(404)
            self._send_cors_headers()
            self.end_headers()
            self.wfile.write(json.dumps({"error": "Not Found"}).encode('utf-8'))

    def log_message(self, format, *args):
        """自定义日志格式，输出到标准输出和日志文件"""
        message = f"[{self.address_string()}] {format % args}"
        print(message)
        # 同时写入日志文件
        try:
            with open('/opt/swimlane-tool/backend.log', 'a', encoding='utf-8') as f:
                f.write(f"{message}\n")
                f.flush()
        except:
            pass

def run_server(port=8222):
    """启动代理服务器"""
    server_address = ('', port)
    httpd = HTTPServer(server_address, SwimlaneProxyHandler)
    api_url, api_key, model, provider, provider_name = get_active_credentials()
    print(f"=" * 60)
    print(f"泳道图智能设计工具 - AI 代理服务器已启动")
    print(f"=" * 60)
    print(f"监听地址: http://localhost:{port}")
    print(f"前端页面: http://localhost:{port}/index.html")
    print(f"配置接口: http://localhost:{port}/api/config")
    print(f"当前 Provider: {provider_name} ({provider})")
    print(f"当前 Model: {model}")
    print(f"API Key: {'已配置' if api_key else '未配置（请在前端右上角设置）'}")
    print(f"=" * 60)
    print(f"按 Ctrl+C 停止服务器")
    print(f"=" * 60)
    
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\n正在关闭服务器...")
        httpd.shutdown()
        print("服务器已关闭")

if __name__ == "__main__":
    import sys
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8222
    run_server(port)
