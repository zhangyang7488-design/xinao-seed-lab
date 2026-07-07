from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class PriceEntry:
    catalog_id: str
    provider_family: str
    model: str
    input_usd_per_1m: float
    output_usd_per_1m: float
    cached_input_usd_per_1m: float = 0.0
    source_url: str = ""


PRICE_CATALOG: dict[str, PriceEntry] = {
    "openai_gpt_5_5": PriceEntry(
        catalog_id="openai_gpt_5_5",
        provider_family="openai",
        model="gpt-5.5",
        input_usd_per_1m=5.0,
        cached_input_usd_per_1m=0.5,
        output_usd_per_1m=30.0,
        source_url="https://developers.openai.com/api/docs/pricing",
    ),
    "openai_gpt_5_3_codex": PriceEntry(
        catalog_id="openai_gpt_5_3_codex",
        provider_family="openai_codex",
        model="gpt-5.3-codex",
        input_usd_per_1m=1.75,
        cached_input_usd_per_1m=0.175,
        output_usd_per_1m=14.0,
        source_url="C:/Users/xx363/Desktop/CODEX_TOKEN_COST_ROUTING_QWEN_DP_AUDIT_20260706.txt",
    ),
    "deepseek_v4_flash": PriceEntry(
        catalog_id="deepseek_v4_flash",
        provider_family="deepseek",
        model="deepseek-v4-flash",
        input_usd_per_1m=0.14,
        cached_input_usd_per_1m=0.0028,
        output_usd_per_1m=0.28,
        source_url="https://api-docs.deepseek.com/quick_start/pricing",
    ),
    "deepseek_v4_pro": PriceEntry(
        catalog_id="deepseek_v4_pro",
        provider_family="deepseek",
        model="deepseek-v4-pro",
        input_usd_per_1m=0.435,
        cached_input_usd_per_1m=0.003625,
        output_usd_per_1m=0.87,
        source_url="https://api-docs.deepseek.com/quick_start/pricing",
    ),
    "qwen3_6_flash": PriceEntry(
        catalog_id="qwen3_6_flash",
        provider_family="qwen",
        model="qwen3.6-flash",
        input_usd_per_1m=0.165,
        output_usd_per_1m=0.99,
        source_url="https://www.alibabacloud.com/help/en/model-studio/model-pricing",
    ),
    "qwen3_coder_flash": PriceEntry(
        catalog_id="qwen3_coder_flash",
        provider_family="qwen",
        model="qwen3-coder-flash",
        input_usd_per_1m=0.144,
        output_usd_per_1m=0.574,
        source_url="https://www.alibabacloud.com/help/en/model-studio/model-pricing",
    ),
}

MODEL_ALIASES = {
    "gpt-5.5": "openai_gpt_5_5",
    "gpt-5.3-codex": "openai_gpt_5_3_codex",
    "gpt-5-codex": "openai_gpt_5_3_codex",
    "codex_exec": "openai_gpt_5_3_codex",
    "deepseek-v4-flash": "deepseek_v4_flash",
    "deepseek-chat": "deepseek_v4_flash",
    "deepseek-v4-pro": "deepseek_v4_pro",
    "deepseek-reasoner": "deepseek_v4_pro",
    "qwen3.6-flash": "qwen3_6_flash",
    "qwen3.6-flash-2026-04-16": "qwen3_6_flash",
    "qwen3-coder-flash": "qwen3_coder_flash",
    "qwen3-coder-flash-2025-07-28": "qwen3_coder_flash",
}

PROVIDER_DEFAULTS = {
    "qwen_prepaid_cheap_worker": "qwen3_6_flash",
    "qwen_quality_aux_worker": "qwen3_6_flash",
    "legacy.deepseek_dp_sidecar": "deepseek_v4_flash",
    "deepseek_dp": "deepseek_v4_flash",
    "codex_exec": "openai_gpt_5_3_codex",
    "codex_sdk": "openai_gpt_5_3_codex",
    "codex_exec_engineering_worker": "openai_gpt_5_3_codex",
}


