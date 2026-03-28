@echo off
set PYTHON=C:\Users\hites\AppData\Local\Programs\Python\Python311\python.exe
echo Using: %PYTHON%
%PYTHON% --version
%PYTHON% -m pip install --upgrade pip
%PYTHON% -m pip install fastapi uvicorn httpx pydantic-settings python-multipart diskcache chromadb python-dotenv sentence-transformers datasets "python-jose[cryptography]"
echo --- Dependencies installed ---
cd /d D:\GramSevakAI
%PYTHON% -c "from core.config import settings; print('OK: config loaded, VERIFY_TOKEN=' + settings.VERIFY_TOKEN)"
%PYTHON% -c "from intelligence.fast_rules import check_fast_rules; r=check_fast_rules('aur dikhao'); print('OK: fast_rules, intent=' + str(r['intent']))"
%PYTHON% -c "from whatsapp.parser import parse_webhook_payload; print('OK: parser loaded')"
%PYTHON% -c "from core.llm import parse_json_safe; r=parse_json_safe('{\"a\":1}'); print('OK: parse_json_safe, result=' + str(r))"
echo --- All verifications done ---
