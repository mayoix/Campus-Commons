# Supabase 设置说明

你不需要为了打开本地演示而配置 Supabase。没有 `.env` 时，系统继续使用项目里的 `campus_commons.sqlite3`，演示数据和历史记录仍然保留。

如果要让不同电脑共享同一套 Mission、资源、组织、预约和历史记录，按下面步骤设置。密钥只放在本机的 `.env`，不要发到聊天、不要放到浏览器代码，也不要提交到 GitHub。

## 1. 创建项目

1. 打开 [Supabase](https://supabase.com/) 并登录。
2. 点击 **New project**，创建一个项目并设置数据库密码。
3. 创建完成后，进入项目的 **Settings → API Keys**。
4. 复制 **Project URL** 和服务器端使用的 **Secret key**（通常以 `sb_secret_` 开头）。如果暂时只看到旧版 `service_role`，本地代码也兼容它。

Supabase 官方说明：Secret key 只能用于受控的后端，不能放在浏览器或源代码中，见 [API keys](https://supabase.com/docs/guides/getting-started/api-keys)。

## 2. 在项目目录创建 `.env`

在 Finder 打开项目目录 `/Users/zhuyining/Desktop/fintech pro2`，新建一个纯文本文件，文件名必须是 `.env`（开头有一个点）。内容如下，把两处占位符替换为你刚刚复制的值：

```dotenv
SUPABASE_URL=https://你的项目编号.supabase.co
SUPABASE_SECRET_KEY=sb_secret_你的服务器密钥
SUPABASE_EVIDENCE_BUCKET=campus-evidence
SUPABASE_DATABASE_URL=postgresql://postgres.你的项目编号:你的数据库密码@aws-0-ap-northeast-2.pooler.supabase.com:5432/postgres
```

如果 Finder 不方便创建以点开头的文件，可以在“终端”执行：

```bash
cd "/Users/zhuyining/Desktop/fintech pro2"
cp .env.example .env
open -e .env
```

在打开的文本编辑器中替换占位符，保存后关闭。

## 3. 先复制业务数据库

在终端执行下面两条命令。迁移是可重复的，会保留本地 SQLite 和当前演示数据，不会删除 Supabase 中已有行：

```bash
cd "/Users/zhuyining/Desktop/fintech pro2"
python3 -m pip install --user "psycopg[binary]"
python3 scripts/migrate_sqlite_to_supabase.py --yes
```

成功后应看到 `Supabase 数据迁移完成（本地 SQLite 保留）`，以及各业务表的条数。若失败，把终端最后一行错误发给我，不要发送 `.env` 内容。

## 4. 重启本地服务

关闭当前运行服务的终端窗口，再打开终端执行：

```bash
cd "/Users/zhuyining/Desktop/fintech pro2"
PORT=8765 python3 server.py
```

然后打开 <http://127.0.0.1:8765/>。上传一条带金额的争议证据后，服务会自动创建私有的 `campus-evidence` bucket，把文件上传到 Supabase Storage；管理端详情仍通过登录后的后端接口预览和下载，不会把 Secret key 发送给用户端。Supabase 的 Storage bucket 和文件模型见 [Storage quickstart](https://supabase.com/docs/guides/storage/quickstart)。

服务器检测到 `SUPABASE_DATABASE_URL` 后，业务读写默认改用 Supabase Postgres；若要临时回退本地演示库，可在启动命令前加 `CAMPUS_DB_BACKEND=sqlite`。证据文件继续使用同一 Supabase Storage。

## 当前版本的边界

- 本次配置会把**争议证据文件**真实保存到 Supabase Storage，SQLite 只保存文件名、类型、大小和云端对象路径。
- `scripts/migrate_sqlite_to_supabase.py` 负责一次性复制现有业务数据；之后每台运行此仓库的服务都连接同一个 `SUPABASE_DATABASE_URL`，用户端与管理端读取同一事实源。Supabase 的连接串在 **Connect** 对话框中，连接方式和连接池说明见 [Connect to your database](https://supabase.com/docs/guides/database/connecting-to-postgres)。
- 迁移脚本采用逐表 upsert，重复执行不会删除本地数据；如果云端已经有同 ID 记录，会用本地记录更新该行。
- 不要直接删除 SQLite 文件来“清空”数据；当前仓库保留演示数据和历史记录。

设置完成后，你只需要回复“已设置”，不要发送 URL 后面的密钥内容。我再继续做连接测试和业务数据迁移验证。
