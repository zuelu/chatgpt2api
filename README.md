[中文](README.md) · [English](README.en.md) · [Tiếng Việt](README.vi.md)

<h1 align="center">ChatGPT2API</h1>

> 本仓库由 `zuelu` 维护，基于原项目 `basketikun/chatgpt2api` 的 `v1.8.0` 建立，并纳入当前生产环境使用的定制修复。上游来源和维护基线见 [UPSTREAM.md](UPSTREAM.md)。


<p align="center">ChatGPT2API 主要是对 ChatGPT 官网相关能力进行逆向整理与封装，提供面向 ChatGPT 图片生成、图片编辑、多图组图编辑场景的 OpenAI 兼容图片 API / 代理，并集成在线画图、号池管理、多种账号导入方式与 Docker 自托管部署能力。</p>

> [!WARNING]
> 免责声明：
>
> 本项目涉及对 ChatGPT 官网文本生成、图片生成与图片编辑等相关接口的逆向研究，仅供个人学习、技术研究与非商业性技术交流使用。
>
> - 严禁将本项目用于任何商业用途、盈利性使用、批量操作、自动化滥用或规模化调用。
> - 严禁将本项目用于破坏市场秩序、恶意竞争、套利倒卖、二次售卖相关服务，以及任何违反 OpenAI 服务条款或当地法律法规的行为。
> - 严禁将本项目用于生成、传播或协助生成违法、暴力、色情、未成年人相关内容，或用于诈骗、欺诈、骚扰等非法或不当用途。
> - 使用者应自行承担全部风险，包括但不限于账号被限制、临时封禁或永久封禁以及因违规使用等所导致的法律责任。
> - 使用本项目即视为你已充分理解并同意本免责声明全部内容；如因滥用、违规或违法使用造成任何后果，均由使用者自行承担。
> - 本项目基于对 ChatGPT 官网相关能力的逆向研究实现，存在账号受限、临时封禁或永久封禁的风险。请勿使用你自己的重要账号、常用账号或高价值账号进行测试。



## 官方 API、GIF 与 SVG（v1.12.1）

在 **号池管理 → 导入账户 → 手动添加官方 API** 中填写名称和 OpenAI API Key 后保存。画图页面选择 GIF/SVG 时，会自动使用 `api-gpt-image-2.6-sunburst`（细节优先）；也可手动选择 `api-gpt-image-2.6-flare`（速度优先）。这些模型调用官方 `https://api.openai.com/v1`，按 API 余额计费，与 ChatGPT 订阅和原 Codex 通道分开；原默认模型不变。账号列表不回显密钥。

手机和桌面画图页均可直接选择 **PNG / GIF / SVG**。选择 **GIF** 后可调整帧数和每帧时长，也可上传静态参考图制作动画；工作台使用 512×512 帧，历史记录与下载保留动画。也可通过 API 调用：

```json
{
  "model": "api-gpt-image-2.6-sunburst",
  "prompt": "一颗橙色小球在白色背景上轻轻弹跳并回到原位，无缝循环",
  "output_format": "gif",
  "frame_count": 9,
  "frame_duration_ms": 200,
  "size": "512x512",
  "quality": "low"
}
```

此 JSON 可发送至 `POST /v1/images/generations`；异步 `POST /api/image-tasks/generations` 另需 `client_task_id`。返回的 `b64_json` 解码后是 GIF，或使用返回的 `.gif` URL。帧数范围 2–16，每帧时长 20–2000 毫秒（上游按 10 毫秒取整），尺寸与总像素预算由官方校验。静态参考图可通过 `POST /v1/images/edits` 生成 GIF；GIF 不支持遮罩、流式输出或压缩参数。上传 GIF、动态 WebP、APNG 等多帧参考图时，会自动使用首帧 PNG 来生成海报或其他图片；网页显示处理提示和静态预览，API 响应及日志包含 `input_adjustments`。这是以首帧为参考重新生成，原文件不变；选择 GIF 输出仍会返回原生动画。无需用户手动提取帧或转换文件。

SVG 示例：

```json
{
  "model": "api-gpt-image-2.6-sunburst",
  "prompt": "简洁的橙色太阳和蓝色海浪矢量图标，使用可编辑的路径和形状",
  "output_format": "svg",
  "n": 1,
  "size": "1024x1024",
  "quality": "low"
}
```

