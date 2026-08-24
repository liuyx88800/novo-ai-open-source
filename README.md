# Novo AI Open Source

Novo AI 的开源接入版本，保留 2026-08-22 首次接入 VOZEB PRO 统一创作 Agent 与短剧工作流时的公开部分。

## 包含内容

- `apps/landing`：Novo AI 产品首页
- `apps/studio`：VOZEB PRO Agent、短剧、作品与分享页面的 Vite 接入版本
- `integrations/fastapi/vz_routes.py`：对接现有 FastAPI 宿主服务的兼容路由

## 不包含内容

Novo AI 自研画布的源码、运行时、构建产物、服务端编排逻辑与生产配置不在本仓库中。完整边界见 [OPEN_SOURCE_BOUNDARY.md](OPEN_SOURCE_BOUNDARY.md)。因此，本仓库不是线上商业服务的完整镜像，接入适配层需要由部署者实现对应宿主 API。

## 本地构建

需要 Node.js 20 或更高版本。

```bash
npm --prefix apps/landing ci
npm --prefix apps/studio ci
npm run build
```

开发模式：

```bash
npm --prefix apps/landing run dev
npm --prefix apps/studio run dev
```

## 配置与安全

复制 `.env.example` 为 `.env` 后再填写自己的服务端配置。真实密钥不能写入前端、提交记录、Issue 或日志。仓库不包含任何生产账号、媒体、任务记录或供应商密钥。

提交前可执行：

```powershell
./scripts/security-scan.ps1
```

## 上游与致谢

Agent 与短剧工作流基于 [VOZEB PRO](https://github.com/csyqlz/VOZEB-PRO)，原作者为 [XOZEM (@csyqlz)](https://github.com/csyqlz)。首页底部保留作者头像、作者名与上游项目入口。

## 许可证

本仓库按 GNU Affero General Public License v3.0 only 发布。使用、修改、分发或通过网络提供修改版本时，请遵守 AGPL-3.0 的源代码提供与声明保留义务。第三方组件的许可证见 `THIRD_PARTY_LICENSES.md`。
