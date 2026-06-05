#!/usr/bin/env python3
"""
gc_download_player.py  (AI Detail Edition v2)
=============================================
Downloads GameChanger clips with Claude Vision AI descriptions
baked into filenames and a metadata CSV. Supports multiple teams.

Filename: 2026-02-21_Triple_HardHitToRightCenter_Inn1Bot_Kassidy.mp4

Usage:
    # Single team:
    python3 gc_download_player.py \
        --team-url "https://web.gc.com/teams/TTkhXvh9VmJ1/2024-fall-bananas" \
        --player-id UUID --player-name Kassidy \
        --output ./gc_clips/Kassidy/mp4s

    # Multiple teams (comma-separated):
    python3 gc_download_player.py \
        --team-urls "https://web.gc.com/teams/TTkhXvh9VmJ1/2024-fall-bananas,https://web.gc.com/teams/dDeB8Wx16VhO/2025-spring-hotshots-2k15-cortinas-10u" \
        --player-id UUID --player-name Kassidy \
        --output ./gc_clips/Kassidy/mp4s

    # Skip AI (faster):
        --no-ai
"""

import argparse, asyncio, base64, csv, json, os, re, subprocess
from datetime import datetime
from io import BytesIO
from pathlib import Path
import anthropic, httpx
from PIL import Image
from playwright.async_api import async_playwright

AI_MODEL  = "claude-haiku-4-5-20251001"

AI_PROMPT = """Analyze this youth softball/baseball clip thumbnail.
In 4-6 words describe the play action shown.
Examples: "Hard ground ball to shortstop", "Line drive right center",
"Stealing second base slide", "Strikeout looking", "Bunt toward third"
Reply ONLY with the 4-6 word description."""

def parse_args():
    p = argparse.ArgumentParser()
    p.add_argument("--player-id",   required=True)
    p.add_argument("--player-name", required=True)
    p.add_argument("--output",      default=None)
    p.add_argument("--manifest",    default=None)
    p.add_argument("--team-url",    default=None, help="Single team URL")
    p.add_argument("--team-urls",   default=None, help="Comma-separated team URLs")
    p.add_argument("--no-ai",       action="store_true")
    p.add_argument("--api-key",     default=None)
    p.add_argument("--debug",       action="store_true", help="Dump page selectors for first game")
    return p.parse_args()

def safe(s): return re.sub(r'[^a-zA-Z0-9_\-]','_',str(s)).strip('_')[:50]

def get_date(ts):
    try: return datetime.fromisoformat(ts.replace('Z','+00:00')).strftime('%Y-%m-%d')
    except: return 'unknown'

def make_filename(clip, ginfo, player_name, ai_desc='', team_label=''):
    ts     = clip.get('timestamp','')
    date   = get_date(ts)
    sport  = clip.get('sport_metadata',{})
    inn    = sport.get('inning','')
    half   = sport.get('inning_half','')
    half_s = 'Top' if half=='top' else 'Bot' if half=='bottom' else ''
    inn_s  = f"Inn{inn}{half_s}" if inn else ''
    play   = safe(clip.get('name','clip'))
    ai_p   = safe(ai_desc) if ai_desc else ''
    tl     = safe(team_label) if team_label else ''
    parts  = [p for p in [date, tl, play, ai_p, inn_s, safe(player_name)] if p]
    return '_'.join(parts)+'.mp4'

def analyze_thumbnail(client, thumb_url):
    try:
        r = httpx.get(thumb_url, timeout=10, headers={'Referer':'https://web.gc.com/'})
        if r.status_code != 200: return ''
        img = Image.open(BytesIO(r.content)).convert('RGB')
        img.thumbnail((400,300), Image.LANCZOS)
        buf = BytesIO(); img.save(buf,format='JPEG',quality=80)
        b64 = base64.b64encode(buf.getvalue()).decode()
        resp = client.messages.create(
            model=AI_MODEL, max_tokens=30,
            messages=[{"role":"user","content":[
                {"type":"image","source":{"type":"base64","media_type":"image/jpeg","data":b64}},
                {"type":"text","text":AI_PROMPT}
            ]}]
        )
        return resp.content[0].text.strip().rstrip('.')
    except: return ''

