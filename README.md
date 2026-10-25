# x-ai-pipeline

## 这是什么

由抓取 bot 把选定 X 账号的 AI 绘画帖子（提示词 + 媒体）推送到 `inbox/`，本流水线每天处理这些文件，用 gpt-image-2（经 bytecat）生成图片，发布到画廊仓库 [`iamyours/ai-image-gallery`](https://github.com/iamyours/ai-image-gallery)，
并把视频任务写入 `pending_videos.json` 队列，由机器人用 Muse 生成视频（本流水线**不**生成视频）。

## 流程图

```
 抓取 bot ─> inbox/*.json ─> 去重(state/seen.json) ─> 提取提示词(原文，不改写) ─> 下载媒体
                                                    │
                                  无提示词 ──> skipped_no_prompt
                                                   │
                      ┌────────────────────────────┴───────────────────┐
                 图片帖 / 纯文本                                    视频帖
                      │                                                 │
          gpt-image-2 生成 gen.png                        生成参考图 ref.png (人物/场景段落)
                      │                                                 │
     写入画廊 works/<id>/ 并 push (Pages 自动部署)            追加到 pending_videos.json (pending)
                                                                        │
                                                       视频机器人: mark <slug> done --video-url ...
```

## 需要的 Secrets

| Secret | 是否必需 | 说明 |
| --- | --- | --- |
| `BYTECAT_API_KEY` | **必需** | 生图接口密钥（未设置则跳过生图，帖子留待下次） |
| `MODELSCOPE_API_KEY` | 可选 | ModelScope（魔搭）DeepSeek 接口密钥，用于 LLM 提取提示词；有免费额度，按调用计费。未设置则用正则规则。可选 repo variable `MODELSCOPE_MODEL`（默认 `deepseek-ai/DeepSeek-V4.1-Flash-1017`） |
| `GALLERY_PUSH_TOKEN` | 发布需要 | fine-grained PAT，仅授权 `ai-image-gallery` 仓库，权限 Contents: Read and write |

### inbox 原始响应模式（机器人最少处理）

机器人也可以把 **X API v2 原始响应** 原样推送，无需自己整理。`inbox/YYYY-MM-DD.json` 可以是：
标准化帖子数组、单个原始响应对象、原始响应数组、`{"responses": [...]}` 或 `{"posts": [...]}`（可混合）。
原始响应由 `pipeline/inbox.py` 中的纯函数规范化（不联网）：作者名取自 `includes.users`（经 `author_id`），媒体来自 `attachments.media_keys` → `includes.media`，
优先使用 `note_tweet.text`，同一 `conversation_id` 下 `in_reply_to_user_id == author_id` 的自回复归并到根帖作为提示词候选。

```json
{"data": [
   {"id": "5001", "text": "新作 https://t.co/a", "author_id": "42", "conversation_id": "5001",
    "attachments": {"media_keys": ["3_1"]}},
   {"id": "5002", "text": "@bot Prompt: a fox in snow, 85mm --ar 2:3", "author_id": "42",
    "conversation_id": "5001", "in_reply_to_user_id": "42",
    "referenced_tweets": [{"type": "replied_to", "id": "5001"}]}],
 "includes": {"users": [{"id": "42", "username": "someartist"}],
              "media": [{"media_key": "3_1", "type": "photo", "url": "https://pbs.twimg.com/media/x.jpg",
                         "width": 1000, "height": 1500}]}}
```

## 提示词提取：LLM + 原文校验 + 正则回退

设置 `MODELSCOPE_API_KEY` 后，先用 ModelScope DeepSeek（OpenAI 兼容接口，temperature 0，每次最多 8 帖）判断帖子是否为含提示词的 AI 作品，
并返回提示词片段（来源候选序号 + 原文）。代码会 **逐段校验**：每段 `strip()` 后必须是对应候选文本的**逐字子串**，
否则丢弃该帖的 LLM 结果（日志 `LLM 提取结果不是原文子串，已拒绝`）并回退到正则规则；通过校验的片段按序以 `\n\n` 拼接。
LLM 判定「非 AI 作品/无提示词」的帖子记为 `skipped_no_prompt`，原因写入 `state/seen.json` 的 `reason`。
未设置密钥、调用失败（仅网络错误/5xx 重试一次）或结果缺失时，同样使用正则规则（日志 `MODELSCOPE_API_KEY 未设置：使用正则规则提取提示词`）。
机器人提供的 `prompt_text` 若通过子串校验则直接采用，不再调用 LLM。

## 如何修改账号列表

编辑 `config/accounts.yml` 的 `accounts`（不带 `@`）。同文件还有 `max_images_per_run`、`max_posts_per_account`、`image_size`、`gallery_repo`、`gallery_tag`。

## 数据流：抓取 bot → inbox → Actions

流水线**不访问 X API，也不使用 X 令牌**。输入只来自 `inbox/`：抓取 bot 读取 `config/accounts.yml`，抓取各账号的帖子，把结果推送到 `inbox/YYYY-MM-DD.json`；
push 到 `inbox/**`、每日 cron、手动 `workflow_dispatch` 都会触发工作流。inbox 文件不会被修改，已处理文件的哈希记录在 `state/seen.json` 的 `processed_inbox`；同名文件内容变化会被重新处理（已见过的 tweet_id 仍会跳过）。
下载 `pbs.twimg.com` / `video.twimg.com` 的媒体文件不属于 API 调用，仍然允许。

## 给抓取 bot 的约定

1. **账号**：读取仓库 `config/accounts.yml` 的 `accounts`（YAML 列表，不带 `@`；以 `#` 注释的账号不要抓取）。`max_posts_per_account` 是每账号每次抓取数量的建议值。
2. **文件名**：`inbox/YYYY-MM-DD.json`（UTC 日期）；同一天多次推送请用不同后缀，如 `inbox/2026-10-25-sandmrk.json`。
3. **允许的格式**：标准化帖子数组、`{"posts": [...]}`、单个 X API v2 原始响应、原始响应数组或 `{"responses": [...]}`（可混合，见上文）。
4. **提交**：把文件 commit 并 push 到 `main`（push 会触发工作流）。不要修改或删除已推送的文件。
5. **去重**：由流水线通过 `state/seen.json` 完成，bot 无需关心；重复推送同一帖子是安全的。

文件内容为数组，或 `{"posts": [...]}`，每项：

| 字段 | 说明 |
| --- | --- |
| `tweet_id` | 字符串，唯一 id |
| `url` | 帖子链接 |
| `author` | 作者用户名（可带 `@`） |
| `text` | 帖子正文 |
| `prompt_text` | 提示词原文（可为空）。必须是 `text`/`replies` 中某段文字的原文子串才会被采用，否则忽略并重新分析 |
| `replies` | 可选，作者自回复文本数组（提示词候选） |
| `media` | `[{type: photo\|video\|animated_gif, url}]`，可选 `width`/`height` |
| `created_at` | ISO 时间 |

```json
{"posts": [{
  "tweet_id": "2113244500646859081",
  "url": "https://x.com/sandmrk/status/2113244500646859081",
  "author": "sandmrk",
  "text": "暗红旗袍 https://t.co/xxx",
  "prompt_text": "暗红旗袍奇幻肖像……",
  "media": [{"type": "photo", "url": "https://pbs.twimg.com/media/xxx.jpg"}],
  "created_at": "2026-10-25T01:00:00Z"
}]}
```

## 视频队列约定

`pending_videos.json` 是条目列表：`slug`, `ref_image`（仓库相对路径）, `ref_image_url`（raw.githubusercontent 链接）, `video_prompt`（原文）, `source_url`, `author`, `original_video`（仓库路径或 null）, `created_at`, `status`，以及可选的 `video_url`, `note`, `updated_at`。

`status` 取值：`pending`（待处理）、`done`（已生成）、`rejected`（放弃）。

```bash
python scripts/queue.py list --status pending
python scripts/queue.py show <slug>
python scripts/queue.py mark <slug> done --video-url https://... [--note TEXT]
```

机器人修改后需自行 commit 并 push；视频机器人负责把条目标记为 `done`。

## 成本说明

- gpt-image-2（bytecat）约 **$0.13/张**，偶尔因慢请求被重复计费为 $0.26。
- `max_images_per_run` 默认 5（视频参考图也计入）⇒ 每天最多约 $0.65–1.3。
- **永不自动重试**：每个帖子只请求一次，超时也可能已扣费。失败/审核拦截的帖子会记入 seen，不会再次尝试。超出上限的帖子保持未处理，留给下次运行。

## 本地测试

```bash
DRY_RUN=1 python -m pipeline.run     # 不访问任何网络，生成占位图
python -m unittest                   # 或 python -m unittest discover -s tests -v
```

`DRY_RUN=1` 会写入本地 `data/`、`state/`、`pending_videos.json`（测试请在临时副本里跑）；若设置 `GALLERY_DIR` 会把作品写入该目录但不提交。工作流的手动 dry_run 不会提交结果。

## 手动重跑一条

从 `state/seen.json` 的 `seen` 里删除对应的 tweet_id（失败 `failed`、审核 `skipped_moderation` 的也一样），提交后下次运行会重新处理。
