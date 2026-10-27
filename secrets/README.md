# secrets

`bytecat_api_key.age` 是 bytecat 生图接口密钥，用 [age](https://age-encryption.org) 加密给 Muse 的 SSH 公钥（`muse.pub`，指纹 SHA256:sSv8q3J0ybdqqLr3+2f16OaVmeThtJKZhy/J3fXwu9c）。

Muse 解密：

```bash
age -d -i ~/.ssh/x_ai_pipeline_muse secrets/bytecat_api_key.age > ~/.config/bytecat_api_key   # 不要提交明文
```

bytecat 接口（OpenAI 兼容）：
- 文生图 `POST https://codecdn.bytecatcode.org/v1/images/generations`，JSON `{"model":"gpt-image-2","prompt":"...","size":"1024x1536","n":1}`
- 图生图 `POST https://codecdn.bytecatcode.org/v1/images/edits`，multipart `model`、`prompt`、`size`、`n`、`image`
- Header `Authorization: Bearer <key>`，超时建议 900s，5xx 重试一次