async def scrape_team(page, base_url, player_id, channel_auth, game_info, player_clips, game_ids, debug=False):
    """Scrape one team's games and collect clip metadata + CF cookies."""
    team_label = base_url.rstrip('/').split('/')[-1]  # e.g. "2024-fall-bananas"
    print(f"\n  📋 Team: {team_label}")

    # Fetch schedule
    try:
        await page.goto(f"{base_url}/schedule", wait_until="domcontentloaded", timeout=30000)
    except: pass
    await asyncio.sleep(6)

    local_game_ids = list(dict.fromkeys(
        re.findall(r'/schedule/([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})',
                   await page.content())
    ))
    # Merge without dupes
    for gid in local_game_ids:
        if gid not in game_ids:
            game_ids.append(gid)
    print(f"  Found {len(local_game_ids)} games")

    for i, game_id in enumerate(local_game_ids):
        clips_url = f"{base_url}/schedule/{game_id}/videos/clips?filters.playerIds%5B0%5D={player_id}"
        print(f"  [{i+1:>2}/{len(local_game_ids)}] {game_id[:8]}...", end=" ", flush=True)
        try:
            await page.goto(clips_url, wait_until="domcontentloaded", timeout=20000)
            await asyncio.sleep(3)

            if debug and i == 0:
                testids = await page.evaluate("""() => {
                    const els = document.querySelectorAll('[data-testid]');
                    return [...new Set(Array.from(els).map(e => e.getAttribute('data-testid')))].slice(0,60);
                }""")
                print(f"\n  🔍 data-testid values: {testids}\n")
                # Also dump aria-labels on buttons
                btns = await page.evaluate("""() => {
                    return Array.from(document.querySelectorAll('button')).map(b =>
                        b.getAttribute('aria-label') || b.textContent.trim().slice(0,30)
                    ).filter(Boolean).slice(0,30);
                }""")
                print(f"  🔍 button labels: {btns}\n")

            # Collect clip IDs directly from the page URL pattern or rendered links
            clip_links = await page.evaluate("""() => {
                const links = Array.from(document.querySelectorAll('a[href*="/clips/"]'));
                return links.map(a => a.href).filter(h => h.includes('/clips/'));
            }""")

            if not clip_links:
                # Fallback: check for any video/clip elements
                clip_count = await page.evaluate("""() =>
                    document.querySelectorAll('[data-testid*="clip"], video, [class*="clip"]').length
                """)
                print(f"no clips (elements: {clip_count})")
                continue

            print(f"{len(clip_links)} clip link(s) → navigating...")

            for clip_url in clip_links[:1]:  # Visit first clip to trigger playback-data response
                try:
                    await page.goto(clip_url.split('?')[0], wait_until="domcontentloaded", timeout=15000)
                    await asyncio.sleep(3)
                except: pass

        except Exception as e:
            print(f"error: {str(e)[:60]}")

    return team_label

