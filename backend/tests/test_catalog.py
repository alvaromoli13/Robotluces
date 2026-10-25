from types import SimpleNamespace

import pytest

from smartseed_robot.catalog import ModelCatalog, resolve_spec


def files(*names):
    return [SimpleNamespace(rfilename=n) for n in names]


def ckpt(step):
    return [f"checkpoints/{step}/pretrained_model/{n}" for n in ("config.json", "model.safetensors")]


class FakeApi:
    def __init__(self, repos, fail=False):
        self.repos, self.fail, self.listed, self.infos = repos, fail, [], []

    def list_models(self, **kwargs):
        self.listed.append(kwargs)
        if self.fail:
            raise OSError("offline")
        return [SimpleNamespace(id=repo) for repo in self.repos]

    def model_info(self, repo, **kwargs):
        self.infos.append(repo)
        return SimpleNamespace(siblings=files(*self.repos[repo]))


REPOS = {
    "RafaelJaime/act-smartseed-d1-c100": ["model.safetensors", "config.json", *ckpt("020000"), *ckpt("010000")],
    "RafaelJaime/act-smartseed-grasp-merged": ["model.safetensors", "config.json"],
}


def test_catalog_lists_models_with_sorted_checkpoints():
    api = FakeApi(REPOS)
    models, offline = ModelCatalog(api=api).models()
    assert offline is False
    assert api.listed == [{"author": "RafaelJaime", "search": "act-smartseed"}]
    assert models == [
        {"repo": "RafaelJaime/act-smartseed-d1-c100", "checkpoints": ["010000", "020000"]},
        {"repo": "RafaelJaime/act-smartseed-grasp-merged", "checkpoints": []}]


def test_a_checkpoint_without_weights_is_not_offered():
    repos = {"u/act-smartseed-x": ["checkpoints/010000/pretrained_model/config.json", *ckpt("020000")]}
    models, _ = ModelCatalog(api=FakeApi(repos)).models()
    assert models[0]["checkpoints"] == ["020000"]


def test_catalog_is_cached_until_the_ttl_expires():
    api, now = FakeApi(REPOS), [0.0]
    catalog = ModelCatalog(api=api, ttl_s=60, clock=lambda: now[0])
    catalog.models()
    now[0] = 59
    catalog.models()
    assert len(api.listed) == 1
    now[0] = 61
    catalog.models()
    assert len(api.listed) == 2


def test_offline_without_cache_is_empty_and_retried_only_after_the_backoff():
    api, now = FakeApi(REPOS, fail=True), [0.0]
    catalog = ModelCatalog(api=api, retry_s=30, clock=lambda: now[0])
    assert catalog.models() == ([], True)
    now[0] = 10
    assert catalog.models() == ([], True)
    assert len(api.listed) == 1
    now[0] = 31
    api.fail = False
    models, offline = catalog.models()
    assert offline is False and len(models) == 2


def test_offline_after_a_success_serves_the_stale_catalog():
    api, now = FakeApi(REPOS), [0.0]
    catalog = ModelCatalog(api=api, ttl_s=60, clock=lambda: now[0])
    fresh, _ = catalog.models()
    api.fail, now[0] = True, 100
    assert catalog.models() == (fresh, True)


def test_resolve_final_is_the_repo_itself_and_downloads_nothing():
    calls = []
    assert resolve_spec("u/m", None, downloader=lambda **kw: calls.append(kw)) == "u/m"
    assert calls == []


def test_resolve_checkpoint_downloads_only_its_subfolder(tmp_path):
    calls = []

    def downloader(**kwargs):
        calls.append(kwargs)
        (tmp_path / "checkpoints/020000/pretrained_model").mkdir(parents=True)
        return str(tmp_path)

    spec = resolve_spec("u/m", "020000", downloader=downloader)
    assert calls == [{"repo_id": "u/m", "allow_patterns": ["checkpoints/020000/pretrained_model/*"]}]
    assert spec == str(tmp_path / "checkpoints/020000/pretrained_model")


def test_resolve_fails_when_the_checkpoint_is_not_in_the_snapshot(tmp_path):
    with pytest.raises(FileNotFoundError, match="020000"):
        resolve_spec("u/m", "020000", downloader=lambda **kw: str(tmp_path))
