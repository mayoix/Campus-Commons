# Campus Commons

Campus Commons 是根据题目文件和项目题目文档实现的本地全栈 MVP。用户端用于发布 Mission、浏览/上传资源、维护本组织资源和确认使用结果；管理端用于批次调度、组织与资源管理、公平分配测试及隔离 Demo。

## 启动

需要 Python 3.10+，不需要安装第三方依赖：

```bash
PORT=8765 python3 server.py
```

打开 <http://127.0.0.1:8765/>。仓库包含当前的 `campus_commons.sqlite3` 演示数据，启动时只做增量迁移，不会用快照覆盖已有记录。资源、Mission、预约、决策、争议、信用事件、贡献事件和历史日志都会在每次写入后提交到数据库，重启服务后仍然存在。

默认数据库是项目根目录的 SQLite 文件；部署时可用 `CAMPUS_DB_PATH=/persistent/path/campus_commons.sqlite3` 指向持久磁盘。配置 `SUPABASE_DATABASE_URL` 并运行 `python3 scripts/migrate_sqlite_to_supabase.py --yes` 后，服务端会把业务读写切换到共享的 Supabase Postgres，所有客户端和管理端看到同一份数据；本地 SQLite 仍保留作为回滚和演示备份。启动前会生成时间戳备份。不要通过删除数据库来重置正式演示数据。

### Supabase 云端证据配置

项目支持从根目录 `.env` 读取 `SUPABASE_URL`、`SUPABASE_SECRET_KEY` 和可选的 `SUPABASE_EVIDENCE_BUCKET`。复制 `.env.example` 为 `.env`，填入 Supabase 项目 URL 与服务器端 Secret key 后重启即可；Secret key 只在后端使用，不能提交到仓库。完整的图文步骤与当前边界见 [SUPABASE_SETUP.md](SUPABASE_SETUP.md)。当前实现会把争议证据文件写入私有 Supabase Storage，同时保留本地 SQLite 业务数据；Mission、资源、组织、预约和历史表迁移到 Supabase Postgres 需要单独执行迁移并验证，不能仅凭配置变量宣称已经完成。

## 用户端

- 用户会话用本地演示组织切换模拟，不在请求参数中信任组织 ID。
- 资源池默认使用“状态排序”，另有时间早到晚、位置 A-Z、价格低到高。
- “组织档案”只管理当前组织自己的资源，可修改内容、可用时间和 `available / offline / maintenance` 状态。
- Mission 提交只保留标题、需求、地点和使用时间；截止时间由服务端按开始时间前 24 小时计算。
- 截止前只能调整可接受方案顺序；到期后由管理端批次执行，用户不会看到 batch、权重或决策过程。
- 用户只能看到当前组织相关活动，以及“Mission / 设备 / 场地已获批”等结果通知。
- Mission 详情可以发起争议；实际金额赔偿必须填写金额并上传证据。管理员审批通过后，违约组织自动扣信用并冻结，受害组织在确认处理完成后点击“已经解决”，系统才会解除冻结。
- 组织档案会显示本组织的历史记录；资源和 Mission 的创建、编辑、方案偏好、获批、候补、替换和完成状态都会留下不可变日志。
- 用户端每 5 秒读取数据库版本号；发现管理端或其他会话有新写入时，只重新读取数据库，不维护第二套前端数据源。
- 资源上传中的“平台无法匹配时的采购 / 租赁成本”用于估算外部替代开支；成本参考来源改为下拉选项（公开报价、校内费率、校内公开费率、校外市场报价、历史成交价、组织估算、其他），选择“其他”时可补充说明。

## 管理端

管理端不使用另一个网站地址，而是从原网站按 `Alt + Shift + A` 打开浮层。普通用户页面默认不会显示入口，管理端仍需要管理员密码。

首次运行会在项目根目录生成 `.admin-password`。当前本地实例密码由该文件提供；也可以用 `CAMPUS_ADMIN_PASSWORD` 覆盖。进入后可：

- 运行到期批次，检查时间/容量冲突、偏好顺序、公平分数、候补和预约；
- 管理组织信用、资源生命周期状态、Mission 使用/归还和争议；
- 在“冲突与争议”中查看受害方、违约方、赔偿金额、证据文件、扣分和冻结状态；确认违约或驳回后，系统把处理结果写入历史记录。
- 调整调度器与公平策略（仅管理端可见）；
- 运行隔离 Demo，演示资源发布、冲突、公平分配、候补、撤回释放、no-show 和替代方案确认。管理端提供“运行全部场景 / 冲突与公平 / 撤回释放 / 违约替换 / 偏好顺序”五个入口；每次报告用时间线、batch 时钟、fairness 输入与总分、状态节点和可验证断言解释底层逻辑。报告保存到 `demo_runs`，不污染正式业务数据。
- “持久化历史”标签查看所有资源、Mission、争议和平台变更；`decisions` 会保存当次 fairness 各组成分、提交的偏好顺序、策略快照、选中方案和解释。

默认调度器是手动模式；只有在管理端打开自动调度并保持服务进程运行时，后台线程才会按间隔处理到期 Mission。

## 关键业务 API

用户 API：`GET /api/bootstrap`、`GET /api/history`、`POST /api/resources`、`PATCH /api/resources/:id`、`POST /api/missions`、`POST /api/missions/:id/preferences`、`POST /api/missions/:id/{checkout,complete,withdraw}`、`POST /api/missions/:id/disputes`、`POST /api/disputes/:id/resolve`。`bootstrap.version` 是用户端和管理端共享的数据库变更令牌。

管理 API 需要独立的 HttpOnly `admin_sid`：`POST /api/admin/login`、`GET /api/admin/bootstrap`、`POST /api/admin/allocation/run`、`POST /api/admin/demo/run`、`PATCH /api/admin/config`。旧的用户端 batch 和单 Mission allocate 接口固定返回 403。管理端也每 5 秒按 `bootstrap.version` 同步一次。

## 文档未明确处的实现调整

- 采用本地 HttpOnly 会话和组织切换来模拟多组织用户；没有声称这是生产级身份认证。
- 资源预约用 `bookings` 表表达时间和容量，不把“已预约”改成资源生命周期状态。
- 提供方资源下架会释放预约、将 Mission 标记为待替换；候选替代方案需要用户重新确认。
- 题目没有规定真实支付、地图、对象存储或外部身份认证，因此本地版本用 SQLite、文本位置和争议记录完成可重复测试。
- 参考架构建议中的 PostgreSQL/FastAPI/React/WebSocket 需要额外运行时依赖和部署环境；当前交付先完成同等的数据边界：数据库是唯一事实源、历史事件不可变、API 写入后双端自动同步。没有强行引入缺少依赖的栈，以保证本地演示可直接启动。
