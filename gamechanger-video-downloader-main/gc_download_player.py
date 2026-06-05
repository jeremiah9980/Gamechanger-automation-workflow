
#!/usr/bin/env python3
"""
gc_download_player.py  (AI Detail Edition)
==========================================
Downloads GameChanger clips with Claude Vision AI descriptions
baked into filenames and a metadata CSV.

Filename: 2026-02-21_Triple_HardHitToRightCenter_Inn1Bot_Kassidy.mp4

Usage:
    python3 gc_download_player.py \
        --team-url "https://web.gc.com/teams/SLUG/SEASON" \
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

TEAM_SLUG = "6EZBH3wGynM4"
SEASON    = "2026-spring-hotshots-2k15-10u"
BASE      = f"https://web.gc.com/teams/{TEAM_SLUG}/{SEASON}"
AI_MODEL  = "claude-haiku-4-5-20251001"

AI_PROMPT = """Analyze this youth softball/baseball clip thumbnail.
In 4-6 words describe the play action shown.
Examples: "Hard ground ball to shortstop", "Line drive right center",
"Stealing second base slide", "Strikeout looking", "Bunt toward third"
Reply ONLY with the 4-6 word description."""

def parse_args():
    p = argparse.ArgumentParser()
    p.add_argument("--player-id",   default="48483163-1262-46b7-ab00-682dfdc03ee5")
    p.add_argument("--player-name", default="Kassidy")
    p.add_argument("--output",      default=None)
    p.add_argument("--manifest",    default=None)
    p.add_argument("--team-url",    default=None)
    p.add_argument("--no-ai",       action="store_true")
    p.add_argument("--api-key",     default=None)
    return p.parse_args()

def safe(s): return re.sub(r'[^a-zA-Z0-9_\-]','_',str(s)).strip('_')[:50]

def get_date(ts):
    try: return datetime.fromisoformat(ts.replace('Z','+00:00')).strftime('%Y-%m-%d')
    except: return 'unknown'

def make_filename(clip, ginfo, player_name, ai_desc=''):
    ts     = clip.get('timestamp','')
    date   = get_date(ts)
    sport  = clip.get('sport_metadata',{})
    inn    = sport.get('inning','')
    half   = sport.get('inning_half','')
    half_s = 'Top' if half=='top' else 'Bot' if half=='bottom' else ''
    inn_s  = f"Inn{inn}{half_s}" if inn else ''
    play   = safe(clip.get('name','clip'))
    ai_p   = safe(ai_desc) if ai_desc else ''
    parts  = [p for p in [date,play,ai_p,inn_s,safe(player_name)] if p]
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

async def main():
    args = parse_args()
    api_key = args.api_key or os.environ.get('ANTHROPIC_API_KEY')
    if not api_key and not args.no_ai:
        print("⚠ No ANTHROPIC_API_KEY — running with --no-ai"); args.no_ai=True
    ai_client = anthropic.Anthropic(api_key=api_key) if not args.no_ai else None

    global BASE, TEAM_SLUG, SEASON
    if args.team_url:
        tu = args.team_url.rstrip('/')
        pts = tu.replace('https://web.gc.com/teams/','').split('/')
        TEAM_SLUG = pts[0] if pts else TEAM_SLUG
        SEASON    = pts[1] if len(pts)>1 else SEASON
        BASE      = tu

    player_id   = args.player_id
    player_name = args.player_name
    out_dir     = Path(args.output or f"gc_clips/{safe(player_name)}_{player_id[:8]}/mp4s")
    out_dir.mkdir(parents=True, exist_ok=True)

    print(f"\n{'='*60}")
    print(f"  GC Clips {'+ AI Detail' if not args.no_ai else '(no AI)'}")
    print(f"  {TEAM_SLUG}/{SEASON}")
    print(f"  Player: {player_name} ({player_id[:8]}...)")
    print(f"  Output: {out_dir}\n{'='*60}\n")

    channel_auth={};gc_token=[None];game_info={};player_clips=[];game_ids=[]

    if args.manifest and Path(args.manifest).exists():
        with open(args.manifest) as f: mdata=json.load(f)
        game_ids=list(dict.fromkeys(c['game_id'] for c in mdata.get('clips',[])
                                     if c.get('game_id') and c['game_id']!='unknown'))
        print(f"📋 {len(game_ids)} game IDs from manifest")

    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=False)
        ctx     = await browser.new_context(permissions=["clipboard-read","clipboard-write"])

        def on_request(req):
            tok=req.headers.get('gc-token','')
            if tok and not gc_token[0]: gc_token[0]=tok; print(f"  🔑 gc-token captured")

        async def on_response(resp):
            url=resp.url
            try:
                ct=resp.headers.get('content-type','')
                if 'json' not in ct and 'gc.com' not in ct: return

                if 'standalone-playback-data' in url:
                    body=await resp.json()
                    pb=body.get('playback',{}); vurl=pb.get('url',''); ck=pb.get('cookies',{})
                    m=re.search(r'/376441934742/(\w+)/clips/',vurl)
                    if m and ck:
                        ch=m.group(1)
                        channel_auth[ch]={'cookies':ck,'url':vurl,'ts':body.get('timestamp','')}
                        print(f"  ✅ [{len(channel_auth)}] {body.get('name','')} — {ch}")

                elif 'clips/search' in url:
                    body=await resp.json()
                    for hit in body.get('hits',[]):
                        pid=hit.get('player_metadata',{}).get('player_id','')
                        cid=hit.get('clip_metadata_id','')
                        if pid==player_id and not any(c.get('clip_metadata_id')==cid for c in player_clips):
                            player_clips.append(hit)

                elif 'game-summaries' in url or 'game_summaries' in url:
                    body=await resp.json()
                    items=body if isinstance(body,list) else body.get('data',body.get('game_summaries',body.get('events',[])))
                    if isinstance(items,dict): items=[items]
                    for ev in (items or []):
                        eid=ev.get('id') or ev.get('event_id') or ev.get('game_id')
                        if eid and str(eid) not in game_ids: game_ids.append(str(eid))
                        home=ev.get('home_team',{}); away=ev.get('away_team',{})
                        hn=home.get('name','') if isinstance(home,dict) else str(home)
                        an=away.get('name','') if isinstance(away,dict) else str(away)
                        opp=ev.get('opponent') or ev.get('opponent_name') or an or hn
                        st=ev.get('start_time') or ev.get('date') or ev.get('scheduled_at','')
                        if eid: game_info[str(eid)]={'opponent':opp,'home_team':hn,'away_team':an,'date':st[:10] if st else ''}

                elif 'teams/' in url and ('events' in url or 'schedule' in url):
                    body=await resp.json()
                    evs=body if isinstance(body,list) else body.get('events',body.get('data',[body]))
                    if isinstance(evs,dict): evs=[evs]
                    for ev in (evs or []):
                        eid=ev.get('id') or ev.get('event_id') or ev.get('schedule_id')
                        if not eid: continue
                        if str(eid) not in game_ids: game_ids.append(str(eid))
                        home=ev.get('home_team',{}); away=ev.get('away_team',{})
                        hn=home.get('name','') if isinstance(home,dict) else str(home)
                        an=away.get('name','') if isinstance(away,dict) else str(away)
                        opp=ev.get('opponent') or ev.get('opponent_name') or an or hn
                        st=ev.get('start_time') or ev.get('date') or ev.get('scheduled_at','')
                        game_info[str(eid)]={'opponent':opp,'home_team':hn,'away_team':an,'date':st[:10] if st else ''}
            except: pass

        ctx.on("request",on_request); ctx.on("response",on_response)
        page = await ctx.new_page()

        print("⏳ Log in manually — 60 seconds...")
        await page.goto("https://web.gc.com/login",wait_until="domcontentloaded"); await asyncio.sleep(60)

        print("📅 Fetching schedule...")
        try: await page.goto(f"{BASE}/schedule",wait_until="domcontentloaded",timeout=30000)
        except: pass
        await asyncio.sleep(6)
        if not game_ids:
            html=await page.content()
            game_ids.extend(list(dict.fromkeys(re.findall(r'/schedule/([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})',html))))
        print(f"  Found {len(game_ids)} games")

        for i,game_id in enumerate(game_ids):
            clips_url=f"{BASE}/schedule/{game_id}/videos/clips?filters.playerIds%5B0%5D={player_id}"
            print(f"  [{i+1:>2}/{len(game_ids)}] {game_id[:8]}...",end=" ",flush=True)
            try:
                await page.goto(clips_url,wait_until="domcontentloaded",timeout=20000); await asyncio.sleep(2)
                share_btn=await page.query_selector("[data-testid='share-icon']")
                if not share_btn: print("no clips"); continue
                await share_btn.click(); await asyncio.sleep(1.5)
                share_url=await page.evaluate("""() => {
                    const inp=document.querySelector('input[value*="/clips/"]'); if(inp) return inp.value;
                    const a=document.querySelector('a[href*="/clips/"]'); if(a) return a.href;
                    const m=document.querySelector('[data-testid="popup-test-id"]');
                    if(m){const r=m.innerText.match(/https?:\\/\\/\\S+\\/clips\\/\\S+/);if(r)return r[0];}
                    return null;}""")
                if not share_url:
                    try:
                        await page.get_by_text("Copy Link").first.click(); await asyncio.sleep(0.5)
                        share_url=await page.evaluate("navigator.clipboard.readText().catch(()=>'')")
                    except: pass
                await page.keyboard.press("Escape"); await asyncio.sleep(0.5)
                if share_url and '/clips/' in share_url:
                    print(f"→ navigating...",end=" ",flush=True)
                    try: await page.goto(share_url.strip(),wait_until="domcontentloaded",timeout=15000)
                    except: pass
                    await asyncio.sleep(2); print("done")
                else: print("no share URL")
            except Exception as e: print(f"error: {str(e)[:50]}")

        if browser.is_connected(): await browser.close()

    data_dir=out_dir.parent
    for name,obj in [('cf_cookies.json',channel_auth),('clips.json',player_clips),('game_info.json',game_info)]:
        with open(data_dir/name,'w') as f: json.dump(obj,f,indent=2)

    print(f"\n📊 Channels:{len(channel_auth)} | Clips:{len(player_clips)} | Games:{len(game_ids)}")
    if not channel_auth: print("❌ No cookies — can't download"); return
    if not player_clips: print("❌ No clips found"); return

    print(f"\n⬇  {'AI-analyzing thumbnails + d' if not args.no_ai else 'D'}ownloading {len(player_clips)} clips...\n")
    metadata_rows=[];ok=fail=skip=0

    for clip in player_clips:
        thumb=clip.get('thumbnail_url','')
        m=re.search(r'/376441934742/(\w+)/clips/([\d\-T:.Z]+)\.jpg',thumb)
        if not m: continue
        ch,ts=m.group(1),m.group(2)
        if ch not in channel_auth: fail+=1; continue

        gid=clip.get('event_id') or clip.get('game_id') or ''
        ginfo=game_info.get(gid,{})
        if not ginfo.get('date'): ginfo['date']=get_date(ts)

        ai_desc=''
        if not args.no_ai and ai_client:
            ai_desc=analyze_thumbnail(ai_client,thumb)

        fname=make_filename(clip,ginfo,player_name,ai_desc)
        dest=out_dir/fname
        metadata_rows.append({'filename':fname,'date':ginfo.get('date',''),'opponent':ginfo.get('opponent',''),
            'play_type':clip.get('name',''),'ai_description':ai_desc,
            'inning':clip.get('sport_metadata',{}).get('inning',''),
            'inning_half':clip.get('sport_metadata',{}).get('inning_half',''),
            'player':player_name,'clip_id':clip.get('clip_metadata_id',''),
            'thumbnail_url':thumb,'channel':ch})

        if dest.exists(): print(f"  ✓ {fname[:65]}"); skip+=1; continue
        ai_tag=f" [{ai_desc[:30]}]" if ai_desc else ""
        print(f"  ↓ {fname[:55]}{ai_tag}",end=" ... ",flush=True)

        cf=channel_auth[ch]['cookies']; cs="; ".join(f"{k}={v}" for k,v in cf.items())
        ref=channel_auth[ch]['url']; ref_ts=channel_auth[ch]['ts']
        m3u8=ref.replace(ref_ts.replace(':','%3A'),ts.replace(':','%3A')).replace(ref_ts,ts)
        downloaded=False
        for url in [m3u8,thumb.replace('.jpg','.mp4')]:
            cmd=['ffmpeg','-y','-loglevel','error','-headers',f'Cookie: {cs}\r\n','-i',url,'-c','copy',str(dest)]
            r=subprocess.run(cmd,capture_output=True,text=True,timeout=90)
            if r.returncode==0 and dest.exists() and dest.stat().st_size>5000:
                print(f"✅ {dest.stat().st_size//1024} KB"); ok+=1; downloaded=True; break
            dest.unlink(missing_ok=True)
        if not downloaded: print("❌"); fail+=1

    if metadata_rows:
        csv_path=data_dir/f"{safe(player_name)}_clips_metadata.csv"
        with open(csv_path,'w',newline='',encoding='utf-8') as f:
            w=csv.DictWriter(f,fieldnames=list(metadata_rows[0].keys())); w.writeheader(); w.writerows(metadata_rows)
        print(f"\n📋 Metadata CSV → {csv_path}")

    print(f"\n🎉 {ok} downloaded | {skip} already existed | {fail} failed")
    print(f"📁 {out_dir.resolve()}")

if __name__=="__main__": asyncio.run(main())
