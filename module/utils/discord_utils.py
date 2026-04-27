# -*- coding: utf-8 -*-
from __future__ import annotations

import os
import time
from typing import List, Tuple, Optional

import requests

Attachment = Tuple[str, bytes, str]  # filename, blob, mimetype


def discord_enabled() -> bool:
    return bool(os.environ.get("DISCORD_WEBHOOK_URL", "").strip())


def post_discord_text(content: str) -> None:
    url = os.environ.get("DISCORD_WEBHOOK_URL", "").strip()
    if not url:
        return

    r = requests.post(url, json={"content": content[:2000]}, timeout=60)
    if r.status_code == 429:
        retry = r.json().get("retry_after", 1)
        time.sleep(float(retry))
        r = requests.post(url, json={"content": content[:2000]}, timeout=60)
    r.raise_for_status()


def post_discord_files(
    *,
    content: str,
    files: List[Attachment],
    max_files_per_message: int = 10,
    sleep_sec: float = 1.0,
) -> None:
    """
    Discord Webhookへ画像を分割投稿。
    1投稿あたり最大10ファイル運用。
    """
    url = os.environ.get("DISCORD_WEBHOOK_URL", "").strip()
    if not url or not files:
        return

    for i in range(0, len(files), max_files_per_message):
        chunk = files[i:i + max_files_per_message]

        multipart = {}
        for idx, (fname, blob, mime) in enumerate(chunk):
            multipart[f"files[{idx}]"] = (fname, blob, mime)

        payload = {
            "content": content[:2000] if i == 0 else f"{content[:1800]}\n（続き {i // max_files_per_message + 1}）"
        }

        r = requests.post(
            url,
            data={"payload_json": __import__("json").dumps(payload, ensure_ascii=False)},
            files=multipart,
            timeout=120,
        )

        if r.status_code == 429:
            retry = r.json().get("retry_after", 1)
            time.sleep(float(retry))
            r = requests.post(
                url,
                data={"payload_json": __import__("json").dumps(payload, ensure_ascii=False)},
                files=multipart,
                timeout=120,
            )

        r.raise_for_status()
        time.sleep(sleep_sec)
