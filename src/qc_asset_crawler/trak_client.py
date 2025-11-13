from __future__ import annotations

from typing import Dict, Optional
from pathlib import Path
import requests
import logging
import os


def get_trak_base_url() -> str:
    return os.environ.get("TRAK_BASE_URL", None).rstrip("/")


def get_trak_api_key() -> str:
    return os.environ.get("TRAK_ASSET_TRACKER_API_KEY", None)


def headers_json() -> Dict[str, str]:
    header = {
        "content-type": "application/json",
        "cache-control": "no-cache",
        "accept": "text/plain",
    }
    if get_trak_api_key():
        header["x-api-key"] = get_trak_api_key()
    return header


def tracker_lookup_asset_by_path(path: Path) -> dict:
    url = f"{get_trak_base_url()}/asset/asset-search"
    body = {
        "searchPage": {"pageSize": 100},
        "assetSearchType": 2,
        "includeCustomer": False,
        "assetPath": path.as_posix(),
        "tagIds": [],
    }
    try:
        r = requests.post(url, json=body, headers=headers_json(), timeout=15)
        logging.debug(r.text)
        if not r.ok:
            status = "unauthorized" if r.status_code in (401, 403) else "error"
            return {"asset_id": None, "status": status, "http_code": r.status_code}
        data = r.json()
        asset_id = (data.get("items") or [{}])[0].get("asset_id") or data.get(
            "asset_id"
        )
        return {"asset_id": asset_id, "status": "ok", "http_code": 200}
    except requests.RequestException:
        return {"asset_id": None, "status": "error", "http_code": None}


def tracker_set_qc(asset_id: Optional[str], payload: dict) -> bool:
    if not asset_id or payload.get("qc_result") == "pending":
        return False
    url = f"{get_trak_base_url()}/assets/{asset_id}/qc"
    try:
        r = requests.post(url, json=payload, headers=headers_json(), timeout=15)
        return bool(r.ok)
    except requests.RequestException:
        return False
