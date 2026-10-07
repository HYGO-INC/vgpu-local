"""Run actual Chrome against a controlled engine; never attach a user's browser."""
import argparse
import json
from pathlib import Path
import sys
import tempfile

from playwright.sync_api import sync_playwright, Error as BrowserError

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tests"))
from runtime_fixture import EngineFixture, service, setup, wait_for


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--chrome", type=Path, required=True, help="Existing Chrome executable; no browser download")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="vgpu-browser-") as temporary, EngineFixture() as engine:
        path = Path(temporary) / "runtime"
        store = setup(path, engine)
        with service(path) as (info, process), sync_playwright() as playwright:
            launch = dict(executable_path=str(args.chrome.resolve()), headless=True)
            browser = playwright.chromium.launch(**launch)
            version = browser.version
            try:
                page = browser.new_page(viewport={"width": 1120, "height": 900})
                page.goto(info["origin"]+"/#"+info["token"])
                page.get_by_role("button", name="Start job", exact=True).click()
                page.locator('article[data-state="running"]').wait_for()
                execution = page.locator('article').get_attribute('data-execution-id')
                engine_id = store.job(execution)["engine_job_id"]
            finally:
                browser.close()  # Every tab, context and the browser process is gone.
            assert process.poll() is None
            assert store.job(execution)["state"] == "running"
            assert engine.finish(engine_id)
            wait_for(lambda: store.job(execution)["state"] == "succeeded")
            browser = playwright.chromium.launch(**launch)
            try:
                page = browser.new_page(viewport={"width": 1120, "height": 900})
                page.goto(info["origin"]+"/#"+info["token"])
                card = page.locator(f'article[data-execution-id="{execution}"][data-state="succeeded"]')
                card.wait_for()
                card.get_by_text("Result metadata").click()
                assert "fixture result" in card.inner_text()
                assert engine.posts == 1
                page.screenshot(path=str(args.output / "local-console.png"), full_page=True)

                # Hosted-page qualification: deny loopback access explicitly. The
                # fixture page uses only its own HTTPS origin, just like the
                # accepted hosted transport design; production UI is separate.
                remote = browser.new_context()
                remote_page = remote.new_page()
                cdp = remote.new_cdp_session(remote_page)
                context_id = cdp.send("Target.getTargetInfo")["targetInfo"]["browserContextId"]
                hosted = "https://vgpu-browser.test"
                permissions = []
                for name in ("local-network-access", "loopback-network"):
                    try:
                        cdp.send("Browser.setPermission", {"permission": {"name": name}, "setting": "denied", "origin": hosted,
                                                         "browserContextId": context_id})
                        permissions.append(name)
                    except BrowserError:
                        pass  # Names differ between Chrome releases; require a supported one below.
                assert permissions, "Chrome does not expose a supported loopback permission"
                requests = []
                remote_page.on("request", lambda request: requests.append(request.url))
                def route(request):
                    if request.request.url.endswith("/api/executions"):
                        request.fulfill(json=[store.report(store.job(execution))])
                    else:
                        request.fulfill(content_type="text/html", body="<title>Hosted management fixture</title><div id='result'></div><script>fetch('/api/executions').then(r=>r.json()).then(rows=>document.getElementById('result').textContent=rows[0].state)</script>")
                remote.route(hosted+"/**", route)
                remote_page.goto(hosted+"/")
                remote_page.get_by_text("succeeded", exact=True).wait_for()
                denied = remote_page.evaluate("async names => await Promise.all(names.map(async name => (await navigator.permissions.query({name})).state))", permissions)
                assert set(denied) == {"denied"}
                assert len(requests) == 2 and all(url.startswith(hosted+"/") for url in requests)
                remote.close()
                evidence = {"chrome": version, "engine": "controlled ComfyUI wire fixture; no GPU execution",
                    "all_browser_processes_closed_while_running": True, "same_execution_and_result_after_reopen": True,
                    "engine_submissions": engine.posts, "listener_host": info["origin"].split(":")[1].lstrip("/"),
                    "hosted_fixture_permissions_denied": permissions, "hosted_fixture_requests": len(requests),
                    "hosted_fixture_loopback_requests": 0, "production_hosted_ui_qualified": False}
                (args.output / "browser.json").write_text(json.dumps(evidence, indent=2)+"\n", encoding="utf-8")
                print(json.dumps(evidence, indent=2))
            finally:
                browser.close()


if __name__ == "__main__": main()
