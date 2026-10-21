"""StepFun (阶跃星辰) speech-to-text provider adapter for AstrBot.

StepFun does not expose an OpenAI-compatible ``/audio/transcriptions`` endpoint.
Its ASR is a single POST to ``.../audio/asr/sse`` carrying base64 audio and
streams the transcript back as Server-Sent Events, so the built-in
``openai_whisper_api`` STT provider cannot talk to it.

This plugin registers a ``stepfun_asr`` provider type so StepFun ASR can be
selected in the WebUI like any other STT provider.

Docs: https://platform.stepfun.com/docs/zh/api-reference/audio/asr-sse
"""

from __future__ import annotations

import base64
import json

import httpx

from astrbot.api import logger
from astrbot.api.provider import ProviderType, STTProvider
from astrbot.api.star import Context, Star
from astrbot.core.provider.register import provider_cls_map, register_provider_adapter
from astrbot.core.utils.media_utils import MediaResolver

PROVIDER_TYPE = "stepfun_asr"
DEFAULT_API_BASE = "https://api.stepfun.com/step_plan/v1"
DEFAULT_MODEL = "stepaudio-2.5-asr"
ASR_PATH = "/audio/asr/sse"

DELTA_EVENT = "transcript.text.delta"
DONE_EVENT = "transcript.text.done"
ERROR_EVENT = "error"

DEFAULT_CONFIG_TMPL = {
    "id": PROVIDER_TYPE,
    "type": PROVIDER_TYPE,
    "provider": "stepfun",
    "provider_type": "speech_to_text",
    "enable": False,
    "api_key": "",
    "api_base": DEFAULT_API_BASE,
    "model": DEFAULT_MODEL,
    "timeout": 120,
    "proxy": "",
}


def build_asr_endpoint(api_base: str | None) -> str:
    """Normalize a StepFun base URL into the full ASR SSE endpoint.

    Accepts ``https://api.stepfun.com``, ``.../v1``, ``.../step_plan/v1`` or the
    full endpoint itself, so users can paste whatever the doc page shows.
    """
    base = (api_base or DEFAULT_API_BASE).strip().rstrip("/")
    if not base:
        base = DEFAULT_API_BASE
    if base.endswith(ASR_PATH):
        return base
    if base.endswith("/v1"):
        return base + ASR_PATH
    return base + "/v1" + ASR_PATH


class StepFunASRProvider(STTProvider):
    """STT provider speaking StepFun's HTTP + SSE ASR protocol."""

    def __init__(self, provider_config: dict, provider_settings: dict) -> None:
        super().__init__(provider_config, provider_settings)
        self.api_key = (provider_config.get("api_key") or "").strip()
        self.endpoint = build_asr_endpoint(provider_config.get("api_base"))
        self.proxy = (provider_config.get("proxy") or "").strip()
        self.timeout = float(provider_config.get("timeout") or 120)
        self.set_model(provider_config.get("model") or DEFAULT_MODEL)
        self.client = httpx.AsyncClient(
            timeout=httpx.Timeout(self.timeout, connect=15.0),
            proxy=self.proxy or None,
        )

    async def _encode_audio(self, audio_url: str) -> str:
        """Convert any incoming audio reference to base64 WAV."""
        resolver = MediaResolver(
            audio_url,
            media_type="audio",
            default_suffix=".wav",
        )
        async with resolver.as_path(target_format="wav") as audio:
            return base64.b64encode(audio.read_bytes()).decode("ascii")

    def _build_payload(self, audio_base64: str) -> dict:
        return {
            "audio": {
                "data": audio_base64,
                "input": {
                    "transcription": {
                        "model": self.model_name,
                        "enable_itn": True,
                    },
                    "format": {
                        "type": "wav",
                    },
                },
            }
        }

    async def get_text(self, audio_url: str) -> str:
        if not self.api_key:
            raise RuntimeError("StepFun ASR: API Key 未填写")

        payload = self._build_payload(await self._encode_audio(audio_url))
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
            "Accept": "text/event-stream",
            **self.request_headers,
        }

        deltas: list[str] = []
        final_text = ""

        try:
            async with self.client.stream(
                "POST",
                self.endpoint,
                headers=headers,
                json=payload,
            ) as response:
                if response.status_code >= 400:
                    body = (await response.aread()).decode("utf-8", "replace")
                    raise RuntimeError(
                        f"StepFun ASR 请求失败: HTTP {response.status_code} "
                        f"{body[:400]} (endpoint={self.endpoint})",
                    )

                async for raw_line in response.aiter_lines():
                    line = raw_line.strip()
                    if not line.startswith("data:"):
                        continue
                    data = line[len("data:") :].strip()
                    if not data or data == "[DONE]":
                        continue
                    try:
                        event = json.loads(data)
                    except json.JSONDecodeError:
                        logger.debug(
                            f"StepFun ASR: 跳过无法解析的 SSE 数据: {data[:200]}"
                        )
                        continue

                    event_type = event.get("type")
                    if event_type == DELTA_EVENT:
                        deltas.append(event.get("delta") or "")
                    elif event_type == DONE_EVENT:
                        final_text = event.get("text") or ""
                    elif event_type == ERROR_EVENT:
                        raise RuntimeError(
                            f"StepFun ASR 返回错误: {event.get('message')}",
                        )
        except httpx.HTTPError as exc:
            raise RuntimeError(f"StepFun ASR 网络请求失败: {exc}") from exc

        text = (final_text or "".join(deltas)).strip()
        if not text:
            raise RuntimeError("StepFun ASR 返回空识别结果")
        return text

    async def terminate(self) -> None:
        if self.client:
            await self.client.aclose()


def _register_provider() -> None:
    """Register the adapter once; plugin reloads must not re-register."""
    if PROVIDER_TYPE in provider_cls_map:
        return
    register_provider_adapter(
        PROVIDER_TYPE,
        "StepFun ASR (阶跃星辰语音识别，HTTP + SSE)",
        provider_type=ProviderType.SPEECH_TO_TEXT,
        default_config_tmpl=dict(DEFAULT_CONFIG_TMPL),
        provider_display_name="StepFun ASR",
    )(StepFunASRProvider)


_register_provider()


class StepFunASRPlugin(Star):
    def __init__(self, context: Context) -> None:
        super().__init__(context)
        logger.info(
            "StepFun ASR provider registered (type=%s, endpoint template=%s)",
            PROVIDER_TYPE,
            build_asr_endpoint(DEFAULT_API_BASE),
        )

    async def terminate(self) -> None:
        logger.info("StepFun ASR plugin unloaded")
