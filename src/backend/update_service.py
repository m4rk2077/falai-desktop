"""Update checker using GitHub Releases.

Beta approach (Option A):
- Check GitHub Releases for a newer version.
- If newer: notify user and open browser to download page/asset.

Security notes:
- We do not download/execute binaries automatically.
- We only open a URL in the user's default browser.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Dict, Optional, Tuple

import requests


_VERSION_RE = re.compile(r"(\d+(?:\.\d+)*)")


def _parse_version_tuple(value: str) -> Tuple[int, ...]:
    s = str(value or "").strip()
    m = _VERSION_RE.search(s)
    if not m:
        return tuple()
    parts = m.group(1).split(".")
    out = []
    for p in parts:
        try:
            out.append(int(p))
        except Exception:
            out.append(0)
    return tuple(out)


def is_newer_version(latest: str, current: str) -> bool:
    lt = _parse_version_tuple(latest)
    ct = _parse_version_tuple(current)
    if not lt or not ct:
        return False
    # Compare with padding to same length.
    n = max(len(lt), len(ct))
    lt2 = lt + (0,) * (n - len(lt))
    ct2 = ct + (0,) * (n - len(ct))
    return lt2 > ct2


@dataclass
class UpdateInfo:
    current_version: str
    latest_version: str
    available: bool
    download_url: str
    release_url: str
    asset_name: str = ""
    asset_id: str = ""
    asset_size: int = 0
    asset_sha256: str = ""
    published_at: str = ""
    notes: str = ""


class GitHubReleasesUpdateService:
    def __init__(self, *, owner: str, repo: str, timeout_seconds: int = 6):
        self.owner = str(owner or "").strip()
        self.repo = str(repo or "").strip()
        self.timeout_seconds = int(timeout_seconds or 6)

    def check_latest(self, *, current_version: str) -> Optional[UpdateInfo]:
        if not self.owner or not self.repo:
            return None

        headers = {
            "Accept": "application/vnd.github+json",
            "User-Agent": "FALAI-App",
        }

        # GitHub behaviour note:
        # - `/releases/latest` returns the latest *non-prerelease* published release.
        # - If the repo has only pre-releases, GitHub may return 404.
        # For beta flows we want a best-effort fallback to `/releases`.
        url_latest = f"https://api.github.com/repos/{self.owner}/{self.repo}/releases/latest"
        resp = requests.get(url_latest, headers=headers, timeout=self.timeout_seconds)
        if resp.status_code == 404:
            url_list = f"https://api.github.com/repos/{self.owner}/{self.repo}/releases"
            resp = requests.get(url_list, headers=headers, timeout=self.timeout_seconds, params={"per_page": 10})

        resp.raise_for_status()
        data = resp.json()

        if isinstance(data, list):
            # Pick the most recent published release.
            releases = [r for r in data if isinstance(r, dict) and not bool(r.get("draft"))]
            if not releases:
                return None
            stable = [r for r in releases if not bool(r.get("prerelease"))]
            data = stable[0] if stable else releases[0]

        if not isinstance(data, dict):
            return None

        tag = str(data.get("tag_name") or "").strip()
        html_url = str(data.get("html_url") or "").strip()
        published_at = str(data.get("published_at") or "").strip()
        body = str(data.get("body") or "").strip()

        # Pick the best asset:
        # Prefer something like "FALAI-Setup.exe" or any "*.exe".
        download_url = ""
        asset_name = ""
        asset_id = ""
        asset_size = 0
        asset_sha256 = ""
        assets = data.get("assets") or []
        if isinstance(assets, list):
            exe_assets = []
            setup_assets = []
            for a in assets:
                if not isinstance(a, dict):
                    continue
                name = str(a.get("name") or "").lower()
                bdu = str(a.get("browser_download_url") or "").strip()
                if not bdu:
                    continue
                if name.endswith(".exe"):
                    digest = str(a.get("digest") or "").strip().lower()
                    sha = ""
                    if digest.startswith("sha256:"):
                        maybe = digest.split(":", 1)[1].strip()
                        if re.fullmatch(r"[0-9a-f]{64}", maybe):
                            sha = maybe
                    asset = {
                        "name": str(a.get("name") or "").strip(),
                        "download_url": bdu,
                        "id": str(a.get("id") or "").strip(),
                        "size": int(a.get("size") or 0),
                        "sha256": sha,
                    }
                    exe_assets.append(asset)
                    if "setup" in name or "installer" in name:
                        setup_assets.append(asset)
            chosen = setup_assets[0] if setup_assets else (exe_assets[0] if exe_assets else None)
            if chosen:
                download_url = chosen.get("download_url") or ""
                asset_name = chosen.get("name") or ""
                asset_id = chosen.get("id") or ""
                asset_size = int(chosen.get("size") or 0)
                asset_sha256 = chosen.get("sha256") or ""

        latest_version = tag or ""
        available = bool(latest_version and is_newer_version(latest_version, current_version))

        return UpdateInfo(
            current_version=str(current_version or ""),
            latest_version=str(latest_version or ""),
            available=available,
            download_url=download_url,
            release_url=html_url,
            asset_name=asset_name,
            asset_id=asset_id,
            asset_size=asset_size,
            asset_sha256=asset_sha256,
            published_at=published_at,
            notes=body,
        )
