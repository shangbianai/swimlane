# 泳道图智能设计工具

输入需求描述或 Mermaid 流程图，自动生成可编辑的 Markdown 泳道图内容，并渲染为泳道图。

## 线上地址

- 当前服务：`http://182.92.97.169:8222/index.html`
- 健康检查：`http://182.92.97.169:8222/api/health`

## 本地运行

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
python3 proxy_server.py 8222
```

然后访问：`http://127.0.0.1:8222/index.html`

## 环境变量

复制 `.env.example` 为 `.env`，并配置：

```bash
DOUBAO_API_KEY=your_doubao_api_key
DOUBAO_MODEL=doubao-seed-1-8-251228
```

不要把 `.env` 提交到 Git。

## 服务器部署

默认部署目录：`/opt/swimlane-tool`

```bash
cd /opt/swimlane-tool
pip3 install -r requirements.txt
cp .env.example .env
bash start_services.sh
```

如需使用 systemd：

```bash
sudo cp swimlane-tool.service /etc/systemd/system/swimlane-tool.service
sudo systemctl daemon-reload
sudo systemctl enable swimlane-tool.service
sudo systemctl restart swimlane-tool.service
sudo systemctl status swimlane-tool.service
```
