# GitHub Release 附件上传失败 — 排障与解决记录

> 首次记录：2026-09-21  
> 解决状态：已解决；v1.10.3 Release、3 个附件和 latest 自动更新清单均已验证。

## 零、问题结论与可复用经验

这次失败由两个相互独立的问题叠加造成：

1. 本机 DNS 将 `uploads.github.com` 错误解析为普通 `github.com` 使用的 `140.82.121.4`。代理也沿用了错误解析；访问根路径得到 301 并不代表上传 API 可用，实际 POST 会被重定向到无效的 `github.com/repos/...` 后返回 404；
2. GitHub CLI 中原有的 OAuth token 已失效，需要重新执行 `gh auth login --web`。

因此，“浏览器能打开 GitHub”“`git push` 偶尔成功”或“`api.github.com` 可访问”都不能证明 Release 附件可以上传。发布前应分别验证身份状态，以及 `github.com`、`api.github.com`、`uploads.github.com` 三条链路。

本次采用的恢复顺序：

1. 检查附件大小和 SHA-256；
2. 通过代理重新执行 `gh auth login --web`，恢复 CLI 身份；
3. 创建空 Release，并使用远端完整 40 位提交哈希作为 `--target`；
4. 通过公共 DNS-over-HTTPS 查询 `uploads.github.com` 的正确 CNAME/IP；
5. 使用 `curl --resolve uploads.github.com:443:<正确IP>` 保留域名和 TLS SNI，逐个上传附件；
6. 查询 Release assets，并下载 `latest/download/update.json` 复核自动更新链路。

一次性设备授权码、OAuth token 和其他登录凭据不得写入本文档或提交到仓库。

### 最终结果

- Release：https://github.com/Song-wenpeng/PM-Stack/releases/tag/v1.10.3
- 目标提交：`390dbff2f2a9255c52bdc19f442c2c96ba4169b0`
- `update.json`：436 字节，已上传；
- `PM-Stack.exe`：136,496,797 字节，GitHub 返回 SHA-256 `1c61483646f790daeea3a4e89670cc8cf4f718f1529be2696b1c65fd7f5bb8c3`；
- `PM-Stack-v1.10.3.zip`：143,408,868 字节，上传前确认仅包含主程序、更新器和 `update-channel.json`；
- `releases/latest/download/update.json` 已返回 v1.10.3 正确清单；EXE 与 ZIP 下载地址均返回 HTTP 200。

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

## 二、解决前状态快照（历史）

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
| `uploads.github.com:443`（附件上传） | ❌ 被错误解析到 `140.82.121.4`，TCP 超时 | ❌ 根路径返回 301，但上传 POST 也被错误重定向，不能视为正常 |

环境：Windows 10，Git Bash（`E:\Git\bin\bash.exe`）。`gh` 在 `D:\PM Stack\tools-gh\gh.exe`，已登录账号 `Song-wenpeng`。Clash Verge 混合端口 `127.0.0.1:7897`。**git / gh 当前都没有配置代理**，默认直连，因此 `uploads.github.com` 不可达 → 附件上传必然失败。

## 五、根因判断

本机 DNS 将 `uploads.github.com` 解析到了普通 GitHub 前端 IP，Clash 代理也没有纠正该结果。对根路径的 GET/HEAD 请求返回 301 只是网页跳转，不能证明 Release 上传 POST 有效。公共 DNS-over-HTTPS 在处理时返回 `alambic-origin.githubusercontent.com` 及上传节点 IP；用 `curl --resolve` 临时覆盖解析并保留 `uploads.github.com` 的 Host/SNI 后，上传 API 返回 201。

上传节点 IP 会随时间和地区变化，不能永久写死。每次遇到同类问题应重新查询公共 DNS，并在上传完成后取消临时覆盖。

## 六、推荐解决方案

**方案 A（仅适用于代理能正确转发上传 POST 时）** — 在 Git Bash 中执行：

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

