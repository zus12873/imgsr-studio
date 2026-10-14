import pytest


@pytest.fixture
def static_dir(tmp_path):
    root = tmp_path / "dist"
    (root / "assets").mkdir(parents=True)
    (root / "index.html").write_text("<div id=root>spa-shell</div>")
    (root / "assets" / "app.js").write_text("console.log('app')")
    (root / "favicon.svg").write_text("<svg/>")
    return root


def test_serves_index_and_client_routes(make_api, static_dir):
    api = make_api(static_dir=static_dir)
    for path in ("/", "/tasks/abc", "/guest"):
        r = api.client.get(path)
        assert r.status_code == 200 and "spa-shell" in r.text
        assert r.headers["cache-control"] == "no-cache"


def test_serves_assets_and_root_files(make_api, static_dir):
    api = make_api(static_dir=static_dir)
    assert "console.log" in api.client.get("/assets/app.js").text
    assert api.client.get("/favicon.svg").text == "<svg/>"


def test_unknown_api_paths_stay_json_404(make_api, static_dir):
    api = make_api(static_dir=static_dir)
    r = api.client.get("/api/nope")
    assert r.status_code == 404 and r.json()["detail"] == "Not Found"


def test_path_traversal_returns_index_not_file(make_api, static_dir):
    (static_dir.parent / "secret.txt").write_text("top-secret")
    api = make_api(static_dir=static_dir)
    assert "top-secret" not in api.client.get("/..%2Fsecret.txt").text


def test_no_static_dir_means_no_spa(make_api, tmp_path):
    api = make_api(static_dir=tmp_path / "missing")
    assert api.client.get("/").status_code == 404
