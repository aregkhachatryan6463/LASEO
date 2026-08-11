"""
AIAnalyzer: pluggable AI backend behind one interface.

Supported AI_PROVIDER values:
  - "none"   : no AI configured. Falls back to rule-based analysis. The
               app is fully functional without any AI provider.
  - "gemini" : Google Gemini free tier (requires AI_API_KEY). Chosen as the
               default cloud option because Gemini has a genuinely free
               tier suitable for a low-volume personal project, unlike
               most OpenAI-compatible APIs.
  - "ollama" : a locally-run open-source model via Ollama
               (https://ollama.com), for a $0-forever, fully local option
               if the user has a computer to run it on. Not usable from
               GitHub Actions (no local machine there) -- intended for
               running the monitor script on your own computer instead.

The AI is only ever called for listings that already passed cheap
deterministic filters (see analysis/filters.should_trigger_ai) -- never for
every listing, per project spec.
"""
from __future__ import annotations

import json
import re
from typing import Optional

import requests

from config.settings import Settings
from src.ai.prompts import SYSTEM_PROMPT, build_user_prompt
from src.models.listing import AIAssessment
from src.utils.logging import logger

_ALLOWED_RECOMMENDATIONS = {"IGNORE", "WATCH", "INVESTIGATE", "STRONG_DEAL"}


class AIAnalyzer:
    def __init__(self, settings: Settings):
        self.settings = settings

    def analyze(self, listing_context: dict) -> AIAssessment:
        provider = self.settings.ai_provider
        try:
            if provider == "gemini" and self.settings.ai_api_key:
                raw = self._call_gemini(listing_context)
            elif provider == "ollama":
                raw = self._call_ollama(listing_context)
            else:
                return self._rule_based_fallback(listing_context)
        except Exception as e:
            logger.warning(f"AI provider '{provider}' failed ({e}); falling back to rule-based analysis")
            return self._rule_based_fallback(listing_context)

        parsed = self._parse_response(raw)
        if parsed is None:
            logger.warning("AI response could not be parsed as valid JSON; falling back to rule-based analysis")
            return self._rule_based_fallback(listing_context)
        return parsed

    # -- providers --------------------------------------------------------

    def _call_gemini(self, listing_context: dict) -> str:
        url = (
            f"https://generativelanguage.googleapis.com/v1beta/models/"
            f"{self.settings.ai_model}:generateContent?key={self.settings.ai_api_key}"
        )
        body = {
            "contents": [{"parts": [{"text": build_user_prompt(listing_context)}]}],
            "systemInstruction": {"parts": [{"text": SYSTEM_PROMPT}]},
            "generationConfig": {"temperature": 0.2, "responseMimeType": "application/json"},
        }
        resp = requests.post(url, json=body, timeout=30)
        resp.raise_for_status()
        data = resp.json()
        return data["candidates"][0]["content"]["parts"][0]["text"]

    def _call_ollama(self, listing_context: dict) -> str:
        url = f"{self.settings.ollama_host}/api/generate"
        prompt = f"{SYSTEM_PROMPT}\n\n{build_user_prompt(listing_context)}"
        body = {"model": self.settings.ollama_model, "prompt": prompt, "stream": False}
        resp = requests.post(url, json=body, timeout=60)
        resp.raise_for_status()
        return resp.json().get("response", "")

    # -- parsing ------------------------------------------------------------

    def _parse_response(self, raw_text: str) -> Optional[AIAssessment]:
        text = raw_text.strip()
        # Strip markdown code fences if the model added them despite instructions.
        text = re.sub(r"^```(json)?", "", text.strip())
        text = re.sub(r"```$", "", text.strip())
        try:
            data = json.loads(text)
        except json.JSONDecodeError:
            return None

        recommendation = data.get("recommendation", "IGNORE")
        if recommendation not in _ALLOWED_RECOMMENDATIONS:
            recommendation = "WATCH"

        try:
            return AIAssessment(
                is_residential=data.get("is_residential"),
                is_likely_full_price=data.get("is_likely_full_price"),
                potentially_misleading=data.get("potentially_misleading"),
                deal_quality=float(data["deal_quality"]) if data.get("deal_quality") is not None else None,
                confidence=float(data["confidence"]) if data.get("confidence") is not None else None,
                positive_factors=list(data.get("positive_factors", [])),
                risk_factors=list(data.get("risk_factors", [])),
                urgency_signals=list(data.get("urgency_signals", [])),
                summary=str(data.get("summary", "")),
                recommendation=recommendation,
                used_ai=True,
            )
        except (TypeError, ValueError) as e:
            logger.warning(f"AI response had unexpected field types ({e})")
            return None

    # -- fallback -------------------------------------------------------------

    def _rule_based_fallback(self, listing_context: dict) -> AIAssessment:
        """
        Simple deterministic heuristic used when no AI provider is configured
        or the AI call/parse failed. Looks for known risk-signal keywords in
        the description text so the app still surfaces obvious red flags.
        """
        text = f"{listing_context.get('title', '')} {listing_context.get('description', '')}".lower()

        risk_keywords = {
            "անավարտ": "possibly unfinished construction",
            "unfinished": "possibly unfinished construction",
            "կիսանկուղ": "possible basement/semi-basement",
            "semi-basement": "possible basement/semi-basement",
            "ապառիկ": "possible installment pricing",
            "աճուրդ": "possible auction sale",
            "մասնաբաժին": "possible partial/shared ownership",
        }
        risk_factors = [note for kw, note in risk_keywords.items() if kw in text]

        urgency_keywords = ["շտապ", "urgent", "срочно"]
        urgency_signals = ["seller indicates urgency"] if any(k in text for k in urgency_keywords) else []

        discount = listing_context.get("discount_percentage")
        deal_quality = 5.0
        if isinstance(discount, (int, float)):
            deal_quality = max(0.0, min(10.0, 5.0 + discount / 8.0))
        if risk_factors:
            deal_quality = max(0.0, deal_quality - 2.0)

        recommendation = "WATCH"
        if risk_factors:
            recommendation = "INVESTIGATE"
        elif deal_quality >= 8 and urgency_signals:
            recommendation = "STRONG_DEAL"
        elif deal_quality >= 7:
            recommendation = "INVESTIGATE"
        elif deal_quality < 5:
            recommendation = "IGNORE"

        return AIAssessment(
            is_residential=listing_context.get("property_type") in ("apartment", "house"),
            is_likely_full_price=not risk_factors,
            potentially_misleading=bool(risk_factors),
            deal_quality=round(deal_quality, 1),
            confidence=0.4,  # rule-based fallback is inherently less confident than a real AI read
            positive_factors=["Below comparable market price"] if isinstance(discount, (int, float)) and discount >= 10 else [],
            risk_factors=risk_factors,
            urgency_signals=urgency_signals,
            summary=(
                "Rule-based assessment (no AI configured or AI call failed): "
                f"estimated discount {discount}%. "
                + ("Some risk keywords detected in description." if risk_factors else "No obvious risk keywords detected.")
            ),
            recommendation=recommendation,
            used_ai=False,
        )