# 2) 再逐个上传附件（前提：代理没有把 POST 错误重定向）
HTTPS_PROXY=http://127.0.0.1:7897 HTTP_PROXY=http://127.0.0.1:7897 \
"D:/PM Stack/tools-gh/gh.exe" release upload v1.10.3 --repo Song-wenpeng/PM-Stack \
  "C:/Users/QJH/AppData/Local/Temp/rel_upload/PM-Stack.exe" \
  "C:/Users/QJH/AppData/Local/Temp/rel_upload/PM-Stack-v1.10.3.zip" \
  "C:/Users/QJH/AppData/Local/Temp/rel_upload/update.json"
```

**方案 C（本次实际解法：临时覆盖错误 DNS）**

先通过可信的公共 DNS-over-HTTPS 查询当前地址。确认结果后，使用 `curl --resolve` 只覆盖本次连接；`--resolve` 仍然保留原域名和 TLS SNI，比直接把 URL 改成 IP 安全。

```powershell
# 查询结果必须在每次故障时重新获取；不要长期写死示例 IP
curl.exe -x http://127.0.0.1:7897 `
  -H "Accept: application/dns-json" `
  "https://dns.google/resolve?name=uploads.github.com&type=A"

$uploadIp = "<本次查询得到的上传节点 IP>"
$releaseId = "<Release ID>"
$token = gh auth token

curl.exe --resolve "uploads.github.com:443:$uploadIp" `
  -X POST `
  -H "Accept: application/vnd.github+json" `
  -H "Authorization: Bearer $token" `
  -H "X-GitHub-Api-Version: 2026-03-10" `
  -H "Content-Type: application/octet-stream" `
  --data-binary "@待上传文件" `
  "https://uploads.github.com/repos/OWNER/REPO/releases/$releaseId/assets?name=附件名"

Remove-Variable token
```

成功响应必须是 HTTP 201；301 只表示错误重定向，不能算上传成功。令牌变量不得打印、记录或保存到脚本和仓库。

**方案 D（给 gh / git 配置代理）**

```bash
# gh 永久走代理（gh 读环境变量，可设系统级 HTTPS_PROXY）
# git 针对 github.com 走代理，顺便解决 push 间歇性 RST：
git config --global http.https://github.com.proxy http://127.0.0.1:7897
```

## 七、重试前务必确认

1. **远端 tag/release 状态**：创建前查询是否有残留；只有确认无有效内容时才清理。v1.10.3 当前已发布，不得执行删除命令。
2. **暂存附件是否还在**：`ls "C:/Users/QJH/AppData/Local/Temp/rel_upload/"`；丢失则需重新整理（EXE 来自 `D:/PM Stack/PM Stack/dist/PM Stack.exe`，需重命名为 `PM-Stack.exe`）。
3. **`update.json` 内容正确**：`url` 必须是绝对地址 `https://github.com/Song-wenpeng/PM-Stack/releases/download/v1.10.3/PM-Stack.exe`，且 `sha256` 与上传的 EXE 一致（`1c61483...`）。修正已提交并推送到 `main`。
4. **附件命名用连字符**：`PM-Stack.exe`，与 update.json 的 url 末尾一致，否则自动更新会 404。
5. **`--latest` 必须加**：自动更新通道指向 `releases/latest/download/update.json`。

## 八、自动更新链路（背景，供理解为何命名/latest 很关键）

- `update-channel.json` 里 `manifest_source = https://github.com/Song-wenpeng/PM-Stack/releases/latest/download/update.json`
- 程序读到该 manifest 后，`core/app_updater.py:_resolve_asset_source` 解析 `url`：
  - 绝对 https 地址 → 原样使用；
  - 相对地址 → 用 `urljoin(manifest_source, 相对地址)` 拼接。
- 因此：Release 附件里的 `update.json` 的 `url` 字段，必须能解析到一个真实存在、命名完全一致的 Release 附件（`PM-Stack.exe`）。命名不符或没标 latest，自动更新都会失败。
