# 泳道图智能设计工具

> 把一段「业务流程描述」或一份「Mermaid 流程图」一键转成可编辑、可导出的彩色泳道图。
> 内置 AI 格式化、跨泳道连线、实时预览、专注审阅、PNG 一键导出。

![banner](https://img.shields.io/badge/UI-Deep%20Space-7C5CFF) ![ai](https://img.shields.io/badge/AI-Doubao%20%7C%20DeepSeek-22D3EE) ![export](https://img.shields.io/badge/Export-PNG%20Hi--DPI-F472B6)

---

## ✨ 这次更新带来什么

- 🎨 **Deep Space 暗色主题**：从配色、间距、阴影到背景动效全部重做，告别"夜店感"，更像专业制图工具。
- 🧭 **左侧竖向 Step 导航**：1 → 2 → 3 三步带流向动画，可折叠，主区让给内容。
- 🪟 **专注审阅大窗**：泳道图改为应用内全屏遮罩弹窗，纵向延伸看更舒服。
- 🪄 **Step 2 双栏工作台**：左侧编辑结构化内容，右侧实时渲染（带 320ms 防抖）。
- 🔁 **跨泳道横向连线（核心）**：解析「跨泳道关系」段，用 SVG overlay 绘制带箭头的虚线折线，跨多列也能正确连。
- 🧩 **节点视觉重做**：去掉左侧加粗竖条 → 改为四边同色细边框；节点之间的向下箭头换成 SVG 线 + 三角，更像流程图。
- 🪪 **节点编号**：每个步骤左上角带短 ID（A1、B1…），方便阅读和引用。
- 🪟 **支持向左滚动**：长泳道居中 + 父级 `overflow-x:auto`，左右内容都能完整看到。
- 🍞 **完整 Toast 系统**：success / error / warning / info / loading，自动堆叠、带进度条。
- 🔑 **多供应商 API Key 配置**：支持「豆包 / DeepSeek」一键切换，前端弹窗输入即写入 `config.json`，无需改 `.env`、无需重启。
- 🖼 **高清 PNG 导出**：完整图（含连线）2× scale，一键下载。

---

## 📦 在线体验

- 服务地址：`http://182.92.97.169:8222/`
- 健康检查：`http://182.92.97.169:8222/api/health`

> 如未配置 API Key，首次进入页面会自动弹出「设置」面板让你填写。

---

## 🚀 三步使用流程

### Step 1 · 输入业务流程
- 用自然语言描述业务（推荐），或粘贴 Mermaid `flowchart TD ...` 代码。
- 不想写？工具栏点 **「演示样例」** 一键跳到 Step 2 看完整效果。

### Step 2 · 编辑结构 + 实时预览
- 左侧：AI 拆好的结构化 Markdown，可以手动调整。
- 右侧：实时渲染的彩色泳道图（带跨泳道连线）。
- 工具栏点 **「专注审阅」** 进入大窗模式。

### Step 3 · 高清预览与导出
- 横向滚动可查看完整图。
- 一键导出 PNG（包含跨泳道连线）。

---

## ✍️ 输入语法（AI 输出 / 手写都遵循）

```
参与部门：用户 | 电商平台 | 支付机构 | 仓储物流

用户：
  ├─ U1 浏览选购 (查找目标商品)
  ├─ U2 提交订单 (确认地址与支付方式)
  └─ U4 验收评价 (确认收货并评价)

电商平台：
  ├─ P1 订单校验 (验证库存与有效性)
  ├─ P2 转发支付指令 (同步金额到支付机构)
  ├─ P3 同步支付状态 (回写订单状态)
  ├─ P4 生成发货指令 (派单给仓储)
  └─ P5 处理售后 (审核退换/反馈)

支付机构：
  ├─ C1 接收并执行扣款 (校验账户与余额)
  └─ C2 反馈支付结果 (同步成功/失败)

仓储物流：
  ├─ W1 接收发货指令 (核对订单与库存)
  ├─ W2 出库打包 (打印物流单号)
  └─ W3 配送至用户 (实时同步轨迹)

跨泳道关系：
  U2 → P1
  P1 → P2 → C1
  C1 → C2 → P3
  P3 → P4 → W1
  W1 → W2 → W3
  W3 → U4
  U4 → P5
```

### 语法约定

| 元素 | 说明 |
|---|---|
| `参与部门：A \| B \| C` | 第一行声明所有部门，用 ` \| ` 分隔；左→右就是泳道顺序 |
| `部门名：` | 单独成行，下面缩进列出该泳道步骤 |
| `├─ ID 标题 (说明)` | 中间步骤；ID 建议「部门首字母+序号」，全文唯一 |
| `└─ ID 标题 (说明)` | 该泳道最后一个步骤 |
| `跨泳道关系：` | 末尾段，用 ` → ` 连接产生交接的两个 ID，可写多条或链式（`A1 → B1 → C1`） |

> 没写 ID 也能渲染（自动生成 `D1S1` 这类 fallback），但跨泳道连线必须有 ID 才能匹配。

---

## 🛠 本地运行

### 1) 拉代码 + 装依赖

```bash
git clone https://github.com/shangbianai/swimlane.git
cd swimlane
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

### 2) 启动后端（同时托管前端）

```bash
python3 proxy_server.py 8222
```

打开浏览器访问：`http://127.0.0.1:8222/`

### 3) 配置 API Key（两种方式任选）

**A. 推荐：前端配置**
- 进入页面右上角点齿轮图标
- 选择供应商（豆包 / DeepSeek）→ 输入 API Key → 选择模型 → 保存
- 配置写入 `config.json`，立即生效，无需重启

**B. 备选：环境变量**
- 复制 `.env.example` 为 `.env` 并填写：
  ```bash
  DOUBAO_API_KEY=your_doubao_api_key
  DEEPSEEK_API_KEY=your_deepseek_api_key
  ```
- `.env` 已加入 `.gitignore`，不会被提交。

> 优先级：`config.json` > `.env`。前端保存的优先生效。

---

## 🔌 后端 API

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/api/health` | 返回当前供应商、模型、是否已配置 Key |
| GET | `/api/config` | 返回脱敏后的配置（Key 掩码显示） |
| POST | `/api/config` | 保存配置 `{provider, api_key, model}`，写入 `config.json` |
| POST | `/api/convert` | AI 格式化入口 `{user_input, input_type}`，未配 Key 时返回 `code: "API_KEY_MISSING"` |

---

## 🧰 技术栈

- **前端**：原生 HTML5 / CSS3 / JavaScript，零框架
  - Mermaid.js（Mermaid 预览）
  - html2canvas（PNG 导出）
  - 自研 Toast / Modal / 跨泳道 SVG overlay
- **后端**：Python 3 标准库 `http.server`
  - `requests` 调用模型 API
  - `python-dotenv`（可选）读取 `.env`

---

## 🚢 服务器部署

默认部署目录：`/opt/swimlane-tool`

```bash
cd /opt/swimlane-tool
pip3 install -r requirements.txt
cp .env.example .env
bash start_services.sh
```

systemd 守护：

```bash
sudo cp swimlane-tool.service /etc/systemd/system/swimlane-tool.service
sudo systemctl daemon-reload
sudo systemctl enable swimlane-tool.service
sudo systemctl restart swimlane-tool.service
sudo systemctl status swimlane-tool.service
```

---

## ❓ 常见问题

**Q：点「下一步：AI 格式化」报「API_KEY_MISSING」**
A：右上角齿轮 → 设置面板填写 API Key 即可。

**Q：泳道图很长，左侧第一列被吞了？**
A：已修复。如仍出现请清缓存刷新（Ctrl/Cmd + Shift + R）。

**Q：跨泳道连线没画出来？**
A：确认 Markdown 末尾有「跨泳道关系：」段，且引用的 ID 在上面步骤中存在。

**Q：导出图能带上跨泳道连线吗？**
A：能。Step 3「导出 PNG」会重新计算并绘制连线后再截图。

---

## 📄 许可证

MIT
