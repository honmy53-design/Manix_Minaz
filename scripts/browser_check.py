"""Optional UI smoke test; routes browser traffic to TestClient, no public server."""

import json
import io
import time
import zipfile
import tempfile
from pathlib import Path
from urllib.parse import urlsplit

from fastapi.testclient import TestClient
from playwright.sync_api import expect, sync_playwright

from panel.auth import totp
from panel.config import Settings
from panel.main import create_app

ROOT = Path(__file__).resolve().parent.parent


def run():
    with tempfile.TemporaryDirectory() as temporary:
        settings = Settings(Path(temporary) / "data", "admin", "browser-test-only-password")
        with TestClient(create_app(settings), base_url="https://manix.test") as client, sync_playwright() as p:
            browser = p.chromium.launch()
            context = browser.new_context(viewport={"width": 1440, "height": 1080}, locale="fa-IR")
            context.add_init_script("localStorage.setItem('manix-theme','dark')")
            page = context.new_page()
            errors = []
            page.on("pageerror", lambda error: errors.append(str(error)))
            page.on(
                "console",
                lambda message: errors.append(message.text) if message.type == "error" and "status of 401" not in message.text else None,
            )

            def route_request(route):
                req = route.request
                path = urlsplit(req.url).path
                query = urlsplit(req.url).query
                if path == "/api/versions":
                    route.fulfill(
                        status=200,
                        content_type="application/json",
                        body=json.dumps({"versions": [{"id": "26.3"}, {"id": "1.21.1"}, {"id": "1.20.1"}]}),
                    )
                    return
                headers = {k: v for k, v in req.headers.items() if k not in {"content-length", "accept-encoding"}}
                response = client.request(req.method, path + ("?" + query if query else ""), content=req.post_data_buffer, headers=headers)
                route.fulfill(status=response.status_code, headers=dict(response.headers), body=response.content)

            context.route("**/*", route_request)
            page.goto("https://manix.test", wait_until="networkidle")
            expect(page.locator("#loginScreen")).to_be_visible()
            page.locator("#loginPassword").fill("browser-test-only-password")
            page.locator("#loginForm button[type=submit]").click()
            expect(page.locator("#app")).to_be_visible()
            expect(page.locator("#setupNotice")).to_be_visible()
            page.wait_for_timeout(300)
            screenshot = ROOT / "docs/screenshots"
            screenshot.mkdir(parents=True, exist_ok=True)
            page.screenshot(path=str(screenshot / "dashboard.png"), full_page=True)

            page.locator('[data-page="files"]').click()
            page.locator("#newFile").click()
            page.locator('#promptFields input[name="name"]').fill("notes.txt")
            page.locator("#promptSubmit").click()
            expect(page.locator("#editorDialog")).to_be_visible()
            page.locator("#editorText").fill("hello Minecraft — سلام")
            page.locator("#editorSave").click()
            expect(page.locator("#fileRows")).to_contain_text("notes.txt")
            page.locator("#editorClose").click()
            expect(page.locator("#editorDialog")).not_to_be_visible()

            page.locator('[data-page="settings"]').click()
            page.locator('#configForm [name="server_name"]').fill("سرور آزمایشی مانیکس")
            page.locator("#configForm button[type=submit]").click()
            expect(page.locator("#configForm button[type=submit]")).to_be_enabled()
            expect(page.locator('#configForm [name="server_name"]')).to_have_value("سرور آزمایشی مانیکس")
            page.locator('#domainForm [name="game_domain"]').fill("play.example.com")
            page.locator('#domainForm [name="proxy_host"]').fill("example.proxy.rlwy.net")
            page.locator('#domainForm [name="proxy_port"]').fill("12345")
            page.locator("#domainForm button[type=submit]").click()
            expect(page.locator("#dnsRecords")).to_contain_text("_minecraft._tcp.play.example.com")

            page.locator('[data-page="versions"]').click()
            expect(page.locator("#versionSelect")).to_have_value("1.21.1")
            expect(page.locator("#installVersion")).to_be_enabled()
            page.locator('[data-page="overview"]').click()
            expect(page.locator("#serverName")).to_have_text("سرور آزمایشی مانیکس")
            page.screenshot(path=str(screenshot / "dashboard.png"), full_page=True)

            for name in ["addons", "players", "backups", "console", "guide", "worlds", "packs", "schedules", "account"]:
                page.locator(f'[data-page="{name}"]').click()
                expect(page.locator(f'[data-section="{name}"]')).to_be_visible()
            page.locator('[data-page="backups"]').click()
            page.locator("#createBackup").click()
            expect(page.locator("#jobDownload")).to_be_visible(timeout=15000)
            expect(page.locator("#backupRows")).to_contain_text("manual-")

            # مانیکس extensions are exercised against real HTTP handlers, not placeholder APIs.
            page.locator('[data-page="files"]').click()
            page.locator("#newFolder").click()
            page.locator('#promptFields input[name="name"]').fill("copies")
            page.locator("#promptSubmit").click()
            page.get_by_label("انتخاب notes.txt", exact=True).check()
            page.locator("#copySelected").click()
            page.locator('#promptFields input[name="destination"]').fill("copies")
            page.locator("#promptSubmit").click()
            expect(page.locator("#jobMessage")).to_contain_text("عملیات گروهی", timeout=15000)
            assert (settings.server_dir / "copies/notes.txt").read_text() == "hello Minecraft — سلام"
            page.locator("#fileSearch").fill("notes")
            expect(page.locator("#fileRows tr")).to_have_count(1)
            page.locator("#fileSearch").fill("")

            page.locator('[data-page="worlds"]').click()
            page.locator('#worldCreateForm [name="name"]').fill("manix-fresh")
            page.locator('#worldCreateForm button[type="submit"]').click()
            expect(page.locator("#worldRows")).to_contain_text("manix-fresh")
            page.get_by_label("فعال کردن دنیا", exact=True).click()
            page.locator("#promptSubmit").click()
            expect(page.locator("#activeWorld")).to_contain_text("manix-fresh")
            world_data = io.BytesIO()
            with zipfile.ZipFile(world_data, "w") as archive:
                archive.writestr("level.dat", b"synthetic-test-save-not-real-NBT")
            page.locator('#worldImportForm [name="name"]').fill("manix-imported")
            page.locator('#worldImportForm [name="file"]').set_input_files(
                {"name": "save.zip", "mimeType": "application/zip", "buffer": world_data.getvalue()}
            )
            page.locator('#worldImportForm button[type="submit"]').click()
            expect(page.locator("#worldRows")).to_contain_text("manix-imported", timeout=15000)

            page.locator('[data-page="packs"]').click()
            pack_data = io.BytesIO()
            with zipfile.ZipFile(pack_data, "w") as archive:
                archive.writestr("pack.mcmeta", json.dumps({"pack": {"pack_format": 34, "description": "Manix QA"}}))
            page.locator("#packUploadInput").set_input_files(
                {"name": "manix-pack.zip", "mimeType": "application/zip", "buffer": pack_data.getvalue()}
            )
            expect(page.locator("#packRows")).to_contain_text("manix-pack.zip")
            pack_id = page.locator("#packSelect option").nth(1).get_attribute("value")
            page.locator("#packSelect").select_option(pack_id)
            page.locator('#packActivateForm [name="required"]').check()
            page.locator('#packActivateForm button[type="submit"]').click()
            expect(page.locator("#packRows .tag-enabled")).to_have_text("فعال")
            assert client.get("/packs/" + pack_id + ".zip").content == pack_data.getvalue()

            page.locator('[data-page="schedules"]').click()
            page.locator('#taskForm [name="name"]').fill("مانیکس روزانه")
            page.locator("#taskAction").select_option("backup")
            page.locator('#taskForm button[type="submit"]').click()
            expect(page.locator("#taskRows")).to_contain_text("مانیکس روزانه")
            page.get_by_label("ویرایش Task", exact=True).click()
            page.locator('#taskForm [name="name"]').fill("مانیکس هفتگی")
            page.locator("#taskMode").select_option("weekly")
            page.locator('#taskForm button[type="submit"]').click()
            expect(page.locator("#taskRows")).to_contain_text("مانیکس هفتگی")
            page.get_by_label("غیرفعال کردن Task", exact=True).click()
            expect(page.locator("#taskRows .tag-disabled")).to_have_text("غیرفعال")

            page.locator('[data-page="account"]').click()
            page.locator('#profileForm [name="display_name"]').fill("مالک مانیکس")
            page.locator('#profileForm [name="email"]').fill("owner@example.com")
            page.locator('#profileForm button[type="submit"]').click()
            expect(page.locator('#profileForm button[type="submit"]')).to_be_enabled()
            page.locator('#keyForm [name="name"]').fill("Manix read-only")
            page.locator('#keyForm [name="password"]').fill("browser-test-only-password")
            page.locator('#keyForm button[type="submit"]').click()
            expect(page.locator("#secretDialog")).to_be_visible()
            raw_key = page.locator("#secretValue").input_value()
            assert raw_key.startswith("manix_")
            assert client.get("/api/status", headers={"Authorization": "Bearer " + raw_key}).status_code == 200
            page.locator("#acknowledgeSecret").click()
            expect(page.locator("#secretValue")).to_have_value("")
            page.locator("#enableFactor").click()
            page.locator('#promptFields [name="password"]').fill("browser-test-only-password")
            page.locator("#promptSubmit").click()
            expect(page.locator("#secretDialog")).to_be_visible()
            secret = page.locator("#secretValue").input_value().splitlines()[1]
            page.locator("#acknowledgeSecret").click()
            page.locator('#promptFields [name="code"]').fill(totp(secret, int(time.time() // 30)))
            page.locator("#promptSubmit").click()
            expect(page.locator("#secretTitle")).to_have_text("کدهای بازیابی مانیکس")
            recoveries = page.locator("#secretValue").input_value().splitlines()
            assert len(recoveries) == 8
            page.locator("#acknowledgeSecret").click()
            expect(page.locator("#factorStatus")).to_have_text("۲FA فعال")
            page.locator('#passwordForm [name="password"]').fill("browser-test-only-password")
            page.locator('#passwordForm [name="new_password"]').fill("new-browser-test-password")
            page.locator('#passwordForm [name="confirm"]').fill("new-browser-test-password")
            page.locator('#passwordForm button[type="submit"]').click()
            page.locator("#promptSubmit").click()
            expect(page.locator("#loginScreen")).to_be_visible()
            page.locator("#loginPassword").fill("new-browser-test-password")
            page.locator("#loginOtp").fill(recoveries[0])
            page.locator('#loginForm button[type="submit"]').click()
            expect(page.locator("#app")).to_be_visible()
            assert client.get("/api/status", headers={"Authorization": "Bearer " + raw_key}).status_code == 401
            expect(page.locator("#secretValue")).to_have_value("")

            # Screenshots are honest test data. No fabricated running game or provider nodes.
            page.locator('[data-page="overview"]').click()
            page.evaluate("document.querySelector('#toasts').replaceChildren();scrollTo(0,0)")
            page.wait_for_timeout(350)
            page.screenshot(path=str(screenshot / "dashboard.png"), full_page=True)
            page.locator("#themeToggle").click()
            expect(page.locator("html")).to_have_attribute("data-theme", "light")
            page.screenshot(path=str(screenshot / "dashboard-light.png"), full_page=True)
            page.locator("#themeToggle").click()
            page.locator('[data-page="schedules"]').click()
            page.evaluate("scrollTo(0,0)")
            page.screenshot(path=str(screenshot / "schedules.png"), full_page=True)
            page.set_viewport_size({"width": 390, "height": 844})
            page.locator("#menuToggle").click()
            page.locator('[data-page="overview"]').click()
            expect(page.locator('[data-section="overview"]')).to_be_visible()
            page.wait_for_timeout(350)
            page.evaluate("document.querySelector('#toasts').replaceChildren();scrollTo(0,0)")
            assert page.evaluate("document.documentElement.scrollWidth <= innerWidth + 2")
            page.screenshot(path=str(screenshot / "mobile.png"), full_page=True)
            for name in ["worlds", "packs", "schedules", "account"]:
                page.locator("#menuToggle").click()
                page.locator(f'[data-page="{name}"]').click()
                expect(page.locator(f'[data-section="{name}"]')).to_be_visible()
                page.wait_for_timeout(230)
                assert page.evaluate("document.documentElement.scrollWidth <= innerWidth + 2"), name
            page.set_viewport_size({"width": 820, "height": 1024})
            for name in ["overview", "files", "settings", "worlds", "packs", "schedules", "account"]:
                page.locator(f'[data-page="{name}"]').click()
                expect(page.locator(f'[data-section="{name}"]')).to_be_visible()
                assert page.evaluate("document.documentElement.scrollWidth <= innerWidth + 2"), "tablet " + name
            if errors:
                raise AssertionError("Browser errors: " + "\n".join(errors))
            browser.close()
            print(
                "Manix UI OK: login/MFA, password/API keys, files/bulk copy/search, worlds, packs, schedules, themes, mobile/tablet, CSP."
            )


if __name__ == "__main__":
    run()
