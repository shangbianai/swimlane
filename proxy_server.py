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

# 尝试加载环境变量（可选）
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    # 如果dotenv未安装，跳过环境变量加载
    pass

# Doubao-Seed-1.8 API 配置
API_URL = os.getenv('DOUBAO_API_URL', 'https://ark.cn-beijing.volces.com/api/v3/chat/completions')
API_KEY = os.getenv('DOUBAO_API_KEY')
MODEL = os.getenv('DOUBAO_MODEL', 'doubao-seed-1-8-251228')
BACKUP_API_KEY = os.getenv('DOUBAO_BACKUP_API_KEY')

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
    
    def do_POST(self):
        """处理 POST 请求"""
        try:
            # 只处理 /api/convert 端点
            if self.path != '/api/convert':
                self.send_response(404)
                self._send_cors_headers()
                self.end_headers()
                self.wfile.write(json.dumps({"error": "Not Found"}).encode('utf-8'))
                return
            
            # 读取请求体
            content_length = int(self.headers.get('Content-Length', 0))
            body = self.rfile.read(content_length)
            
            # 解析 JSON
            try:
                data = json.loads(body.decode('utf-8'))
            except json.JSONDecodeError:
                self.send_response(400)
                self._send_cors_headers()
                self.end_headers()
                self.wfile.write(json.dumps({"error": "Invalid JSON"}).encode('utf-8'))
                return
            
            # 获取用户输入（需求文本或Mermaid代码）
            user_input = data.get('input', '')
            input_type = data.get('type', 'text')  # 'text' 或 'mermaid'
            
            if not user_input:
                self.send_response(400)
                self._send_cors_headers()
                self.end_headers()
                self.wfile.write(json.dumps({"error": "Input is required"}).encode('utf-8'))
                return
            
            # 构造提示词
            prompt = self._build_prompt(user_input, input_type)

            if not API_KEY:
                self.send_response(500)
                self.send_header('Content-Type', 'application/json; charset=utf-8')
                self._send_cors_headers()
                self.end_headers()
                error_response = {
                    "success": False,
                    "error": "DOUBAO_API_KEY 未配置",
                    "message": "请在服务器环境变量或 .env 文件中配置 DOUBAO_API_KEY"
                }
                self.wfile.write(json.dumps(error_response, ensure_ascii=False).encode('utf-8'))
                return
            
            # 构造API请求
            payload = {
                "model": MODEL,
                "messages": [
                    {
                        "role": "user",
                        "content": prompt
                    }
                ],
                "temperature": 0.7,
                "max_tokens": 4000
            }
            
            # 调用 Doubao-Seed-1.8 API
            headers = {
                'Content-Type': 'application/json',
                'Authorization': f'Bearer {API_KEY}'
            }
            
            log_debug(f"使用API Key: {API_KEY[:8]}...")
            log_debug(f"请求URL: {API_URL}")
            log_debug(f"请求Payload: {json.dumps(payload, ensure_ascii=False)[:200]}...")
            
            try:
                log_debug(f"开始调用API，超时时间: 60秒")
                response = requests.post(
                    API_URL,
                    headers=headers,
                    json=payload,
                    timeout=60
                )
                log_debug(f"API调用完成，状态码: {response.status_code}")
                
                log_debug(f"响应状态码: {response.status_code}")
                
                if response.status_code == 401 and BACKUP_API_KEY:
                    # 如果主API Key失败，尝试备用Key
                    log_debug(f"主API Key失败，尝试备用Key...")
                    headers['Authorization'] = f'Bearer {BACKUP_API_KEY}'
                    response = requests.post(
                        API_URL,
                        headers=headers,
                        json=payload,
                        timeout=60
                    )
                    log_debug(f"备用Key响应状态码: {response.status_code}")
                
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
        """构造AI提示词"""
        if input_type == 'mermaid':
            prompt = f"""你是一个专业的业务流程分析专家。请将以下Mermaid流程图转换为指定格式的Markdown：

Mermaid代码：
```mermaid
{user_input}
```

请严格按照以下格式输出Markdown：

格式要求：
参与部门：部门1 | 部门2 | 部门3

部门1：
  ├─ 步骤1 (说明)
  └─ 步骤2 (说明)

部门2：
  ├─ 步骤1 (说明)
  └─ 步骤2 (说明)

请确保：
1. 第一行列出所有参与部门，用"|"分隔
2. 每个部门的步骤使用树状结构（├─ 和 └─）
3. 步骤说明用括号标注
4. 保持逻辑清晰，步骤顺序合理
5. 只输出Markdown内容，不要添加其他说明文字"""
        else:
            prompt = f"""你是一个专业的业务流程分析专家。请根据以下需求描述，生成指定格式的Markdown泳道图：

需求描述：
{user_input}

请严格按照以下格式输出Markdown：

格式要求：
参与部门：部门1 | 部门2 | 部门3

部门1：
  ├─ 步骤1 (说明)
  └─ 步骤2 (说明)

部门2：
  ├─ 步骤1 (说明)
  └─ 步骤2 (说明)

请确保：
1. 第一行列出所有参与部门，用"|"分隔
2. 每个部门的步骤使用树状结构（├─ 和 └─）
3. 步骤说明用括号标注
4. 保持逻辑清晰，步骤顺序合理
5. 只输出Markdown内容，不要添加其他说明文字"""
        
        return prompt
    
    def do_GET(self):
        # 处理 GET 请求：健康检查 + 静态前端页面
        parsed_path = urlparse(self.path).path
        if parsed_path == '/api/health':
            self.send_response(200)
            self.send_header('Content-Type', 'application/json; charset=utf-8')
            self._send_cors_headers()
            self.end_headers()
            response = {
                "status": "ok",
                "service": "swimlane-tool",
                "api_url": API_URL,
                "model": MODEL
            }
            self.wfile.write(json.dumps(response, ensure_ascii=False).encode('utf-8'))
            return

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
    print(f"=" * 60)
    print(f"泳道图智能设计工具 - AI代理服务器已启动")
    print(f"=" * 60)
    print(f"监听地址: http://localhost:{port}")
    print(f"API端点: http://localhost:{port}/api/convert")
    print(f"健康检查: http://localhost:{port}/api/health")
    print(f"目标 API: {API_URL}")
    print(f"模型: {MODEL}")
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