async def main():
    args = parse_args()
    api_key = args.api_key or os.environ.get('ANTHROPIC_API_KEY')
    if not api_key and not args.no_ai:
        print("⚠ No ANTHROPIC_API_KEY — running with --no-ai"); args.no_ai = True
    ai_client = anthropic.Anthropic(api_key=api_key) if not args.no_ai else None

    # Build team URL list
    team_urls = []
    if args.team_urls:
        team_urls = [u.strip() for u in args.team_urls.split(',') if u.strip()]
    elif args.team_url:
        team_urls = [args.team_url.rstrip('/')]
    else:
        print("❌ Provide --team-url or --team-urls"); return

    player_id   = args.player_id
    player_name = args.player_name
    out_dir     = Path(args.output or f"gc_clips/{safe(player_name)}_{player_id[:8]}/mp4s")
    out_dir.mkdir(parents=True, exist_ok=True)

    print(f"\n{'='*60}")
    print(f"  GC Clips {'+ AI Detail' if not args.no_ai else '(no AI)'}")
    print(f"  Teams: {len(team_urls)}")
    for u in team_urls: print(f"    • {u.split('/teams/')[-1]}")
    print(f"  Player: {player_name} ({player_id[:8]}...)")
    print(f"  Output: {out_dir}\n{'='*60}\n")

    channel_auth = {}; gc_token = [None]; game_info = {}; player_clips = []; game_ids = []

    if args.manifest and Path(args.manifest).exists():
        with open(args.manifest) as f: mdata = json.load(f)
        game_ids = list(dict.fromkeys(
            c['game_id'] for c in mdata.get('clips', [])
            if c.get('game_id') and c['game_id'] != 'unknown'
        ))
        print(f"📋 {len(game_ids)} game IDs from manifest")

    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=False)
        ctx     = await browser.new_context(permissions=["clipboard-read","clipboard-write"])

        def on_request(req):
            tok = req.headers.get('gc-token','')
            if tok and not gc_token[0]:
                gc_token[0] = tok
                print(f"  🔑 gc-token captured")

        async def on_response(resp):
            url = resp.url
            try:
                ct = resp.headers.get('content-type','')
                if 'json' not in ct and 'gc.com' not in ct: return

                if 'standalone-playback-data' in url:
                    body = await resp.json()
                    pb = body.get('playback',{}); vurl = pb.get('url',''); ck = pb.get('cookies',{})
                    m = re.search(r'/376441934742/(\w+)/clips/', vurl)
                    if m and ck:
                        ch = m.group(1)
                        channel_auth[ch] = {'cookies':ck,'url':vurl,'ts':body.get('timestamp','')}
                        print(f"  ✅ CF cookie [{len(channel_auth)}] {body.get('name','')} — {ch}")

                elif 'clips/search' in url or ('clips' in url and 'json' in ct):
                    body = await resp.json()
                    hits = body.get('hits', body.get('clips', body.get('data', [])))
                    if isinstance(hits, list):
                        for hit in hits:
                            pid = (hit.get('player_metadata') or {}).get('player_id','')
                            cid = hit.get('clip_metadata_id','') or hit.get('id','')
                            if pid == player_id and not any(c.get('clip_metadata_id')==cid for c in player_clips):
                                player_clips.append(hit)
                                print(f"  🎬 clip: {hit.get('name','?')} ({cid[:8]}...)")

                elif any(x in url for x in ['game-summaries','game_summaries','events','schedule']):
                    body = await resp.json()
                    items = body if isinstance(body,list) else body.get('data', body.get('game_summaries', body.get('events',[])))
                    if isinstance(items, dict): items = [items]
                    for ev in (items or []):
                        eid = ev.get('id') or ev.get('event_id') or ev.get('game_id')
                        if not eid: continue
                        if str(eid) not in game_ids: game_ids.append(str(eid))
                        home = ev.get('home_team',{}); away = ev.get('away_team',{})
                        hn = home.get('name','') if isinstance(home,dict) else str(home)
                        an = away.get('name','') if isinstance(away,dict) else str(away)
                        opp = ev.get('opponent') or ev.get('opponent_name') or an or hn
                        st = ev.get('start_time') or ev.get('date') or ev.get('scheduled_at','')
                        game_info[str(eid)] = {'opponent':opp,'home_team':hn,'away_team':an,'date':st[:10] if st else ''}
            except: pass

        ctx.on("request", on_request)
        ctx.on("response", on_response)
        page = await ctx.new_page()

        print("⏳ Log in manually — 90 seconds...")
        await page.goto("https://web.gc.com/login", wait_until="domcontentloaded")
        await asyncio.sleep(90)

        for team_url in team_urls:
            await scrape_team(page, team_url, player_id, channel_auth, game_info, player_clips, game_ids, debug=args.debug)

        if browser.is_connected(): await browser.close()

    data_dir = out_dir.parent
    for name, obj in [('cf_cookies.json',channel_auth),('clips.json',player_clips),('game_info.json',game_info)]:
        with open(data_dir/name,'w') as f: json.dump(obj, f, indent=2)

    print(f"\n📊 Channels:{len(channel_auth)} | Clips:{len(player_clips)} | Games:{len(game_ids)}")
    if not channel_auth: print("❌ No CF cookies — playback-data endpoint not triggered"); return
    if not player_clips: print("❌ No clips found for this player"); return

    print(f"\n⬇  {'AI-analyzing thumbnails + d' if not args.no_ai else 'D'}ownloading {len(player_clips)} clips...\n")
    metadata_rows = []; ok = fail = skip = 0

    for clip in player_clips:
        thumb = clip.get('thumbnail_url','')
        m = re.search(r'/376441934742/(\w+)/clips/([\d\-T:.Z]+)\.jpg', thumb)
        if not m: continue
        ch, ts = m.group(1), m.group(2)
        if ch not in channel_auth: fail += 1; continue

        gid = clip.get('event_id') or clip.get('game_id') or ''
        ginfo = game_info.get(gid, {})
        if not ginfo.get('date'): ginfo['date'] = get_date(ts)

        # Derive team label from clip or game info
        team_label = safe(ginfo.get('home_team','') or '')

        ai_desc = ''
        if not args.no_ai and ai_client:
            ai_desc = analyze_thumbnail(ai_client, thumb)

        fname = make_filename(clip, ginfo, player_name, ai_desc, team_label)
        dest  = out_dir / fname
        metadata_rows.append({
            'filename':fname, 'date':ginfo.get('date',''), 'opponent':ginfo.get('opponent',''),
            'play_type':clip.get('name',''), 'ai_description':ai_desc,
            'inning':clip.get('sport_metadata',{}).get('inning',''),
            'inning_half':clip.get('sport_metadata',{}).get('inning_half',''),
            'player':player_name, 'clip_id':clip.get('clip_metadata_id',''),
            'thumbnail_url':thumb, 'channel':ch, 'team':team_label
        })

        if dest.exists(): print(f"  ✓ {fname[:65]}"); skip += 1; continue
        ai_tag = f" [{ai_desc[:30]}]" if ai_desc else ""
        print(f"  ↓ {fname[:55]}{ai_tag}", end=" ... ", flush=True)

        cf  = channel_auth[ch]['cookies']
        cs  = "; ".join(f"{k}={v}" for k,v in cf.items())
        ref = channel_auth[ch]['url']
        ref_ts = channel_auth[ch]['ts']
        m3u8 = ref.replace(ref_ts.replace(':','%3A'), ts.replace(':','%3A')).replace(ref_ts, ts)
        downloaded = False
        for url in [m3u8, thumb.replace('.jpg','.mp4')]:
            cmd = ['ffmpeg','-y','-loglevel','error','-headers',f'Cookie: {cs}\r\n','-i',url,'-c','copy',str(dest)]
            r = subprocess.run(cmd, capture_output=True, text=True, timeout=90)
            if r.returncode==0 and dest.exists() and dest.stat().st_size > 5000:
                print(f"✅ {dest.stat().st_size//1024} KB"); ok += 1; downloaded = True; break
            dest.unlink(missing_ok=True)
        if not downloaded: print("❌"); fail += 1

    if metadata_rows:
        csv_path = data_dir / f"{safe(player_name)}_clips_metadata.csv"
        with open(csv_path,'w',newline='',encoding='utf-8') as f:
            w = csv.DictWriter(f, fieldnames=list(metadata_rows[0].keys()))
            w.writeheader(); w.writerows(metadata_rows)
        print(f"\n📋 Metadata CSV → {csv_path}")

    print(f"\n🎉 {ok} downloaded | {skip} already existed | {fail} failed")
    print(f"📁 {out_dir.resolve()}")

if __name__=="__main__": asyncio.run(main())
