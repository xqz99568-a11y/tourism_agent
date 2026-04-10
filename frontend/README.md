# Tourism Agent Frontend

这是本仓库的第二版答辩展示前端，位于 `frontend/`，采用 Next.js App Router、TypeScript、Tailwind CSS 和 shadcn/ui 风格组织，继续复用现有单页聊天架构，并对演示体验做了成品化收口。

默认组件路径固定为 `@/components/ui/*`，这样可以直接兼容本次接入的现成素材引用：

- `@/components/ui/textarea`
- `@/components/ui/ai-input-with-loading`

## 1. 安装前端依赖

在仓库根目录执行：

```powershell
cd frontend
npm install
```

## 2. 启动 Python 后端

回到仓库根目录，启动 FastAPI Web 服务：

```powershell
python -m app.main --mode web --host 127.0.0.1 --port 8000
```

默认会提供以下接口：

- `GET /health`
- `POST /chat`
- `POST /session/reset`

## 3. 启动 Next.js 前端

在 `frontend/` 目录执行：

```powershell
npm run dev
```

默认访问地址：

- `http://localhost:3000`

## 4. 环境变量配置

复制环境变量示例后按需修改：

```powershell
cd frontend
Copy-Item .env.example .env.local
```

默认内容如下：

```env
NEXT_PUBLIC_API_BASE_URL=http://127.0.0.1:8000
```

如果你的 Python 后端不在本机 `8000` 端口，请把它改成实际地址。

## 5. 第二版前端包含的能力

- 单页聊天式工作台，适合答辩展示
- 浏览器 `localStorage` 持久化 `session_id`
- 空状态欢迎区和可点击示例问题
- 真实后端请求联动，不使用伪思考主流程
- loading 占位消息、错误卡片、健康检查提示
- `need_info` 场景单独渲染为提示卡
- 对最终方案和 follow-up 结果做基础结构化展示
- 提供“查看原始 JSON”折叠区，方便演示接口返回
- 支持新会话、重置会话、继续追问

## 6. 常见启动失败原因

- Python 后端没有启动，前端会提示无法连接后端服务
- 当前 Python 环境没装 `fastapi`、`uvicorn` 或 `pydantic`
- `NEXT_PUBLIC_API_BASE_URL` 配置错误，前端请求到了错误地址
- Node 版本过旧，导致 Next.js 或依赖安装失败

## 7. 演示建议脚本

建议按下面顺序演示：

1. 启动后端：`python -m app.main --mode web --host 127.0.0.1 --port 8000`
2. 启动前端：`cd frontend && npm run dev`
3. 打开 `http://localhost:3000`
4. 先输入模糊需求，例如“我想过几天去桂林玩”
5. 展示系统触发补充信息提问
6. 继续补充天数、人数、预算，拿到完整方案
7. 再追问“有什么需要注意的”“下雨怎么办”“美食推荐”等 follow-up 能力
8. 点击“重置会话”演示上下文清空
9. 点击“新会话”演示切换到新的 `web-xxxxxxxx` 会话 ID

## 8. 说明

这版前端的目标是“第二版答辩展示前端”，重点在于稳定、清楚、像完成品，而不是增加复杂系统能力。
