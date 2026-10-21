# astrbot_plugin_stepfun_asr

给 AstrBot 增加一个 `stepfun_asr` 提供商类型，用阶跃星辰（StepFun）的语音识别接口。

## 为什么需要它

AstrBot 内置的 STT 只有 `openai_whisper_api`，请求 `POST /audio/transcriptions`（multipart）。
阶跃只有 `POST /audio/asr/sse`（JSON + base64 音频，SSE 流式返回），所以填 base_url 是没用的，只能加适配器。

## 安装

把整个目录放到 `AstrBot/data/plugins/astrbot_plugin_stepfun_asr/`，然后在 WebUI 插件页启用（或重启 AstrBot）。

## 配置

WebUI → 配置 → 其他配置 → 提供商 → 新增，类型选 **StepFun ASR**：

| 字段 | 填什么 |
| --- | --- |
| API Key | 阶跃平台申请的 Key |
| API Base URL | Step Plan 套餐：`https://api.stepfun.com/step_plan/v1`；普通开放平台：`https://api.stepfun.com/v1` |
| 模型 ID | `stepaudio-2.5-asr`（或 `stepaudio-3-asr-max`、`stepaudio-2-asr-pro`） |
| 超时时间 | 120（秒，长语音可以加大） |

`API Base URL` 有三段式容错：填 `https://api.stepfun.com`、`.../v1`、`.../step_plan/v1` 或完整 endpoint 都能自动补全。

然后在 `语音识别`（provider_stt_settings）里打开开关、把默认语音转文本模型选成刚建的这个。

## 说明

- 音频统一转成 WAV 再上传（`MediaResolver`），opus/silk/amr 等平台格式都能吃。
- `enable_itn` 固定开启（数字、标点规范化）；`language` 不传，交给服务端自动判断。
- 没有实现 WebSocket 双向流式（`/audio/asr-stream`），语音消息转文字用不到。
