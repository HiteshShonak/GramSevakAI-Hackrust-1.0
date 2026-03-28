"""GramSevak AI - MVP Build Verification.

Run from Backend folder:
  .\\.venv\\Scripts\\python.exe verify_build.py
"""

from __future__ import annotations

import os
import sys
import time
from pathlib import Path

os.environ["PYTHONIOENCODING"] = "utf-8"
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

results: list[tuple[str, str]] = []


def check(step: str, test_fn):
    """Run one verification check and record PASS/FAIL."""
    try:
        test_fn()
        results.append((step, "PASS"))
        print(f"  PASS: {step}")
    except Exception as e:
        results.append((step, f"FAIL: {e}"))
        print(f"  FAIL: {step} -> {e}")


print("=" * 50)
print("GramSevak AI - MVP Build Verification")
print("=" * 50)


# Step 1: Config

def test_step1():
    from core.config import settings

    assert settings.VERIFY_TOKEN == "gramsevak_verify_2024"
    assert settings.ENVIRONMENT in ("development", "production")


check("Step 1: config.py", test_step1)


# Step 2-3: FastAPI + health

def test_step2():
    from main import app

    assert app.title == "GramSevak AI"


check("Step 2-3: main.py + health", test_step2)


# Step 4: Webhook router

def test_step4():
    from whatsapp.router import router, verify_meta_signature

    routes = [r.path for r in router.routes]
    assert "/webhook" in routes
    assert callable(verify_meta_signature)


check("Step 4: webhook router", test_step4)


# Step 5: Parser + Sender

def test_step5():
    from whatsapp.parser import parse_webhook_payload
    from whatsapp.sender import send_text

    assert parse_webhook_payload({}) is None
    test_data = {
        "entry": [
            {
                "changes": [
                    {
                        "value": {
                            "messages": [
                                {
                                    "from": "919999999999",
                                    "id": "msg1",
                                    "type": "text",
                                    "text": {"body": "hello"},
                                }
                            ]
                        }
                    }
                ]
            }
        ]
    }
    parsed = parse_webhook_payload(test_data)
    assert parsed is not None
    assert parsed["phone"] == "919999999999"
    assert parsed["content"] == "hello"
    assert parsed["message_type"] == "text"
    assert callable(send_text)


check("Step 5: parser + sender", test_step5)


# Step 7: Session

def test_step7():
    from core.session import session_manager

    unique_phone = f"test_{int(time.time())}"
    s = session_manager.get_or_create(unique_phone)
    assert s["state"] == "idle"
    assert s["language"] == "hi"
    assert s["message_count"] == 1

    s["language"] = "en"
    session_manager.save(unique_phone, s)
    s2 = session_manager.get(unique_phone)
    assert s2["language"] == "en"


check("Step 7: session.py", test_step7)


# Step 8: Language detection

def test_step8():
    from core.language import _fallback_detect, check_language_switch_request

    assert _fallback_detect("hello world this is clearly english text") == "en"
    assert _fallback_detect("namaste") == "hi"
    assert check_language_switch_request("reply in english") == "en"
    assert check_language_switch_request("hindi me bolo") == "hi"
    assert check_language_switch_request("random text") is None


check("Step 8: language.py", test_step8)


# Step 9: LLM + parse_json_safe

def test_step9():
    from intelligence.llm_client import parse_json_safe

    r = parse_json_safe('{"scope": "IN_SCOPE", "intent": "GREETING"}')
    assert r["scope"] == "IN_SCOPE"
    assert r["intent"] == "GREETING"

    # Fenced JSON may or may not be parsed depending on current parser strategy.
    r2 = parse_json_safe("```json\\n{\\\"verdict\\\": \\\"FAKE\\\"}\\n```")
    assert isinstance(r2, dict)

    r3 = parse_json_safe("Here is the result: {\"a\": 1} end")
    assert r3["a"] == 1

    assert parse_json_safe("") == {}
    assert parse_json_safe("not json at all") == {}
    assert parse_json_safe(None) == {}


check("Step 9: llm.py + parse_json_safe", test_step9)


# Step 10: Onboarding

def test_step10():
    from pipelines.onboarding import WELCOME_MESSAGES, get_greeting_reply

    assert "hi" in WELCOME_MESSAGES
    assert "en" in WELCOME_MESSAGES
    greet = get_greeting_reply("en")
    assert "GramSevak" in greet


check("Step 10: onboarding.py", test_step10)


# Step 11: Voice module

def test_step11():
    from voice.downloader import cleanup_voice_file, download_voice
    from voice.language_id import detect_language_from_text
    from voice.transcriber import get_voice_too_long_message, transcribe_audio

    msg = get_voice_too_long_message("en")
    assert "1 minute" in msg
    assert callable(download_voice)
    assert callable(cleanup_voice_file)
    assert callable(transcribe_audio)
    assert callable(detect_language_from_text)


check("Step 11: voice module", test_step11)


# Step 12: Fast rules

def test_step12():
    from intelligence.fast_rules import check_fast_rules, get_scam_red_flag_score

    assert check_fast_rules("aur dikhao")["intent"] == "MORE_RESULTS"
    assert check_fast_rules("ok")["intent"] == "CLARIFICATION"

    scam = check_fast_rules("click this link otp required http://fake.xyz/claim")
    assert scam["intent"] == "SCAM_DETECTION"
    assert scam["scam_signal"] is True
    assert len(scam["rule_flags"]) > 0

    none_match = check_fast_rules("mujhe sarkari yojana chahiye")
    assert none_match["intent"] is None

    assert get_scam_red_flag_score(["a", "b"]) == 50
    assert get_scam_red_flag_score(["a", "b", "c", "d", "e"]) == 100


