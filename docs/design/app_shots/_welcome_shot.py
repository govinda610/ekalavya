from playwright.sync_api import sync_playwright
OUT="/Users/govindmittal/datascience-setup/eklavya-ai-coding-tutor/docs/design/app_shots"
BASE="http://127.0.0.1:4646"
with sync_playwright() as p:
    b=p.chromium.launch()
    for label,w in (("desktop",1440),("mobile",390)):
        ctx=b.new_context(viewport={"width":w,"height":900},device_scale_factor=2,is_mobile=(label=="mobile"))
        pg=ctx.new_page()
        # HANG the stream (never resolve) so the loading/welcome state stays, no error bubble
        pg.route("**/api/stream", lambda r: None)
        pg.goto(BASE+"/", wait_until="domcontentloaded"); pg.wait_for_timeout(2200)
        of=pg.evaluate("()=>document.documentElement.scrollWidth-window.innerWidth")
        hasErr=pg.evaluate("()=>document.body.innerText.includes('connection error')")
        pg.screenshot(path=f"{OUT}/arena_welcome_{label}.png", full_page=False)
        print(f"arena_welcome_{label} overflow:{of} connection_error_shown:{hasErr}")
        ctx.close()
    b.close()