SVG 通过官方 Images API 生成，保留 UTF-8 XML 原文件，支持图片库预览和 `.svg` 下载。SVG 每次请求要求 `n=1`，不支持编辑、流式输出、压缩参数，也不能直接作为位图编辑输入。部分 API 项目要求显式选择 SVG 编写模型：服务会在收到缺少 `svg.model` 的明确参数错误后补充 `gpt-6.1-sol` 再提交；可用环境变量 `OPENAI_SVG_AUTHOR_MODEL` 调整，或在同步 `/v1/images/generations` 请求中直接传入 `svg: {"model": "..."}`。SVG 按参考图和 SVG 编写模型分别计费。

GIF/SVG 即使省略 `model` 或传入 Codex 模型，服务端也会自动选用官方 API 模型与 API 号池。没有可用 API 账号时会提示导入密钥。号池按顺序轮询，账号额度、认证、限流及上游故障自动切换到下一个同通道账号重试；同次请求不重复失败账号，全部账号失败后返回具体错误。参数和内容政策错误不会跨账号重试，保留会话绑定不会跨账号迁移。

详见 [OpenAI 官方图片生成文档](https://developers.openai.com/api/docs/guides/image-generation)。SVG 与静态参考图生成 GIF 已使用官方 API 实测。

更新固定镜像标签至 `ghcr.io/zuelu/chatgpt2api-maintained:1.12.1`，或沿用 `latest`，执行 `docker compose pull app` 和 `docker compose up -d app` 即可；配置、账号和历史数据无需迁移。


## GPT Image 2.6（v1.10.0）

- 工作台、新图片任务和图片 API 省略 `model` 时，默认使用 `codex-gpt-image-2.6`，对应 `gpt-image-2.6-sunburst`。需要已导入的 **Codex 来源 Plus / Team / Pro 账号**。
- Sunburst 适合细节、布局和精确编辑；Flare 适合速度优先的生成。可在设置中修改 `codex_image_model_26_name`，或请求时直接指定 `gpt-image-2.6-sunburst` / `gpt-image-2.6-flare`；`gpt-image-2.6` 是同一 Codex 通道的本地别名。
- 保留显式选择 `gpt-image-2` / `gpt-image-2.5` 的网页通道，以及 `codex-gpt-image-2` / `codex-gpt-image-2.5` 的原有配置。仅有网页账号的部署，请显式使用原网页模型；新默认值不会自动切换到网页通道。
- 本版本接入现有 PNG 生成/编辑和 `auto` / `low` / `medium` / `high` / `xhigh` / `max` 质量档。官方新增的 complexity、标注编辑、SVG 和 GIF 尚未在本项目接入。模型特性见 [OpenAI 图片文档](https://developers.openai.com/api/docs/guides/image-generation)。

更新：

```bash
docker compose pull app
docker compose up -d app
```

以上命令适用于仓库默认的 `latest` 镜像；如固定了版本，请先将 compose 镜像标签改为 `ghcr.io/zuelu/chatgpt2api-maintained:1.10.0`。沿用原 `config.json` 和 `data` 挂载即可，无需重新导入账号或迁移历史。


## 快速开始

### Docker 运行

```bash
git clone git@github.com:zuelu/chatgpt2api.git
cd chatgpt2api
docker compose up -d
```

启动前请先在 `config.json` 中设置 `auth-key`，也可以在 `docker-compose.yml` 中通过 `CHATGPT2API_AUTH_KEY` 覆盖。

- Web 面板：`http://localhost:3000`
- API 地址：`http://localhost:3000/v1`
- 数据目录：`./data`

### WARP / FlareSolverr 稳定代理部署

如果图片链路经常遇到 Cloudflare 拦截，可以启用附带的 WARP + Privoxy + FlareSolverr 方案：

```bash
cp .env.example .env
docker compose -f docker-compose.warp.yml up -d --build
```

该 compose 会启动：

- `warp-proxy`：提供 WARP SOCKS5 出口。
- `privoxy`：把 WARP SOCKS5 转成 HTTP 代理。
- `flaresolverr`：刷新 Cloudflare clearance。
- `init-config`：幂等写入 `proxy_runtime` 默认配置。
- `app`：启动 ChatGPT2API 主服务。

默认只让上游 OpenAI / ChatGPT 请求走稳定代理，账号邮箱、CPA 等辅助链路不会被强制接管。账号自身配置的代理优先级最高，其次是稳定代理运行时，再其次是显式代理和旧版全局代理。

可在 `.env` 中调整端口和代理运行时参数，也可在后台设置页的「稳定代理运行时」面板手动保存、测试代理和测试 clearance。

### 本地开发

启动后端：

```bash
git clone git@github.com:zuelu/chatgpt2api.git
cd chatgpt2api
uv sync
uv run main.py
```

启动前端：

```bash
cd chatgpt2api/web
bun install
bun run dev
```

后续更新新版本：

```bash
docker compose pull
docker compose up -d

```

### 存储后端配置

支持通过环境变量 `STORAGE_BACKEND` 切换存储方式：

- `json` - 本地 JSON 文件（默认）
- `sqlite` - 本地 SQLite 数据库
- `postgres` - 外部 PostgreSQL（需配置 `DATABASE_URL`）
- `git` - Git 私有仓库（需配置 `GIT_REPO_URL` 和 `GIT_TOKEN`）

示例：使用 PostgreSQL

```yaml
environment:
  - STORAGE_BACKEND=postgres
  - DATABASE_URL=postgresql://user:password@host:5432/dbname
```

## 功能

### API 兼容能力

- 兼容 `POST /v1/images/generations` 图片生成接口
- 兼容 `POST /v1/images/edits` 图片编辑接口
- 兼容面向图片场景的 `POST /v1/chat/completions`
- 兼容面向图片场景的 `POST /v1/responses`
- `GET /v1/models` 返回账号支持的 `codex-gpt-image-2.6`、`gpt-image-2.6`、`gpt-image-2.6-sunburst`、`gpt-image-2.6-flare`、`gpt-image-2`、`gpt-image-2.5`、`codex-gpt-image-2`、`codex-gpt-image-2.5`、`auto`、`gpt-5`、`gpt-5-1`、`gpt-5-2`、`gpt-5-3`、`gpt-5-3-mini`、
  `gpt-5-mini`
- 支持通过 `n` 返回多张生成结果
- 支持生成可编辑 PPT 文件
- 支持生成可编辑 PSD 文件
- 支持 Codex 中的画图接口逆向，仅 `Plus` / `Team` / `Pro` 订阅可用，模型别名为 `codex-gpt-image-2`，如有需要可自行在其他场景映射回
  `gpt-image-2`，用于和官网画图区分；也就意味着同一账号会同时有官网和 Codex 两份生图额度
- 支持 ChatGPT Images 2.5：官网画图链路的别名为 `gpt-image-2.5`（上游模型名可在设置页单独配置，留空跟随旧版设置）；
  Codex 链路的别名为 `codex-gpt-image-2.5`（同样支持 `plus` / `team` / `pro` 前缀），工具模型默认 `gpt-image-2.5-sunburst`、
  可在设置页切换为 `gpt-image-2.5-flare`，质量档额外支持 `xhigh` / `max`
- Web 工作台默认选择 `codex-gpt-image-2.6`；需要导入 Codex 来源的 `Plus` / `Team` / `Pro` 账号，并具有 `gpt-6.1-sol` 和图片工具的使用权限。账号池未提供该模型时，工作台按当前可用模型列表选择。此默认值不会改写历史会话或 API 显式指定的模型。

### 在线画图功能

- 内置在线画图工作台，支持生成、图片编辑与多图组图编辑
- 支持 `codex-gpt-image-2.6`、`gpt-image-2.6-sunburst`、`gpt-image-2.6-flare`、`gpt-image-2`、`gpt-image-2.5`、`codex-gpt-image-2`、`codex-gpt-image-2.5`、`auto`、`gpt-5`、`gpt-5-1`、`gpt-5-2`、`gpt-5-3`、`gpt-5-3-mini`、`gpt-5-mini` 模型选择
- 编辑模式支持参考图上传
- 前端支持多图生成交互
- 本地保存图片会话历史，支持回看、删除和清空
- 支持服务端缓存图片URL
- 图片生成进度追踪，超时后可继续等待
- 图片懒加载与滚动位置记忆，优化大量图片场景性能

### 号池管理功能

- 自动刷新账号邮箱、类型、额度和恢复时间（异步进度追踪）
- 轮询可用账号执行图片生成与图片编辑
- 遇到 Token 失效类错误时自动剔除无效 Token
- 定时检查限流账号并自动刷新
- 支持密码重新登录恢复异常账号，刷新后可自动重登
- 支持网页端配置全局 HTTP / HTTPS / SOCKS5 / SOCKS5H 代理
- 支持 WARP / FlareSolverr 稳定代理运行时
- 支持搜索、筛选、批量刷新、导出、手动编辑和清理账号
- 支持四种导入方式：本地 CPA JSON 文件导入、远程 CPA 服务器导入、`sub2api` 服务器导入、`access_token` 导入
- 支持在设置页配置 `sub2api` 服务器，筛选并批量导入其中的 OpenAI OAuth 账号

### 实验性 / 规划中

- 详细状态说明见：[功能清单](./docs/feature-status.en.md)

## 效果展示

<table width="100%">
  <tr>
    <td width="50%"><img src="https://i.ibb.co/Jj8nfwwP/image.png" alt="image" border="0"></td>
    <td width="50%"><img src="https://i.ibb.co/pqf235v/image-edit.png" alt="image edit" border="0"></td>
  </tr>
  <tr>
    <td width="50%"><img src="https://i.ibb.co/tPcqtVfd/chery-studio.png" alt="chery studio" border="0"></td>
    <td width="50%"><img src="https://i.ibb.co/PsT9YHBV/account-pool.png" alt="account pool" border="0"></td>
  </tr>
  <tr>
    <td width="50%"><img src="https://i.ibb.co/rRWLG08q/new-api.png" alt="new api" border="0"></td>
  </tr>
</table>

## API

所有 AI 接口都需要请求头：

```http
Authorization: Bearer <auth-key>
```

<details>
<summary><code>GET /v1/models</code></summary>
<br>

返回当前暴露的图片模型列表。

```bash
curl http://localhost:8000/v1/models \
  -H "Authorization: Bearer <auth-key>"
```

<details>
<summary>说明</summary>
<br>

| 字段   | 说明                                                                                                         |
|:-----|:-----------------------------------------------------------------------------------------------------------|
| 返回模型 | `codex-gpt-image-2.6`、`gpt-image-2.6-sunburst`、`gpt-image-2.6-flare`、`gpt-image-2`、`gpt-image-2.5`、`codex-gpt-image-2`、`codex-gpt-image-2.5`、`auto`、`gpt-5`、`gpt-5-1`、`gpt-5-2`、`gpt-5-3`、`gpt-5-3-mini`、`gpt-5-mini` |
| 接入场景 | 可接入 Cherry Studio、New API 等上游或客户端                                                                          |

<br>
</details>
</details>

<details>
<summary><code>POST /v1/images/generations</code></summary>
<br>

OpenAI 兼容图片生成接口，用于文生图。

```bash
curl http://localhost:8000/v1/images/generations \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer <auth-key>" \
  -d '{
    "model": "codex-gpt-image-2.6",
    "prompt": "一只漂浮在太空里的猫",
    "n": 1,
    "response_format": "b64_json"
  }'
```

<details>
<summary>字段说明</summary>
<br>

| 字段                | 说明                                                 |
|:------------------|:---------------------------------------------------|
| `model`           | 图片模型，省略时默认 `codex-gpt-image-2.6`；当前可用值以 `/v1/models` 返回结果为准，`gpt-image-2` 仍可显式选择 |
| `prompt`          | 图片生成提示词                                            |
| `n`               | 生成数量，当前后端限制为 `1-4`                                 |
| `response_format` | 当前请求模型中包含该字段，默认值为 `b64_json`                       |

<br>
</details>
</details>

<details>
<summary><code>POST /v1/images/edits</code></summary>
<br>

OpenAI 兼容图片编辑接口，可上传图片文件，也可按官方 JSON 格式传入图片链接并生成编辑结果。

```bash
curl http://localhost:8000/v1/images/edits \
  -H "Authorization: Bearer <auth-key>" \
  -F "model=codex-gpt-image-2.6" \
  -F "prompt=把这张图改成赛博朋克夜景风格" \
  -F "n=1" \
  -F "image=@./input.png"
```

也可以直接传图片 URL：

```bash
curl http://localhost:8000/v1/images/edits \
  -H "Authorization: Bearer <auth-key>" \
  -H "Content-Type: application/json" \
  -d '{
    "model": "codex-gpt-image-2.6",
    "prompt": "把这张图改成赛博朋克夜景风格",
    "images": [
      {"image_url": "https://example.com/input.png"}
    ]
  }'
```

<details>
<summary>字段说明</summary>
<br>

| 字段          | 说明                                            |
|:------------|:----------------------------------------------|
| `model`     | 图片模型，省略时默认 `codex-gpt-image-2.6`，`gpt-image-2` 仍可显式选择 |
| `prompt`    | 图片编辑提示词                                       |
| `n`         | 生成数量，当前后端限制为 `1-4`                            |
| `image`     | 需要编辑的图片文件，使用 multipart/form-data 上传           |
| `images`    | JSON 图片引用数组，支持 `{"image_url": "https://..."}` |
| `image_url` | 表单模式下也可直接传图片链接，支持重复字段传多张图                     |

<br>
</details>
</details>

<details>
<summary><code>POST /v1/chat/completions</code></summary>
<br>

面向文本、网页搜索与图片场景的 Chat Completions 兼容接口，不是完整通用聊天代理。

```bash
curl http://localhost:8000/v1/chat/completions \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer <auth-key>" \
  -d '{
    "model": "gpt-image-2",
    "messages": [
      {
        "role": "user",
        "content": "生成一张雨夜东京街头的赛博朋克猫"
      }
    ],
    "n": 1
  }'
```

<details>
<summary>字段说明</summary>
<br>

| 字段                   | 说明                                                                           |
|:---------------------|:-----------------------------------------------------------------------------|
| `model`              | 文本、搜索或图片模型；搜索模型会触发网页搜索兼容逻辑                                                   |
| `messages`           | 消息数组，支持文本、搜索和图片请求内容                                                          |
| `n`                  | 图片生成数量，按当前实现解析为图片数量                                                          |
| `stream`             | 文本、搜索和图片场景均支持，仍在测试                                                           |
| `tools`              | 文本场景支持 `web_search` / `web_search_preview` / `web_search_preview_2025_03_11` |
| `web_search_options` | 传入时会触发网页搜索兼容逻辑                                                               |

<br>
</details>
</details>

<details>
<summary><code>POST /v1/responses</code></summary>
<br>

面向文本、网页搜索和图片生成工具调用的 Responses API 兼容接口，不是完整通用 Responses API 代理。

```bash
curl http://localhost:8000/v1/responses \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer <auth-key>" \
  -d '{
    "model": "gpt-5",
    "input": "生成一张未来感城市天际线图片",
    "tools": [
      {
        "type": "image_generation"
      }
    ]
  }'
```

<details>
<summary>字段说明</summary>
<br>

| 字段       | 说明                                                                                      |
|:---------|:----------------------------------------------------------------------------------------|
| `model`  | 响应中会回显该模型字段，搜索和图片生成会走对应兼容逻辑                                                             |
| `input`  | 输入内容；搜索使用最后一条用户文本，图片生成需能解析出提示词                                                          |
| `tools`  | 支持 `image_generation`、`web_search`、`web_search_preview`、`web_search_preview_2025_03_11` |
| `stream` | 已实现，但仍在测试                                                                               |

<br>
</details>
</details>


## 生图报错排查

升级到 1.9.3 或更新版本后，可在后台日志详情查看上游返回的完整错误原因（展示内容有长度限制）。

- `Unusual activity has been detected from your device`：上游拒绝了当前设备或账号请求。先停止重复提交，并在 ChatGPT 官网确认账号能否正常生图、完成官方要求的验证；升级服务代码无法解除此限制。
- `upstream_verification_required`（HTTP 503，1.9.4 起）：上游要求交互式浏览器验证，但当前纯 HTTP 网页通道无法提供验证结果。该错误发生在生成提交前，参考图也不会上传。官网可以生图或重新 OAuth 登录，不代表服务器请求的这次验证已完成。本项目目前没有可用的交互式验证流程；该版本仅修复错误处理，尚未恢复此情况下的原网页通道。
- `Model not found`：核对设置中的上游模型名称与该账号当前返回的模型 `slug`。显示名称、API 模型名和网页模型 `slug` 可能不同，不要仅根据显示名称填写。
- 原版 `/backend-api/f/conversation` 的 404 会兼容重试 `/backend-api/conversation`，应以最终请求的错误为准。

Docker 用户可将 compose 中的镜像设为 `ghcr.io/zuelu/chatgpt2api-maintained:1.10.0`，或继续跟随 `latest`，随后执行 `docker compose pull` 和 `docker compose up -d`。升级前备份配置和数据目录；已有失败任务不会因升级自动重新生成。

1.9.5 修复了 Codex 生图仍使用已退役主模型 `gpt-5.5` 的兼容问题，改用 `gpt-6.1-sol`。该版本的工作台默认模型为 `codex-gpt-image-2.5`；通过 API 使用该通道时，请显式传入同名模型。原网页通道的交互验证限制仍然存在。

## Contributors

感谢所有为本项目做出贡献的开发者：

<a href="https://github.com/zuelu/chatgpt2api/graphs/contributors">
  <img alt="Contributors" src="https://contrib.rocks/image?repo=zuelu/chatgpt2api" />
</a>

## Star History

[![Star History Chart](https://api.star-history.com/chart?repos=zuelu/chatgpt2api&type=date&legend=top-left)](https://www.star-history.com/?repos=zuelu%2Fchatgpt2api&type=date&legend=top-left)
