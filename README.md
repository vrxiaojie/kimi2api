# Kimi2API

Kimi 网页版 Chat 转 OpenAI 兼容 API 的命令行代理工具。

基于对 Chat2API（TypeScript/Electron）项目中 Kimi 相关代码的逆向分析，用 Python 重新实现了核心逻辑：将 Kimi 内部 gRPC-Web 协议转换为标准 OpenAI `/v1/chat/completions` 接口，并提供一个带侧边栏的网页管理台来管理账号、curl 导入、模型映射和 API Key。

## 功能

- **OpenAI 兼容 API**：`/v1/chat/completions` 和 `/v1/models` 端点
- **流式输出（SSE）**：支持 `stream: true`
- **思考模式**：通过 `reasoning_effort` 参数启用，输出 `reasoning_content`
- **联网搜索**：通过 `web_search: true` 参数启用
- **函数调用**：通过 `tools` 参数 + 提示注入实现工具调用
- **API Key 管理**：创建、列表、吊销、删除 API Key
- **多模型映射**：自定义 OpenAI 模型名 → Kimi 模型名
- **网页管理台**：浏览器里直接管理账号、配置和密钥
- **curl 导入账号**：粘贴浏览器开发者工具复制的 curl 文本，自动提取 `auth` token 保存为账号

## 安装
clone本仓库

```bash
git clone https://github.com/vrxiaojie/kimi2api.git
```

安装python依赖
```bash
cd kimi2api
pip install -r requirements.txt
```

复制配置文件
```bash
cp config.example.json config.json
```

## 快速开始

### 1. 获取 Kimi Token 或 curl

打开 https://www.kimi.com 并登录，按 F12 打开开发者工具：

- **Application → Local Storage** 中查找 `access_token` 或 `refresh_token`
- 或从任意 API 请求的 `Authorization: Bearer xxx` 头中复制
- 或在 **网络（Network）** 中选中任意一个发往 kimi.com 的请求，右键 **复制为 curl**

Token 有两种类型：
- **JWT Token**（以 `eyJ` 开头）：直接使用
- **Refresh Token**：程序会自动尝试使用

### 2. 配置 Token

```bash
python run.py config set-token "你的Kimi_Token"
```

也可以直接打开网页管理台：

- 启动后访问 `http://127.0.0.1:8080/admin`
- 在左侧侧边栏切换到不同页面管理账号、模型映射和 API Key
- 在“账号”页里可以手动粘贴 token，也可以粘贴“复制为 curl”的完整文本
- 后端会从 curl 文本中提取 `auth=` 到第一个分号之间的内容，并立即校验后保存为账号
- 账号、模型映射和 API Key 会写入项目根目录的 `config.json`

### Docker 运行

#### 构建镜像

```bash
docker build -t kimi2api:latest .
```

#### 运行镜像
```bash
docker run -d \
  --name kimi2api \
  -p 8080:8080 \
  -v "$(pwd)/config.json:/data/config.json" \
  kimi2api:latest
```

### 3. 从账号页导入 curl（推荐）

1. 打开 `http://127.0.0.1:8080/admin`
2. 进入“账号”分页
3. 在 Kimi 页面按 F12，进入“网络（Network）”
4. 右键任意一个 kimi.com 请求，选择“复制为 curl”
5. 把完整 curl 文本粘贴到“从 curl 导入”表单
6. 保存后后端会自动提取 Cookie 中 `auth=...;` 的值，并创建账号

### 4. 创建 API Key

```bash
python run.py keys create --name "my-app"
```

### 5. 启动服务

```bash
python run.py serve --port 8080
```

启动后可以访问：

- `http://127.0.0.1:8080/admin`：网页管理台
- `http://127.0.0.1:8080/health`：健康检查

### 6. 调用 API

```bash
curl http://127.0.0.1:8080/v1/chat/completions \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer sk-你的API_Key" \
  -d '{
    "model": "kimi-k2.6",
    "messages": [{"role": "user", "content": "你好"}],
    "stream": true
  }'
```

## CLI 命令参考

### 配置管理

```bash
python run.py config show              # 查看当前配置
python run.py config set-token <token> # 设置 Kimi Token
python run.py config set-port <port>   # 设置服务端口
python run.py config set-host <host>   # 设置绑定地址
```

### API Key 管理

```bash
python run.py keys list                          # 列出所有 Key
python run.py keys create --name "my-app"        # 创建新 Key
python run.py keys revoke <prefix_or_name>       # 吊销 Key
python run.py keys enable <prefix_or_name>       # 启用 Key
python run.py keys delete <prefix_or_name>       # 删除 Key
```

### 模型映射

```bash
python run.py model list                                      # 列出映射
python run.py model add --openai gpt-4 --kimi kimi-k2.6       # 添加映射
python run.py model remove --openai gpt-4                     # 删除映射
```

### 启动服务

```bash
python run.py serve --host 0.0.0.0 --port 8080
```

## API 端点

| 端点 | 方法 | 说明 |
|------|------|------|
| `/` | GET | 服务信息 |
| `/health` | GET | 健康检查 |
| `/stats` | GET | 服务统计 |
| `/v1/models` | GET | 模型列表 |
| `/v1/chat/completions` | POST | 聊天补全 |
| `/v0/management/api-keys` | GET | 列出 API Key |
| `/v0/management/api-keys` | POST | 创建 API Key |
| `/v0/management/api-keys/<id>` | DELETE | 吊销 API Key |
| `/admin` | GET | 网页管理台 |

## 配置文件

- **主配置**：项目根目录的 `config.json`
- **模板文件**：`config.example.json`

## 技术细节

- **协议转换**：OpenAI JSON → Kimi gRPC-Web 帧格式（1 字节标志 + 4 字节大端长度 + JSON 载荷）
- **消息格式**：OpenAI messages 数组 → Kimi `role:content\n` 文本格式
- **URL 包装**：自动将用户消息中的 URL 包装为 `<url>` 标签（Kimi 专有格式）
- **流式解析**：解析 gRPC-Web 帧 → 提取 `block.think`（推理）/ `block.text`（回答）→ 输出 OpenAI SSE 块
- **多阶段检测**：支持 thinking → answer 阶段切换

## 依赖

- Python >= 3.9
- Flask >= 3.0
- requests >= 2.31

## 免责声明

本项目仅供学习与研究目的，使用者应遵守所在地的法律法规以及 Kimi 平台的服务条款。**严禁将本项目用于以下用途：**

- **商业用途**：不得将本项目或其衍生品用于任何商业盈利活动，包括但不限于以付费形式对外提供 API 转发服务。
- **批量注册与滥用**：不得利用本项目批量注册 Kimi 账号、自动化获取大量 Token，或以任何方式绕过 Kimi 平台的使用限制和频率控制。
- **违规分发**：不得将本项目打包为闭源产品进行二次分发，或移除本声明后重新发布。

使用本项目所产生的一切后果由使用者自行承担，项目作者不对因使用本项目而引发的任何直接或间接损失负责。**如不同意以上条款，请立即停止使用并删除本项目。**

## 致谢
- [Chat2API](https://github.com/xiaoY233/Chat2API) — 本项目参考了其 Kimi 相关部分的实现，在此表示感谢。

## 许可证
本项目基于 [GNU General Public License v3.0](LICENSE) 开源。