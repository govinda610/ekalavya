#!/usr/bin/env python
"""Capture the practice-arena interactive states live, by driving the app's own JS.
Produces desktop shots of: streaming+tool-trace, run output, bash-approval,
death/anti-cheat overlay, AI-assistant panel, chats drawer.
"""
from playwright.sync_api import sync_playwright

BASE = "http://127.0.0.1:4646"
OUT = __file__.rsplit("/", 1)[0]


def page(ctx):
    pg = ctx.new_page()
    pg.route("**/api/stream", lambda r: r.abort())   # we build the transcript manually
    pg.goto(BASE + "/", wait_until="domcontentloaded")
    pg.wait_for_timeout(1200)
    # clear the aborted-kickoff artifact + welcome so each state starts from a clean log
    pg.evaluate("() => { const l=document.getElementById('log'); if(l) l.innerHTML=''; }")
    return pg


def shot(pg, name):
    pg.wait_for_timeout(500)
    pg.screenshot(path=f"{OUT}/{name}.png", full_page=False)
    print("shot", name)


with sync_playwright() as p:
    b = p.chromium.launch()

    # 1 — streaming + tool-trace + run output, all in one transcript
    ctx = b.new_context(viewport={"width": 1440, "height": 900}, device_scale_factor=2)
    pg = page(ctx)
    pg.evaluate(r"""() => {
      addMsg('you', renderMd('How do I invert a binary tree in place? Here is my attempt.'));
      const ui = addAiMsg(); ui.m.style.display='';
      ui.trace.style.display='block';
      traceLine(ui.tb,'call','→ Running a command'); ui.steps++;
      traceLine(ui.tb,'res','✓ Running a command');
      traceLine(ui.tb,'call','→ Reading the docs'); ui.steps++;
      traceLine(ui.tb,'res','✓ Reading the docs');
      ui.sum.textContent = ui.steps+' steps · tap to view';
      ui.buf = "Good instinct — you *recursed*, which is exactly right. Invert by swapping the children, then recursing into each side:\n\n```python\ndef invert(node):\n    if not node:\n        return None\n    node.left, node.right = invert(node.right), invert(node.left)\n    return node\n```\n\nYour version mutated a copy instead of the node in place. One question before you run it: **what is the base case, and why can't you skip it?**";
      finalizeMsg(ui);
      const box = addRunOut('running solution.py');
      renderRunOut(box, {ok:true, exit_code:0, seconds:0.08, stdout:'[4, 7, 2, 9, 6, 3, 1]\ninverted OK\n', stderr:''});
    }""")
    shot(pg, "state_stream_trace")
    ctx.close()

    # 2 — bash-approval card
    ctx = b.new_context(viewport={"width": 1440, "height": 900}, device_scale_factor=2)
    pg = page(ctx)
    pg.evaluate(r"""() => {
      addMsg('you', renderMd('Set up the project and run the tests.'));
      const ui = addAiMsg(); ui.m.style.display='';
      ui.buf = "I'll install the dependencies and run the suite. This touches your shell, so approve it first:";
      ui.reply.classList.remove('typing'); ui.reply.innerHTML = renderMd(ui.buf);
      ui.trace.style.display='block';
      traceLine(ui.tb,'call','⏸ awaiting approval — uv run pytest -q');
      const card = el('approve');
      card.innerHTML='<div class="ah">⏻ RUN THIS COMMAND?</div><div class="acmd"></div>'+
        '<div class="awhy"></div><div class="abtns">'+
        '<button class="ok">Approve &amp; run</button><button class="no">Reject</button></div>';
      card.querySelector('.acmd').textContent='uv run pytest -q';
      card.querySelector('.awhy').textContent='Runs the test suite so I can see which cases still fail before we fix them.';
      ui.m.insertBefore(card, ui.reply); scroll();
    }""")
    shot(pg, "state_approval")
    ctx.close()

    # 3 — death / anti-cheat overlay
    ctx = b.new_context(viewport={"width": 1440, "height": 900}, device_scale_factor=2)
    pg = page(ctx)
    pg.evaluate(r"""() => {
      addMsg('you', renderMd('def two_sum(nums, target): ...'));
      document.getElementById('deathsub').innerHTML =
        'You pasted a whole solution instead of earning it. The round is <b>lost</b> — but the string is still in your hand. Type it yourself to reclaim your merit.';
      document.getElementById('death').classList.add('on');
    }""")
    shot(pg, "state_death")
    ctx.close()

    # 4 — AI-assistant panel (aiinterview mode)
    ctx = b.new_context(viewport={"width": 1440, "height": 900}, device_scale_factor=2)
    pg = page(ctx)
    pg.evaluate(r"""() => {
      document.getElementById('mode').value='aiinterview'; mode='aiinterview'; applyMode();
      addMsg('ai', renderMd('This is an **AI-enabled** round — the assistant on the right is allowed, but it is imperfect. Use it, then verify it.'));
      const log = document.getElementById('asslog');
      const q = el('msg you'); q.innerHTML='<div class="who">you</div><div class="body">Is a dict comprehension faster than a loop here?</div>'; log.appendChild(q);
      const a = el('msg ai'); a.innerHTML='<div class="who">assistant</div><div class="body">'+renderMd('Usually yes — a dict comprehension avoids repeated `__setitem__` lookups. But benchmark it: for tiny inputs the difference is noise. Verify with `timeit`.')+'</div>'; log.appendChild(a);
    }""")
    shot(pg, "state_assist")
    ctx.close()

    # 5 — chats drawer open
    ctx = b.new_context(viewport={"width": 1440, "height": 900}, device_scale_factor=2)
    pg = page(ctx)
    pg.evaluate(r"""() => {
      const box=document.getElementById('chatlist'); box.innerHTML='';
      const chats=[['Inverting a binary tree','practice · 2026-07-29 14:02'],
                   ['Mock: system design','mock · 2026-07-28 19:20'],
                   ['SQL window functions','practice · 2026-07-27 09:10'],
                   ['First-time setup','onboard · 2026-07-26 21:44']];
      chats.forEach((c,i)=>{ const it=el('chatitem'); if(i===0) it.classList.add('active');
        const ci=el('ci'), ct=el('ct'), cm=el('cm'); ct.textContent=c[0]; cm.textContent=c[1];
        ci.appendChild(ct); ci.appendChild(cm);
        const ed=document.createElement('button'); ed.className='cedit'; ed.textContent='✎';
        it.appendChild(ci); it.appendChild(ed); box.appendChild(it); });
      document.getElementById('drawer').classList.add('open');
      document.getElementById('drawerscrim').classList.add('open');
    }""")
    shot(pg, "state_drawer")
    ctx.close()

    b.close()
