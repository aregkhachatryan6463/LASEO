from config.settings import Settings
from src.ai.analyzer import AIAnalyzer


def make_analyzer():
    settings = Settings()
    settings.ai_provider = "none"
    return AIAnalyzer(settings)


def test_parse_valid_json_response():
    analyzer = make_analyzer()
    raw = """{
        "is_residential": true, "is_likely_full_price": true, "potentially_misleading": false,
        "deal_quality": 8, "confidence": 0.86, "positive_factors": ["Good location"],
        "risk_factors": ["Verify ownership"], "urgency_signals": ["Owner states urgent sale"],
        "summary": "Potentially strong opportunity.", "recommendation": "INVESTIGATE"
    }"""
    result = analyzer._parse_response(raw)
    assert result is not None
    assert result.deal_quality == 8
    assert result.recommendation == "INVESTIGATE"
    assert result.used_ai is True


def test_parse_response_wrapped_in_markdown_fences():
    analyzer = make_analyzer()
    raw = '```json\n{"deal_quality": 5, "confidence": 0.5, "recommendation": "WATCH"}\n```'
    result = analyzer._parse_response(raw)
    assert result is not None
    assert result.recommendation == "WATCH"


def test_parse_malformed_json_returns_none():
    analyzer = make_analyzer()
    result = analyzer._parse_response("this is not json at all")
    assert result is None


def test_parse_invalid_recommendation_defaults_to_watch():
    analyzer = make_analyzer()
    raw = '{"deal_quality": 5, "confidence": 0.5, "recommendation": "BUY_NOW_PLEASE"}'
    result = analyzer._parse_response(raw)
    assert result.recommendation == "WATCH"


def test_analyze_falls_back_to_rule_based_when_no_provider():
    analyzer = make_analyzer()
    context = {"title": "Test", "description": "Normal listing", "property_type": "apartment", "discount_percentage": 15}
    result = analyzer.analyze(context)
    assert result.used_ai is False
    assert result.recommendation in ("IGNORE", "WATCH", "INVESTIGATE", "STRONG_DEAL")


def test_rule_based_fallback_flags_risk_keywords():
    analyzer = make_analyzer()
    context = {"title": "Անավարտ շինություն", "description": "անավարտ, առանց ամբողջական փաստաթղթերի",
               "property_type": "house", "discount_percentage": 40}
    result = analyzer.analyze(context)
    assert result.used_ai is False
    assert len(result.risk_factors) > 0
    assert result.recommendation == "INVESTIGATE"
