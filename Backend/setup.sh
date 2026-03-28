#!/bin/bash
PYTHON="/c/Users/hites/AppData/Local/Programs/Python/Python311/python.exe"
echo "Using Python at: $PYTHON"
$PYTHON --version
$PYTHON -m pip install fastapi uvicorn httpx pydantic-settings python-multipart "python-jose[cryptography]" diskcache chromadb python-dotenv sentence-transformers datasets
echo "--- Install complete ---"
$PYTHON -c "from core.config import settings; print('Config loaded OK')"
$PYTHON -c "from intelligence.fast_rules import check_fast_rules; print('fast_rules OK')"
$PYTHON -c "from whatsapp.parser import parse_webhook_payload; print('parser OK')"
echo "--- Verification complete ---"
