# BrandAgent 免费介绍页自动发布

## 范围

发布目标是已有的 `https://brandagent.pages.dev/`（Cloudflare Pages Direct Upload 项目 `brandagent`）。发布源是 `docs/site/brandagent/` 的六个静态文件，与 Next.js 写作应用和 Python 服务独立。

2026-10-28 用户批准 V4.2 方案 A：双载体同源重做。正文真值为 `src/components/landing/content.html`，样式真值为 `src/styles/landing.css`，颜色和字体以 `src/styles/consumer-tokens.css` 为准。生成脚本产出 Next 使用的 JSON 与静态介绍页；不可直接编辑生成文件。当前修改仅本地验收，公开发布仍需审阅。静态页没有 AI API、账号、数据库或支付功能。维护说明和验证脚本不在上传目录中。

## 免费边界

使用现有 Pages 免费项目和 GitHub 托管的标准 Linux Actions runner。该公开仓库的标准 runner 适用 GitHub 免费使用政策；若以后改为私有仓库或更换 runner，先重新核对 Actions 额度。不要开通付费 Cloudflare 服务或购买域名。

## 本地检查

```sh
python3 scripts/generate_pages_site.py
python3 scripts/generate_pages_site.py --check
python3 -m unittest discover -s tests/unit -p 'test_pages_site.py' -v
python3 scripts/verify_pages_site.py
node --check docs/site/brandagent/app.js
```

发布目录采用文件白名单，不接受 `.env`、`functions/`、`_worker.js`、符号链接或新增未审核文件。更改资源布局时，应同时修改白名单和相关边界测试。页面样式和交互还应经过浏览器检查。

## 一次性授权（需要用户确认）

1. 在 Cloudflare 创建专用 API Token：仅授予目标账号的 **Account → Cloudflare Pages → Edit** 权限。不授予 DNS、R2、Workers Scripts 或账号管理权限。该权限作用于所选账号的 Pages，并不能承诺只限制到单个项目。
2. 在 `kayon0209/brandagent` 的 Actions Secrets 中设置 `CLOUDFLARE_API_TOKEN`、`CLOUDFLARE_ACCOUNT_ID`。Token 不得进入源码、终端输出、截图或本地环境文件。
3. 审阅工作流后，设置仓库 Actions Variable `CLOUDFLARE_PAGES_DEPLOY_ENABLED=true`。未设置时仅检查，不部署。可以设为 `false` 暂停后续自动发布，不影响现有线上页面。

凭据名也记录在 `.env.example` 供发现，但仅用于 Actions，不能填写进应用本地环境文件。

## 触发与验收

- 相关 PR 仅做无密钥验证，使用 `pull_request`，不用 `pull_request_target`。
- 仅主分支的相关 push 或在主分支手动触发可以部署，且要求验证通过、启用开关为 true。
- Actions 均锁定完整提交 SHA，checkout 不保留 Git 凭据；只有发布步骤接收 Cloudflare Token。Wrangler 固定版本，使用带独立 `package.json` 的 `.github/pages-tooling/` 工作目录和 npm，避免向上查找应用依赖；该工具目录不在上传范围内。
- 发布前先验收预览，再确认生产发布。检查工作流、提交标识、原网址、图标和样式，以及目录、来源脚注和更新日志入口；核对 1440px 与 390px 排版。没有这些证据不能称发布已完成。
- GitHub 上的其他应用 CI 保持原样，不把 Pages 检查等同于完整应用测试。

## 回滚

紧急情况下先关闭 `CLOUDFLARE_PAGES_DEPLOY_ENABLED`。可以在 Cloudflare 控制台恢复先前成功的生产部署；随后在 GitHub 通过 revert 恢复对应页面源文件，使后续自动发布与线上保持一致。不要删除现有项目或更换已分享网址。

## 官方说明

- [Direct Upload 接持续集成](https://developers.cloudflare.com/pages/how-to/use-direct-upload-with-continuous-integration/)
- [Direct Upload 与原生 Git 集成的限制](https://developers.cloudflare.com/pages/get-started/direct-upload/)
- [GitHub Actions 计费](https://docs.github.com/en/billing/managing-billing-for-your-products/managing-billing-for-github-actions/about-billing-for-github-actions)
