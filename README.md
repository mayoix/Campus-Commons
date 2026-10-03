# Campus Commons

Campus Commons 是根据题目文件和项目题目文档实现的本地全栈 MVP。用户端用于发布 Mission、浏览/上传资源、维护本组织资源和确认使用结果；管理端用于批次调度、组织与资源管理、公平分配测试及隔离 Demo。

## 启动

需要 Python 3.10+，不需要安装第三方依赖：

```bash
PORT=8765 python3 server.py
```

打开 <http://127.0.0.1:8765/>。仓库包含当前的 `campus_commons.sqlite3` 演示数据，启动时会做增量迁移；运行中的新增记录会继续写入本地数据库。启动前会生成时间戳备份。不要通过删除数据库来重置正式演示数据。

## 用户端

- 用户会话用本地演示组织切换模拟，不在请求参数中信任组织 ID。
- 资源池默认使用“状态排序”，另有时间早到晚、位置 A-Z、价格低到高。
- “组织档案”只管理当前组织自己的资源，可修改内容、可用时间和 `available / offline / maintenance` 状态。
- Mission 提交只保留标题、需求、地点和使用时间；截止时间由服务端按开始时间前 24 小时计算。
- 截止前只能调整可接受方案顺序；到期后由管理端批次执行，用户不会看到 batch、权重或决策过程。
- 用户只能看到当前组织相关活动，以及“Mission / 设备 / 场地已获批”等结果通知。

## 管理端

管理端不使用另一个网站地址，而是从原网站按 `Alt + Shift + A` 打开浮层。普通用户页面默认不会显示入口，管理端仍需要管理员密码。

首次运行会在项目根目录生成 `.admin-password`。当前本地实例密码由该文件提供；也可以用 `CAMPUS_ADMIN_PASSWORD` 覆盖。进入后可：

- 运行到期批次，检查时间/容量冲突、偏好顺序、公平分数、候补和预约；
- 管理组织信用、资源生命周期状态、Mission 使用/归还和争议；
- 调整调度器与公平策略（仅管理端可见）；
- 运行隔离 Demo，演示资源发布、冲突、公平分配、候补、no-show 和替代方案确认。Demo 报告保存到 `demo_runs`，不污染正式业务数据。

默认调度器是手动模式；只有在管理端打开自动调度并保持服务进程运行时，后台线程才会按间隔处理到期 Mission。

## 关键业务 API

用户 API：`GET /api/bootstrap`、`POST /api/resources`、`PATCH /api/resources/:id`、`POST /api/missions`、`POST /api/missions/:id/preferences`、`POST /api/missions/:id/{checkout,complete,withdraw}`、`POST /api/missions/:id/disputes`。

管理 API 需要独立的 HttpOnly `admin_sid`：`POST /api/admin/login`、`GET /api/admin/bootstrap`、`POST /api/admin/allocation/run`、`POST /api/admin/demo/run`、`PATCH /api/admin/config`。旧的用户端 batch 和单 Mission allocate 接口固定返回 403。

## 文档未明确处的实现调整

- 采用本地 HttpOnly 会话和组织切换来模拟多组织用户；没有声称这是生产级身份认证。
- 资源预约用 `bookings` 表表达时间和容量，不把“已预约”改成资源生命周期状态。
- 提供方资源下架会释放预约、将 Mission 标记为待替换；候选替代方案需要用户重新确认。
- 题目没有规定真实支付、地图、对象存储或外部身份认证，因此本地版本用 SQLite、文本位置和争议记录完成可重复测试。
