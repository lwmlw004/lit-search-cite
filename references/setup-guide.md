# 安装指南

完整的一次性配置。完成后所有搜索和下载无需打开浏览器即可运行。

---

## 第一步 — 安装系统依赖

| 组件 | 用途 | 安装命令 (Windows) |
|-----------|-------------|-------------------|
| Node.js 18+ | ai4scholar MCP | `winget install OpenJS.NodeJS` |
| Python 3.10+ | CNKI Playwright, scansci-pdf | `winget install Python.Python.3.11` |
| Playwright + Chromium | CNKI、Google Scholar 浏览器引擎 | `pip install playwright && playwright install chromium` |
| uv | scansci-pdf MCP 运行时 | `pip install uv` 或 `winget install astral-sh.uv` |

**验证安装：**
```powershell
node --version          # v18+
python --version        # 3.10+
python -c "from playwright.sync_api import sync_playwright; print('OK')"
uvx --version
```

---

## 第二步 — 配置 MCP 服务器

编辑 `%USERPROFILE%\.claude\mcp.json`，加入：

```json
{
  "mcpServers": {
    "ai4scholar": {
      "command": "npx",
      "args": ["-y", "@ai4scholar/mcp-server"],
      "env": { "AI4SCHOLAR_API_KEY": "sk-user-你的密钥" }
    },
    "scansci-pdf": {
      "command": "uvx",
      "args": ["scansci-pdf"]
    }
  }
}
```

**重启 Claude Code** 后生效。复制粘贴模板：`references/mcp-template.json`。

---

## 第三步 — API 密钥

```powershell
.\scripts\setup.ps1
```

交互式配置向导。密钥保存到 `~/.lit-search-cite/config.json`。优先级：

| 密钥 | 用途 |
|-----|--------|
| `ai4scholar` | Google Scholar + S2（2.14 亿篇）— 最推荐 |
| `unpaywall_email` | OA PDF 发现 — 免费，任意邮箱 |
| `onescholar` | 在线期刊等级查询（JCR/CAS/IF） |
| `semantic_scholar` | S2 直接访问备选 |
| `wanfang` | 万方中文文献结构化检索 |

查看：`.\scripts\setup.ps1 -Show`

---

## 第四步 — Google Scholar Playwright（可选）

一次性浏览器配置，获取真实 Google Scholar 结果：
```powershell
python scripts/google-scholar.py --setup
# 浏览器打开 → 解决 CAPTCHA → 终端按 Enter
```
之后永久无头运行：
```powershell
python scripts/google-scholar.py --query "styrene smart polymer" --limit 10
python scripts/google-scholar.py --status
```
Cookie 约 7 天过期。刷新：`python scripts/google-scholar.py --login-only`

---

## 第五步 — 知网 WebVPN（中文文献）

一次性配置，内置 76 所中国高校 VPN 地址：
```powershell
python scripts/cnki-playwright.py --setup --school scau       # 缩写
python scripts/cnki-playwright.py --setup --school "清华大学"  # 中文名
```
之后无头搜索：
```powershell
python scripts/cnki-playwright.py --query "形状记忆 聚合物" --limit 20
```
Session 约 7 天过期。刷新：`python scripts/cnki-playwright.py --login-only --no-headless`

---

## 第六步 — 出版商 PDF 访问（付费论文）

对付费论文。告诉 Claude：
- "帮我配置 scansci-pdf 的 ScienceDirect Cookie"（通用）
- "帮我配置 scansci-pdf CARSI 登录"（国内高校）
- "帮我配置 scansci-pdf EZProxy 登录"（图书馆代理）

浏览器打开 → 登录一次 → Cookie 保存 → 永久无头下载。

---

## 第七步 — 验证

```powershell
.\scripts\check-deps.ps1
```

预期输出：`Status: READY — all critical components configured.`

---

## 最低可用配置

| 级别 | 需要配置 | 可用功能 |
|------|-------------|------------|
| 零配置 | 无 | PubMed、arXiv、OpenAlex、CrossRef、OA PDF |
| 推荐 | 第二步 + 第三步 | + Google Scholar、S2、期刊等级 |
| 完整英文 | + 第六步 | + 任意出版商付费 PDF |
| 完整中文 | + 第五步 | + 知网无头搜索 |
| 全部 | 全部 | + 万方结构化中文结果 |

---

## 配置文件

`~/.lit-search-cite/config.json`（仅本地，切勿分享）：

```json
{
  "vpn_url": "https://vpn.your-school.edu.cn",
  "cnki_vpn_base": "https://kns-cnki-net-s.vpn.your-school.edu.cn",
  "api_keys": {
    "ai4scholar": "sk-user-...",
    "onescholar": "sk_...",
    "semantic_scholar": "s2k-...",
    "unpaywall_email": "you@email.com",
    "wanfang": "",
    "elsevier": "",
    "springer": ""
  }
}
```

> **给 AI 的提示：** 不要通过 shell 工具运行 `setup.ps1`、`cnki-playwright.py --setup/--login-only` 或 scansci-pdf 登录工具 —— 它们需要交互式终端和可见浏览器。告诉用户确切的命令让他们自己运行。
