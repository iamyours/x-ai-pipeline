# Muse 任务说明：tari323 视频复刻流水线

## 分工
- **小M（Grok Bot）**：只负责把 X 上的素材提交到 `resources/<账号>/<post_id>/`：
  - `video.mp4` 原始视频
  - `thumb.jpg` 封面
  - `text.txt` 原帖文案和作者自回复（原文）
  - `post.json` 元数据
  - 总索引 `resources/<账号>/index.json`，每条 `status: "pending"`
- **Muse**：监听仓库提交（定时 `git pull`），处理 pending 素材，生成结果并发布 GitHub Pages。

## Muse 每小时任务
1. `git pull` 拉取最新代码。从 `resources/*/index.json` 里按日期取最多 **10 条** `status == "pending"` 的视频。
   - 重试规则：如果 `works/<post_id>/` 下已经有 `image_prompt.txt` / `image.png` / `video_prompt.txt`，直接复用，不要重新生成，只补缺的步骤（比如只补 `muse.mp4`）。
2. 对每条视频：
   1. 分析原视频，写出英文首帧图片提示词，存到 `works/<post_id>/image_prompt.txt`。
   2. 用 bytecat（gpt-image-2）生成首帧图，存到 `works/<post_id>/image.png`。key 和接口见 `secrets/README.md`，明文 key 不要提交。
   3. 写出英文视频提示词，存到 `works/<post_id>/video_prompt.txt`。
   4. Muse 自己用 `image.png` 作首帧或人物参考，配合 `video_prompt.txt` 生成视频，存到 `works/<post_id>/muse.mp4`。
   5. 每步只做一次，被拒或失败就跳过，不改写、不重试。把 index 里的状态改成 `done`、`refused` 或 `failed`，并写 `reason`。
3. 提交时 commit 信息**不要**带 `[skip ci]`（GitHub Pages 从 main 的 /docs 发布，带 `[skip ci]` 会跳过站点部署），用 SSH 推送到 `main`。
4. 重新生成并发布 GitHub Pages 站点（见下）。

## GitHub Pages 站点
每条作品一张卡片或一个详情页，并排展示：
- **原始视频**：`resources/.../video.mp4`，附原帖链接和文案
- **反推图片**：`works/<id>/image.png`
- **提示词**：图片提示词和视频提示词，可复制
- **反推视频**：`works/<id>/muse.mp4`

首页按日期倒序，能按状态筛选。

## 注意
- 单个文件不能超过 100MB。超过的视频先压缩，或改放到 GitHub Release，并在 index 里写上 URL。
- 不要改动现有的 `pipeline/`、`inbox/` 流程。
