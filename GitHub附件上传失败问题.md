# GitHub Release 附件上传失败 — 排障与解决记录

> 首次记录：2026-09-21  
> 解决状态：处理中；网络根因与身份问题均已定位，发布完成后补充最终验证结果。

## 零、问题结论与可复用经验

这次失败由两个相互独立的问题叠加造成：

1. `uploads.github.com:443` 无法直连，但经本机 Clash 代理 `127.0.0.1:7897` 可以访问；
2. GitHub CLI 中原有的 OAuth token 已失效，需要重新执行 `gh auth login --web`。

因此，“浏览器能打开 GitHub”“`git push` 偶尔成功”或“`api.github.com` 可访问”都不能证明 Release 附件可以上传。发布前应分别验证身份状态，以及 `github.com`、`api.github.com`、`uploads.github.com` 三条链路。

本次采用的恢复顺序：

1. 检查附件大小和 SHA-256；
2. 确认代理端口可用；
3. 为当前 PowerShell 进程设置 `HTTPS_PROXY` / `HTTP_PROXY`；
4. 通过代理重新执行 `gh auth login --web`；
5. 创建空 Release；
6. 逐个上传大附件；
7. 查询 Release assets，并下载 `latest/download/update.json` 复核自动更新链路。

一次性设备授权码、OAuth token 和其他登录凭据不得写入本文档或提交到仓库。

## 一、要完成的目标

为仓库 `Song-wenpeng/PM-Stack` 创建 Release **v1.10.3** 并上传 3 个附件：

| 附件文件名 | 大小（字节） | 说明 |
|---|---|---|
| `PM-Stack.exe` | 136,496,797 | 主程序（SHA-256 见下） |
| `PM-Stack-v1.10.3.zip` | 143,408,868 | 首次分发压缩包 |
| `update.json` | 436 | 自动更新清单 |

- `PM-Stack.exe` 的 SHA-256：`1c61483646f790daeea3a4e89670cc8cf4f718f1529be2696b1c65fd7f5bb8c3`
- Release 标题：`PM Stack v1.10.3`
- Release 需标记为 **latest**（`--latest`），因为自动更新通道指向 `releases/latest/download/update.json`。
- **附件命名必须用连字符 `PM-Stack.exe`**（不是空格 `PM Stack.exe`），以匹配 `update.json` 里的绝对下载地址（见第四节）。

## 二、当前状态快照

- 代码已提交并推送到 GitHub `main` 分支（commit `eb20777`），版本号已改为 v1.10.3，EXE 已打包完成。
- **Release v1.10.3 尚未创建**：之前一次 `gh release create` 因附件上传失败，已回滚（删除了 tag）。刚刚复核确认：
  - `gh api .../git/ref/tags/v1.10.3` → **404**（tag 不存在）
  - `gh api .../releases/tags/v1.10.3` → **404**（release 不存在）
- 3 个待上传附件已暂存在本地：`C:/Users/QJH/AppData/Local/Temp/rel_upload/`
  - 注意：Temp 目录可能被系统清理，若文件已丢失需重新打包/重新整理。
- `update.json` 已在**本地**修正为绝对下载地址，但**尚未提交/推送**（远端 `eb20777` 仍是旧的相对地址）。

## 三、精确报错

执行 `gh release create v1.10.3 ... PM-Stack.exe ...` 上传附件时报错：

```
Post "https://uploads.github.com/repos/Song-wenpeng/PM-Stack/releases/<id>/assets?label=PM-Stack.exe&name=PM-Stack.exe":
dial tcp 140.82.121.4:443: connectex: A connection attempt failed because the connected
party did not properly respond after a period of time, or established connection failed
because connected host has failed to respond.
```

即：连不上 `uploads.github.com`（IP `140.82.121.4`）的 443 端口，TCP 握手超时。

## 四、网络连通性矩阵（直连 = 不走代理）

| 域名 | 直连 | 经 Clash 代理 (127.0.0.1:7897) |
|---|---|---|
| `api.github.com` | ✅ 正常 | ✅ 正常 |
| `github.com:443`（git push / clone） | ⚠️ 间歇性 RST 重置（`Connection was reset`），重试可成功 | ✅ 正常 |
| `uploads.github.com:443`（附件上传） | ❌ TCP 超时，连不上 | ✅ 正常（`curl -x http://127.0.0.1:7897 https://uploads.github.com` → HTTP 301，约 2.27s） |

环境：Windows 10，Git Bash（`E:\Git\bin\bash.exe`）。`gh` 在 `D:\PM Stack\tools-gh\gh.exe`，已登录账号 `Song-wenpeng`。Clash Verge 混合端口 `127.0.0.1:7897`。**git / gh 当前都没有配置代理**，默认直连，因此 `uploads.github.com` 不可达 → 附件上传必然失败。

