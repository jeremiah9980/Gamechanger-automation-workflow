#!/usr/bin/env python3
"""
gc_download_player.py  (API Direct Edition v6)
===============================================
Downloads GameChanger clips by calling the clips/search/v2 API directly.
Captures gc-token, gc-device-id, and x-aws-waf-token from the browser session,
then uses httpx to enumerate clips per game and download via CloudFront.

Filename: 2024-11-02_Bananas_Single_LineDriverightCenter_Inn3Top_Kassidy.mp4

Usage:
    python3 gc_download_player.py \
        --team-urls "https://web.gc.com/teams/TTkhXvh9VmJ1/2024-fall-bananas,https://web.gc.com/teams/dDeB8Wx16VhO/2025-spring-hotshots-2k15-cortinas-10u" \
        --player-id "48483163-1262-46b7-ab00-682dfdc03ee5" \
        --player-name "Kassidy" \
        --output ./gc_clips/Kassidy/mp4s

    # Skip AI descriptions (faster):
        --no-ai
"""

import argparse, asyncio, base64, csv, json, os, re, subprocess
from datetime import datetime
from io import BytesIO
from pathlib import Path
import anthropic, httpx
from PIL import Image
from playwright.async_api import async_playwright

CLIPS_API   = "https://api.team-manager.gc.com/clips/search/v2"
PLAYBACK_API= "https://api.team-manager.gc.com"
AI_MODEL    = "claude-haiku-4-5-20251001"
PAGE_SIZE   = 36

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
    p.add_argument("--team-url",    default=None)
    p.add_argument("--team-urls",   default=None)
    p.add_argument("--no-ai",       action="store_true")
    p.add_argument("--api-key",     default=None)
    p.add_argument("--play-side",   default=None, help="offensive, defensive, or None for both")
    return p.parse_args()

def safe(s): return re.sub(r'[^a-zA-Z0-9_\-]','_',str(s)).strip('_')[:50]

def get_date(ts):
    try: return datetime.fromisoformat(ts.replace('Z','+00:00')).strftime('%Y-%m-%d')
    except: return 'unknown'

def make_filename(clip, ginfo, player_name, ai_desc='', team_label=''):
    ts     = clip.get('timestamp','') or clip.get('clip_timestamp','')
    date   = get_date(ts)
    sport  = clip.get('sport_metadata',{}) or {}
    inn    = sport.get('inning','')
    half   = sport.get('inning_half','')
    half_s = 'Top' if half=='top' else 'Bot' if half=='bottom' else ''
    inn_s  = f"Inn{inn}{half_s}" if inn else ''
    play   = safe(clip.get('name','') or clip.get('play_type','') or 'clip')
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

def api_headers(auth):
    """Build headers for clips/search/v2 API calls."""
    return {
        "accept":          "application/vnd.gc.com.video_clip_search_v2_results+json; version=0.0.0",
        "content-type":    "application/vnd.gc.com.video_clip_search_query+json; version=0.0.0",
        "gc-app-name":     "web",
        "gc-device-id":    auth["device_id"],
        "gc-token":        auth["gc_token"],
        "x-aws-waf-token": auth["waf_token"],
        "origin":          "https://web.gc.com",
        "referer":         "https://web.gc.com/",
        "user-agent":      "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/149.0.0.0 Safari/537.36",
    }

def search_clips(auth, event_id, player_id, play_side=None, offset=0):
    """Call clips/search/v2 for one game, one page."""
    match_all = {
        "event_id":  event_id,
        "player_id": [player_id],
    }
    if play_side:
        match_all["attributes"] = {"play_side": play_side}

    body = {
        "select":   {"kind": "player", "include_totals": True},
        "match_all": match_all,
        "limit":    PAGE_SIZE,
        "sort":     [{"by": "timestamp", "order": "asc"}],
        "paging":   "page",
        "offset":   offset,
    }
    r = httpx.post(CLIPS_API, headers=api_headers(auth), json=body, timeout=20)
    if r.status_code == 200:
        return r.json()
    print(f"      API {r.status_code}: {r.text[:120]}")
    return None