def price_catalog_payload() -> dict[str, Any]:
    return {
        "schema_version": "xinao.codex_s.provider_price_catalog.v1",
        "status": "provider_price_catalog_ready",
        "unit": "usd_per_1m_tokens",
        "entries": {
            key: {
                "provider_family": value.provider_family,
                "model": value.model,
                "input_usd_per_1m": value.input_usd_per_1m,
                "cached_input_usd_per_1m": value.cached_input_usd_per_1m,
                "output_usd_per_1m": value.output_usd_per_1m,
                "source_url": value.source_url,
            }
            for key, value in PRICE_CATALOG.items()
        },
        "aliases": MODEL_ALIASES,
        "provider_defaults": PROVIDER_DEFAULTS,
        "not_completion_boundary": True,
    }


def resolve_price_entry(
    provider: str = "", model: str = "", provider_tier: str = ""
) -> PriceEntry | None:
    model_key = str(model or "").strip().lower()
    provider_key = str(provider or provider_tier or "").strip()
    catalog_id = MODEL_ALIASES.get(model_key)
    if not catalog_id:
        catalog_id = PROVIDER_DEFAULTS.get(provider_key)
    return PRICE_CATALOG.get(catalog_id or "")


def estimate_usage_cost(
    *,
    provider: str = "",
    model: str = "",
    provider_tier: str = "",
    prompt_tokens: int = 0,
    completion_tokens: int = 0,
    cache_hit_tokens: int = 0,
    cache_miss_tokens: int | None = None,
    observed_cost_usd: float | None = None,
) -> dict[str, Any]:
    prompt = max(0, int(prompt_tokens or 0))
    completion = max(0, int(completion_tokens or 0))
    cache_hit = max(0, min(prompt, int(cache_hit_tokens or 0)))
    cache_miss = (
        max(0, int(cache_miss_tokens))
        if cache_miss_tokens is not None
        else max(0, prompt - cache_hit)
    )
    if cache_hit + cache_miss > prompt:
        cache_miss = max(0, prompt - cache_hit)
    entry = resolve_price_entry(provider=provider, model=model, provider_tier=provider_tier)
    observed = None
    if observed_cost_usd not in (None, ""):
        try:
            observed = max(0.0, float(observed_cost_usd or 0.0))
        except (TypeError, ValueError):
            observed = None
    if entry is None:
        return {
            "cost_usd": round(observed or 0.0, 10),
            "estimated_cost_usd": 0.0,
            "cost_source": "provider_reported_cost" if observed else "price_catalog_missing",
            "price_catalog_applied": False,
            "price_catalog_id": "",
            "price_catalog_source_url": "",
            "input_cost_usd": 0.0,
            "cached_input_cost_usd": 0.0,
            "output_cost_usd": 0.0,
            "cache_hit_tokens": cache_hit,
            "cache_miss_tokens": cache_miss,
            "input_rate_usd_per_1m": 0.0,
            "cached_input_rate_usd_per_1m": 0.0,
            "output_rate_usd_per_1m": 0.0,
        }
    input_cost = cache_miss * entry.input_usd_per_1m / 1_000_000
    cached_cost = cache_hit * entry.cached_input_usd_per_1m / 1_000_000
    output_cost = completion * entry.output_usd_per_1m / 1_000_000
    estimated = input_cost + cached_cost + output_cost
    return {
        "cost_usd": round(observed if observed and observed > 0 else estimated, 10),
        "estimated_cost_usd": round(estimated, 10),
        "cost_source": "provider_reported_cost"
        if observed and observed > 0
        else "provider_price_catalog",
        "price_catalog_applied": True,
        "price_catalog_id": entry.catalog_id,
        "price_catalog_model": entry.model,
        "price_catalog_provider_family": entry.provider_family,
        "price_catalog_source_url": entry.source_url,
        "input_cost_usd": round(input_cost, 10),
        "cached_input_cost_usd": round(cached_cost, 10),
        "output_cost_usd": round(output_cost, 10),
        "cache_hit_tokens": cache_hit,
        "cache_miss_tokens": cache_miss,
        "input_rate_usd_per_1m": entry.input_usd_per_1m,
        "cached_input_rate_usd_per_1m": entry.cached_input_usd_per_1m,
        "output_rate_usd_per_1m": entry.output_usd_per_1m,
    }