## 五、根因判断

`uploads.github.com` 在直连下被网络阻断（TCP 超时），但经 Clash 代理可正常访问。`gh` 是 Go 程序，会读取 `HTTPS_PROXY` / `HTTP_PROXY` 环境变量；只要给它配上代理，附件上传即可走通。`api.github.com` 能直连不代表 `uploads.github.com` 也能——两者是不同的域名/网段，阻断策略不同，这正是之前误判的原因。

## 六、推荐解决方案

**方案 A（最简单，临时给单次命令加代理）** — 在 Git Bash 中执行：

```bash
HTTPS_PROXY=http://127.0.0.1:7897 HTTP_PROXY=http://127.0.0.1:7897 \
"D:/PM Stack/tools-gh/gh.exe" release create v1.10.3 \
  --repo Song-wenpeng/PM-Stack \
  --title "PM Stack v1.10.3" \
  --notes "新增：市场规划字段提取支持自动补抓五点描述与主副图（边抓边提取、解耦流水线、默认开启）；评论采集面板支持导出并一键发送到评论分析。" \
  --latest \
  "C:/Users/QJH/AppData/Local/Temp/rel_upload/PM-Stack.exe" \
  "C:/Users/QJH/AppData/Local/Temp/rel_upload/PM-Stack-v1.10.3.zip" \
  "C:/Users/QJH/AppData/Local/Temp/rel_upload/update.json"
```

**方案 B（大文件更稳：先建 Release，再分步上传）** — 130MB+ 的 EXE 走单条命令易超时，建议拆开：

```bash
# 1) 先创建空 Release（走 api.github.com，直连也行，但加代理更稳）
HTTPS_PROXY=http://127.0.0.1:7897 HTTP_PROXY=http://127.0.0.1:7897 \
"D:/PM Stack/tools-gh/gh.exe" release create v1.10.3 --repo Song-wenpeng/PM-Stack \
  --title "PM Stack v1.10.3" --notes "……" --latest

# 2) 再逐个上传附件（uploads.github.com，必须走代理）
HTTPS_PROXY=http://127.0.0.1:7897 HTTP_PROXY=http://127.0.0.1:7897 \
"D:/PM Stack/tools-gh/gh.exe" release upload v1.10.3 --repo Song-wenpeng/PM-Stack \
  "C:/Users/QJH/AppData/Local/Temp/rel_upload/PM-Stack.exe" \
  "C:/Users/QJH/AppData/Local/Temp/rel_upload/PM-Stack-v1.10.3.zip" \
  "C:/Users/QJH/AppData/Local/Temp/rel_upload/update.json"
```

**方案 C（一劳永逸：给 gh / git 永久配代理）**

```bash
# gh 永久走代理（gh 读环境变量，可设系统级 HTTPS_PROXY）
# git 针对 github.com 走代理，顺便解决 push 间歇性 RST：
git config --global http.https://github.com.proxy http://127.0.0.1:7897
```

## 七、重试前务必确认

1. **远端无残留 tag/release**：已确认 `v1.10.3` 的 tag 与 release 均为 404，可直接创建。若发现残留，先 `gh release delete v1.10.3 --cleanup-tag` 再重建。
2. **暂存附件是否还在**：`ls "C:/Users/QJH/AppData/Local/Temp/rel_upload/"`；丢失则需重新整理（EXE 来自 `D:/PM Stack/PM Stack/dist/PM Stack.exe`，需重命名为 `PM-Stack.exe`）。
3. **`update.json` 内容正确**：`url` 必须是绝对地址 `https://github.com/Song-wenpeng/PM-Stack/releases/download/v1.10.3/PM-Stack.exe`，且 `sha256` 与上传的 EXE 一致（`1c61483...`）。本地已修正但未推送——上传到 Release 附件即可生效（自动更新走的是 Release 附件里的 update.json），是否同时把它提交进仓库由用户决定。
4. **附件命名用连字符**：`PM-Stack.exe`，与 update.json 的 url 末尾一致，否则自动更新会 404。
5. **`--latest` 必须加**：自动更新通道指向 `releases/latest/download/update.json`。

## 八、自动更新链路（背景，供理解为何命名/latest 很关键）

- `update-channel.json` 里 `manifest_source = https://github.com/Song-wenpeng/PM-Stack/releases/latest/download/update.json`
- 程序读到该 manifest 后，`core/app_updater.py:_resolve_asset_source` 解析 `url`：
  - 绝对 https 地址 → 原样使用；
  - 相对地址 → 用 `urljoin(manifest_source, 相对地址)` 拼接。
- 因此：Release 附件里的 `update.json` 的 `url` 字段，必须能解析到一个真实存在、命名完全一致的 Release 附件（`PM-Stack.exe`）。命名不符或没标 latest，自动更新都会失败。