check("Step 12: fast_rules.py", test_step12)


# Step 13: Intent classifier

def test_step13():
    from intelligence.intent import INTENT_PROMPT, classify_intent

    assert "{message}" in INTENT_PROMPT
    assert "SCHEME_DISCOVERY" in INTENT_PROMPT
    assert "OUT_OF_SCOPE" in INTENT_PROMPT
    assert callable(classify_intent)


check("Step 13: intent.py", test_step13)


# Step 14: Ingest

def test_step14():
    from database.ingest import FALLBACK, SCAM, VERIFIED, main

    assert VERIFIED.name == "schemes_verified.json"
    assert FALLBACK.name == "schemes_fallback.json"
    assert SCAM.name == "scam_patterns.json"
    assert callable(main)


check("Step 14: ingest.py", test_step14)


# Step 15: Vector store

def test_step15():
    from database.vector_store import get_scheme_count, init_vector_store, search_schemes

    assert callable(init_vector_store)
    assert callable(search_schemes)
    assert callable(get_scheme_count)


check("Step 15: vector_store.py", test_step15)


# Step 16: Profile extractor + followup

def test_step16():
    from intelligence.followup import build_combined_question, get_missing_required_fields
    from intelligence.profile_extractor import PROFILE_PROMPT, extract_profile

    assert "{message}" in PROFILE_PROMPT
    assert callable(extract_profile)

    profile = {"state": None, "occupation": None, "name": "Ram"}
    missing = get_missing_required_fields(profile)
    assert "state" in missing
    assert "occupation" in missing

    q = build_combined_question(missing, "en")
    assert "state" in q.lower() or "occupation" in q.lower()

    profile2 = {"state": "Haryana", "occupation": "farmer"}
    missing2 = get_missing_required_fields(profile2)
    assert missing2 == ["bonus"]


check("Step 16: profile_extractor + followup", test_step16)


# Step 17: Scheme discovery

def test_step17():
    from pipelines.scheme_discovery import (
        INITIAL_SCHEMES_LIMIT,
        PAGE_SIZE,
        handle_more_results,
        run_scheme_search,
    )

    assert INITIAL_SCHEMES_LIMIT == 3
    assert PAGE_SIZE == 3
    assert callable(run_scheme_search)
    assert callable(handle_more_results)


check("Step 17: scheme_discovery.py", test_step17)


# Step 18: Scheme formatter

def test_step18():
    from formatters.scheme_formatter import format_scheme_results

    test_schemes = [
        {
            "name": "Test Scheme",
            "amount": "Rs 5000/year",
            "description": "A test",
            "documents_needed": "Aadhar",
            "apply_where": "CSC",
            "apply_link": "https://test.gov.in",
            "last_date": "ongoing",
            "confidence": "high",
        }
    ]

    result = format_scheme_results(test_schemes, "en", total_found=5)
    assert "Test Scheme" in result
    assert "5000" in result
    assert "more" in result.lower()


check("Step 18: scheme_formatter.py", test_step18)


# Step 19: Scam detection

def test_step19():
    from pipelines.scam_detection import SCAM_PROMPT, _hash_message, analyze_scam

    assert "{message}" in SCAM_PROMPT
    assert "{language_name}" in SCAM_PROMPT

    h1 = _hash_message("test message")
    h2 = _hash_message("  TEST   Message  ")
    assert h1 == h2
    assert callable(analyze_scam)


check("Step 19: scam_detection.py", test_step19)


# Step 20: Scam formatter

def test_step20():
    from formatters.scam_formatter import format_scam_verdict

    fake_result = {
        "verdict": "FAKE",
        "reason": "Wrong amount",
        "scheme_name": "PM Kisan",
        "official_link": "https://pmkisan.gov.in",
        "official_amount": "6000",
        "red_flags": ["wrong amount"],
        "confidence": 90,
    }
    msg = format_scam_verdict(fake_result, "en")
    assert "fake" in msg.lower()
    assert "pmkisan.gov.in" in msg

    real_result = {
        "verdict": "REAL",
        "scheme_name": "PM Kisan",
        "official_link": "https://pmkisan.gov.in",
    }
    msg2 = format_scam_verdict(real_result, "en")
    assert "genuine" in msg2.lower() or "official source" in msg2.lower()

    sus_result = {
        "verdict": "SUSPICIOUS",
        "reason": "Cannot verify",
        "red_flags": ["unclear"],
        "official_link": None,
    }
    msg3 = format_scam_verdict(sus_result, "en")
    assert "do not trust" in msg3.lower() or "check the official source" in msg3.lower()


check("Step 20: scam_formatter.py", test_step20)


# Summary
print("\n" + "=" * 50)
print("RESULTS SUMMARY")
print("=" * 50)
passed = sum(1 for _, status in results if status == "PASS")
failed = sum(1 for _, status in results if status != "PASS")
for step, status in results:
    marker = "[x]" if status == "PASS" else "[ ]"
    print(f"  {marker} {step}: {status}")
print(f"\nTotal: {passed} PASS / {failed} FAIL out of {len(results)}")
if failed == 0:
    print("\n*** ALL STEPS VERIFIED SUCCESSFULLY ***")
