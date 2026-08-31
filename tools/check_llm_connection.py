# -*- coding: utf-8 -*-
"""Check the configured text-model endpoint without printing credentials."""

import ssl
import sys
from pathlib import Path

import httpx
from openai import OpenAI


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from core.config_manager import ConfigManager


def main():
    manager = ConfigManager()
    api_key = manager.get("api_key")
    base_url = manager.get("base_url")
    model = manager.get("model_name")
    if not api_key:
        raise ValueError("未配置 API Key")
    print(f"BASE_URL={base_url}")
    print(f"MODEL={model}")
    client = OpenAI(api_key=api_key, base_url=base_url, timeout=30)
    request = {
        "model": model,
        "messages": [{"role": "user", "content": "只回复 OK"}],
        "temperature": 0,
        "max_tokens": 8,
    }
    try:
        response = client.chat.completions.create(**request)
    except Exception as exc:
        print(f"ERROR_TYPE={type(exc).__name__}")
        print(f"STATUS={getattr(exc, 'status_code', '')}")
        print(f"ERROR={exc}")
        cause = exc.__cause__
        depth = 0
        while cause is not None and depth < 5:
            print(f"CAUSE_{depth}={type(cause).__name__}: {cause}")
            cause = cause.__cause__
            depth += 1

        print("TRY_TLS12=1")
        context = ssl.create_default_context()
        context.maximum_version = ssl.TLSVersion.TLSv1_2
        transport = httpx.Client(verify=context, timeout=30)
        fallback = OpenAI(
            api_key=api_key,
            base_url=base_url,
            timeout=30,
            http_client=transport,
        )
        try:
            response = fallback.chat.completions.create(**request)
        except Exception as fallback_exc:
            print(f"TLS12_ERROR_TYPE={type(fallback_exc).__name__}")
            print(f"TLS12_STATUS={getattr(fallback_exc, 'status_code', '')}")
            print(f"TLS12_ERROR={fallback_exc}")
            raise SystemExit(1)
        finally:
            fallback.close()
    print(f"RESPONSE={response.choices[0].message.content}")
    usage = getattr(response, "usage", None)
    if usage is not None:
        print(f"TOTAL_TOKENS={getattr(usage, 'total_tokens', '')}")


if __name__ == "__main__":
    main()
