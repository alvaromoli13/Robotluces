from __future__ import annotations

import re
import threading
import time
from pathlib import Path
from typing import Callable

AUTHOR = "RafaelJaime"
SEARCH = "act-smartseed"
_CHECKPOINT_WEIGHTS = re.compile(r"^checkpoints/([^/]+)/pretrained_model/model\.safetensors$")


def _snapshot_download(**kwargs) -> str:
    from huggingface_hub import snapshot_download

    return snapshot_download(**kwargs)


def resolve_spec(repo: str, checkpoint: str | None, downloader: Callable[..., str] = _snapshot_download) -> str:
    """What `from_pretrained` takes. The final model is the repo itself. lerobot cannot load a Hub subfolder, so an
    intermediate checkpoint is downloaded alone and its local `pretrained_model` directory is the spec."""
    if checkpoint is None:
        return repo
    root = downloader(repo_id=repo, allow_patterns=[f"checkpoints/{checkpoint}/pretrained_model/*"])
    path = Path(root) / "checkpoints" / checkpoint / "pretrained_model"
    if not path.is_dir():
        raise FileNotFoundError(f"checkpoint {checkpoint} of {repo} is not on the Hub")
    return str(path)


class ModelCatalog:
    """ACT models published on the Hub by `author` (`checkpoints/<step>/pretrained_model/` folders), cached.
    Offline it serves the last catalog it saw, or nothing, and retries only after `retry_s`."""

    def __init__(self, api=None, author: str = AUTHOR, search: str = SEARCH, ttl_s: float = 300.0,
                 retry_s: float = 30.0, clock: Callable[[], float] = time.monotonic):
        self._api, self.author, self.search = api, author, search
        self._ttl, self._retry, self._clock = ttl_s, retry_s, clock
        self._models: list[dict] | None = None
        self._expires, self._offline = 0.0, False
        self._lock = threading.Lock()

    def models(self) -> tuple[list[dict], bool]:
        """(`[{"repo", "checkpoints": [step, ...]}]`, offline)"""
        with self._lock:
            if self._clock() >= self._expires:
                self._refresh()
            return list(self._models or []), self._offline

    def _refresh(self) -> None:
        try:
            self._models, self._offline = self._fetch(), False
            self._expires = self._clock() + self._ttl
        except Exception:  # any Hub or network failure: keep serving what we have
            self._offline = True
            self._expires = self._clock() + self._retry

    def _fetch(self) -> list[dict]:
        api = self._api
        if api is None:
            from huggingface_hub import HfApi

            api = self._api = HfApi()
        models = []
        for info in api.list_models(author=self.author, search=self.search):
            files = (s.rfilename for s in api.model_info(info.id).siblings or [])
            steps = sorted(m.group(1) for f in files if (m := _CHECKPOINT_WEIGHTS.match(f)))
            models.append({"repo": info.id, "checkpoints": steps})
        return sorted(models, key=lambda m: m["repo"])
