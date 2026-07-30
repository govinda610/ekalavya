from playwright.sync_api import sync_playwright
OUT="/Users/govindmittal/datascience-setup/eklavya-ai-coding-tutor/docs/design/app_shots"
BASE="http://127.0.0.1:4646"
with sync_playwright() as p:
    b=p.chromium.launch()
    for label,w in (("desktop",1440),("mobile",390)):
        ctx=b.new_context(viewport={"width":w,"height":900},device_scale_factor=2,is_mobile=(label=="mobile"))
        pg=ctx.new_page()
        pg.route("**/api/stream", lambda r: r.abort())  # skip the kickoff agent call
        pg.goto(BASE+"/", wait_until="domcontentloaded")
        pg.wait_for_timeout(1500)
        # click the Skill Tree tab
        pg.click("button.tab[data-view='tree']")
        pg.wait_for_timeout(2500)  # mermaid render + default-to-first-track
        of=pg.evaluate("()=>document.documentElement.scrollWidth-window.innerWidth")
        pg.screenshot(path=f"{OUT}/tree_{label}.png", full_page=False)
        print(f"tree_{label}  h-overflow:{of}px  filter:", pg.eval_on_selector("#treefilter","e=>e.value"))
        # now the ALL-pillars overview
        pg.select_option("#treefilter", value="__all__")
        pg.wait_for_timeout(2500)
        pg.screenshot(path=f"{OUT}/tree_all_{label}.png", full_page=False)
        of2=pg.evaluate("()=>{const f=document.querySelector('.treeframe');return f?f.scrollWidth-f.clientWidth:0}")
        print(f"tree_all_{label}  frame-scrollWidth-overflow:{of2}px")
        ctx.close()
    b.close()