def get_all_clips_for_game(auth, event_id, player_id, play_side=None):
    """Paginate through all clips for a game."""
    clips = []
    offset = 0
    while True:
        data = search_clips(auth, event_id, player_id, play_side, offset)
        if not data: break
        hits = data.get('hits', data.get('clips', data.get('data', [])))
        if not hits: break
        clips.extend(hits)
        total = data.get('total', data.get('totals', {}).get('clips', len(hits)))
        if isinstance(total, dict): total = total.get('clips', len(hits))
        offset += PAGE_SIZE
        if offset >= total: break
    return clips

async def main():
    args = parse_args()
    api_key = args.api_key or os.environ.get('ANTHROPIC_API_KEY')
    if not api_key and not args.no_ai:
        print("⚠ No ANTHROPIC_API_KEY — running with --no-ai"); args.no_ai = True
    ai_client = anthropic.Anthropic(api_key=api_key) if not args.no_ai else None

    # Build team URL list
    team_urls = []
    if args.team_urls:
        team_urls = [u.strip().rstrip('/') for u in args.team_urls.split(',') if u.strip()]
    elif args.team_url:
        team_urls = [args.team_url.rstrip('/')]
    else:
        print("❌ Provide --team-url or --team-urls"); return

    player_id   = args.player_id
    player_name = args.player_name
    out_dir     = Path(args.output or f"gc_clips/{safe(player_name)}_{player_id[:8]}/mp4s")
    out_dir.mkdir(parents=True, exist_ok=True)

    print(f"\n{'='*60}")
    print(f"  GC Clips API v3 {'+ AI' if not args.no_ai else '(no AI)'}")
    for u in team_urls: print(f"  • {u.split('/teams/')[-1]}")
    print(f"  Player: {player_name} ({player_id[:8]}...)")
    print(f"  Output: {out_dir}\n{'='*60}\n")

    # Auth state captured from browser
    auth = {"gc_token": None, "device_id": None, "waf_token": None}
    channel_auth = {}; game_info = {}; all_clips = []; game_ids_by_team = {}

    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=False)
        ctx     = await browser.new_context(permissions=["clipboard-read","clipboard-write"])

        def on_request(req):
            h = req.headers
            if h.get('gc-token') and not auth["gc_token"]:
                auth["gc_token"]  = h.get('gc-token')
                auth["device_id"] = h.get('gc-device-id','')
                auth["waf_token"] = h.get('x-aws-waf-token','')
                print(f"  🔑 Auth captured (token ...{auth['gc_token'][-12:]})")

            # Refresh WAF token whenever we see a newer one
            if h.get('x-aws-waf-token'):
                auth["waf_token"] = h.get('x-aws-waf-token')

        async def on_response(resp):
            url = resp.url
            try:
                ct = resp.headers.get('content-type','')
                if 'json' not in ct: return

                # Capture CloudFront cookies for video download
                if 'standalone-playback-data' in url:
                    body = await resp.json()
                    pb   = body.get('playback',{}); vurl = pb.get('url',''); ck = pb.get('cookies',{})
                    m    = re.search(r'/376441934742/(\w+)/clips/', vurl)
                    if m and ck:
                        ch = m.group(1)
                        channel_auth[ch] = {'cookies':ck,'url':vurl,'ts':body.get('timestamp','')}
                        print(f"  ✅ CF cookie [{len(channel_auth)}] {body.get('name','')} — {ch}")

                # Capture game info from schedule responses
                elif any(x in url for x in ['game-summaries','events','schedule']):
                    body  = await resp.json()
                    items = body if isinstance(body,list) else body.get('data', body.get('events', body.get('game_summaries',[])))
                    if isinstance(items, dict): items = [items]
                    for ev in (items or []):
                        eid = ev.get('id') or ev.get('event_id') or ev.get('game_id')
                        if not eid: continue
                        home = ev.get('home_team',{}); away = ev.get('away_team',{})
                        hn   = home.get('name','') if isinstance(home,dict) else str(home)
                        an   = away.get('name','') if isinstance(away,dict) else str(away)
                        opp  = ev.get('opponent') or ev.get('opponent_name') or an or hn
                        st   = ev.get('start_time') or ev.get('date') or ev.get('scheduled_at','')
                        game_info[str(eid)] = {'opponent':opp,'home_team':hn,'away_team':an,'date':st[:10] if st else ''}
            except: pass

        ctx.on("request",  on_request)
        ctx.on("response", on_response)
        page = await ctx.new_page()

        print("⏳ Log in manually — 90 seconds...")
        await page.goto("https://web.gc.com/login", wait_until="domcontentloaded")
        await asyncio.sleep(90)

        # Visit each team schedule to capture game IDs + refresh WAF token
        for team_url in team_urls:
            team_label = team_url.split('/')[-1]
            print(f"\n  📋 Fetching schedule: {team_label}")
            try:
                await page.goto(f"{team_url}/schedule", wait_until="domcontentloaded", timeout=30000)
            except: pass
            await asyncio.sleep(6)

            html = await page.content()
            gids = list(dict.fromkeys(
                re.findall(r'/schedule/([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})', html)
            ))
            game_ids_by_team[team_label] = gids
            print(f"  Found {len(gids)} games")

            # Visit first game's videos page to warm up WAF token + trigger any auth
            if gids:
                try:
                    await page.goto(f"{team_url}/schedule/{gids[0]}/videos/clips",
                                    wait_until="domcontentloaded", timeout=20000)
                    await asyncio.sleep(4)
                    # Refresh WAF token from page context
                    waf = await page.evaluate("""() => {
                        const m = document.cookie.match(/aws-waf-token=([^;]+)/);
                        return m ? m[1] : null;
                    }""")
                    if waf: auth["waf_token"] = waf
                except: pass

        if browser.is_connected(): await browser.close()

    if not auth["gc_token"]:
        print("❌ No gc-token captured — did you log in?"); return

    print(f"\n🔑 Auth ready. Querying clips API...\n")

    # Now call the API directly for each team/game
    for team_url in team_urls:
        team_label = team_url.split('/')[-1]
        gids = game_ids_by_team.get(team_label, [])
        print(f"\n  📋 Team: {team_label} ({len(gids)} games)")

        for i, game_id in enumerate(gids):
            print(f"  [{i+1:>2}/{len(gids)}] {game_id[:8]}...", end=" ", flush=True)

            # Query both offensive and defensive (or specific side)
            game_clips = []
            sides = [args.play_side] if args.play_side else ["offensive", "defensive"]
            for side in sides:
                clips = get_all_clips_for_game(auth, game_id, player_id, side)
                game_clips.extend(clips)

            # Dedupe by clip_metadata_id
            seen = set(c.get('clip_metadata_id','') for c in all_clips)
            new_clips = [c for c in game_clips if c.get('clip_metadata_id','') not in seen]

            if new_clips:
                print(f"{len(new_clips)} clips ✅")
                for c in new_clips:
                    c['_team_label'] = team_label
                    c['_game_id']    = game_id
                all_clips.extend(new_clips)
            else:
                print("no clips")

    data_dir = out_dir.parent
    with open(data_dir/'clips.json','w') as f: json.dump(all_clips, f, indent=2)
    with open(data_dir/'game_info.json','w') as f: json.dump(game_info, f, indent=2)

    print(f"\n📊 Total clips found: {len(all_clips)}")
    if not all_clips:
        print("❌ No clips found — check player ID matches this team's roster"); return
    if not channel_auth:
        print("⚠ No CF cookies captured — will attempt direct thumbnail-to-mp4 fallback")

    print(f"\n⬇  {'AI-analyzing + d' if not args.no_ai else 'D'}ownloading {len(all_clips)} clips...\n")
    metadata_rows = []; ok = fail = skip = 0

    for clip in all_clips:
        thumb      = clip.get('thumbnail_url','')
        team_label = clip.get('_team_label','')
        game_id    = clip.get('_game_id','')
        ginfo      = game_info.get(game_id, {})

        m = re.search(r'/376441934742/(\w+)/clips/([\d\-T:.Z]+)\.jpg', thumb)
        ch = m.group(1) if m else None
        ts = m.group(2) if m else ''
        if not ginfo.get('date'): ginfo['date'] = get_date(ts)

        ai_desc = ''
        if not args.no_ai and ai_client:
            ai_desc = analyze_thumbnail(ai_client, thumb)

        fname = make_filename(clip, ginfo, player_name, ai_desc, team_label)
        dest  = out_dir / fname
        metadata_rows.append({
            'filename':    fname,
            'date':        ginfo.get('date',''),
            'opponent':    ginfo.get('opponent',''),
            'team':        team_label,
            'play_type':   clip.get('name','') or clip.get('play_type',''),
            'play_side':   (clip.get('attributes') or {}).get('play_side',''),
            'ai_description': ai_desc,
            'inning':      (clip.get('sport_metadata') or {}).get('inning',''),
            'inning_half': (clip.get('sport_metadata') or {}).get('inning_half',''),
            'player':      player_name,
            'clip_id':     clip.get('clip_metadata_id',''),
            'thumbnail_url': thumb,
            'channel':     ch or '',
        })

        if dest.exists(): print(f"  ✓ {fname[:65]}"); skip += 1; continue
        ai_tag = f" [{ai_desc[:30]}]" if ai_desc else ""
        print(f"  ↓ {fname[:52]}{ai_tag}", end=" ... ", flush=True)

        downloaded = False

        # Method 1: CloudFront HLS via ffmpeg (requires CF cookies)
        if ch and ch in channel_auth:
            cf  = channel_auth[ch]['cookies']
            cs  = "; ".join(f"{k}={v}" for k,v in cf.items())
            ref = channel_auth[ch]['url']
            ref_ts = channel_auth[ch]['ts']
            m3u8 = ref.replace(ref_ts.replace(':','%3A'), ts.replace(':','%3A')).replace(ref_ts, ts)
            cmd = ['ffmpeg','-y','-loglevel','error','-headers',f'Cookie: {cs}\r\n',
                   '-i', m3u8, '-c','copy', str(dest)]
            r = subprocess.run(cmd, capture_output=True, text=True, timeout=90)
            if r.returncode==0 and dest.exists() and dest.stat().st_size > 5000:
                print(f"✅ {dest.stat().st_size//1024} KB (HLS)"); ok += 1; downloaded = True

        # Method 2: Direct thumbnail → mp4 swap
        if not downloaded and thumb:
            mp4_url = thumb.replace('.jpg','.mp4')
            cmd = ['ffmpeg','-y','-loglevel','error','-i', mp4_url, '-c','copy', str(dest)]
            r = subprocess.run(cmd, capture_output=True, text=True, timeout=90)
            if r.returncode==0 and dest.exists() and dest.stat().st_size > 5000:
                print(f"✅ {dest.stat().st_size//1024} KB (direct)"); ok += 1; downloaded = True

        if not downloaded:
            dest.unlink(missing_ok=True)
            print("❌"); fail += 1

    if metadata_rows:
        csv_path = data_dir / f"{safe(player_name)}_clips_metadata.csv"
        with open(csv_path,'w',newline='',encoding='utf-8') as f:
            w = csv.DictWriter(f, fieldnames=list(metadata_rows[0].keys()))
            w.writeheader(); w.writerows(metadata_rows)
        print(f"\n📋 Metadata CSV → {csv_path}")

    print(f"\n🎉 {ok} downloaded | {skip} already existed | {fail} failed")
    print(f"📁 {out_dir.resolve()}")

if __name__=="__main__": asyncio.run(main())