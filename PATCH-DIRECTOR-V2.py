from pathlib import Path
import re, shutil, sys
from datetime import datetime
ROOT=Path(sys.argv[1]).resolve()
BACK=ROOT/'.ollama-studio-backups'/datetime.now().strftime('%Y%m%d-%H%M%S-v2')
BACK.mkdir(parents=True, exist_ok=True)

def rw(rel, fn):
    p=ROOT/rel
    if not p.exists():
        raise SystemExit(f'[ERROR] missing {rel}')
    old=p.read_text(encoding='utf-8')
    new=fn(old)
    if new!=old:
        b=BACK/rel; b.parent.mkdir(parents=True, exist_ok=True); shutil.copy2(p,b); p.write_text(new,encoding='utf-8'); print('[PATCHED]',rel)
    else: print('[OK]',rel)

def write(rel,text):
    p=ROOT/rel
    if p.exists():
        old=p.read_text(encoding='utf-8')
        if old==text: print('[OK]',rel); return
        b=BACK/rel; b.parent.mkdir(parents=True,exist_ok=True); shutil.copy2(p,b)
    p.parent.mkdir(parents=True,exist_ok=True); p.write_text(text,encoding='utf-8'); print('[PATCHED]',rel)

# Docker: local Piper installed in the image.
rw('Dockerfile', lambda s: s.replace('RUN pip install --no-cache-dir --retries 4 --timeout 120 -r requirements.txt','RUN pip install --no-cache-dir --retries 4 --timeout 180 -r requirements.txt && pip install --no-cache-dir piper-tts'))

write('app/services/local_tts.py', r'''import os,re,subprocess
from pathlib import Path
from loguru import logger
MODEL=os.getenv('PIPER_MODEL','/MoneyPrinterTurbo/models/piper/en_US-lessac-medium.onnx')
def duration(p):
    try:return float(subprocess.check_output(['ffprobe','-v','error','-show_entries','format=duration','-of','default=nw=1:nk=1',p],text=True,timeout=30).strip())
    except:return 0.0
def synthesize(text,out):
    m=Path(MODEL); cfg=Path(str(m)+'.json'); o=Path(out); wav=o.with_suffix('.piper.wav')
    if not m.exists() or not cfg.exists(): return False
    try:
        p=subprocess.run(['piper','--model',str(m),'--config',str(cfg),'--output_file',str(wav)],input=(text or '').encode(),stdout=subprocess.PIPE,stderr=subprocess.PIPE,timeout=max(180,len(text)//8))
        if p.returncode or not wav.exists(): return False
        q=subprocess.run(['ffmpeg','-y','-i',str(wav),'-codec:a','libmp3lame','-q:a','2',str(o)],stdout=subprocess.DEVNULL,stderr=subprocess.PIPE,timeout=180)
        return q.returncode==0 and o.exists() and o.stat().st_size>1024 and duration(str(o))>0
    except Exception as e: logger.warning(f'Piper failed: {e}'); return False
    finally:
        try:wav.unlink(missing_ok=True)
        except:pass
def create_subtitles(text,audio,srt):
    d=duration(audio); parts=[x.strip() for x in re.split(r'(?<=[.!?])\s+|\n+',text or '') if x.strip()]
    if d<=0 or not parts:return False
    weights=[max(1,len(re.findall(r'\w+',x))) for x in parts]; total=sum(weights); cur=0.0; lines=[]
    def ts(v):
        ms=int(v*1000); h,ms=divmod(ms,3600000); m,ms=divmod(ms,60000); s,ms=divmod(ms,1000); return f'{h:02d}:{m:02d}:{s:02d},{ms:03d}'
    for i,(x,w) in enumerate(zip(parts,weights),1):
        end=d if i==len(parts) else min(d,cur+d*w/total); lines += [str(i),f'{ts(cur)} --> {ts(end)}',x,'']; cur=end
    Path(srt).write_text('\n'.join(lines),encoding='utf-8'); return True
''')

write('app/services/quality_control.py', r'''import json,subprocess
from pathlib import Path
from loguru import logger
def save_report(task_dir,video_path,target_minutes=3,attribution_file=None):
    r={'video':video_path,'score':100,'duration_seconds':0,'resolution':'','audio':False,'warnings':[]}
    try:
        d=json.loads(subprocess.check_output(['ffprobe','-v','error','-show_streams','-show_format','-of','json',video_path],text=True,timeout=45)); ss=d.get('streams') or []; v=next((x for x in ss if x.get('codec_type')=='video'),None); r['audio']=any(x.get('codec_type')=='audio' for x in ss); r['duration_seconds']=round(float((d.get('format') or {}).get('duration') or 0),2); r['resolution']=f"{v.get('width',0)}x{v.get('height',0)}" if v else ''
    except Exception as e:r['warnings'].append(str(e));r['score']-=50
    if not r['audio']:r['warnings'].append('No audio stream');r['score']-=25
    target=target_minutes*60
    if r['duration_seconds'] and (r['duration_seconds']<target*.55 or r['duration_seconds']>target*1.6):r['warnings'].append('Duration far from target');r['score']-=12
    if attribution_file and not Path(attribution_file).exists():r['warnings'].append('Attribution missing');r['score']-=5
    r['score']=max(0,r['score']); Path(task_dir,'quality-report.json').write_text(json.dumps(r,indent=2),encoding='utf-8'); logger.info(f"Quality check {r['score']}/100"); return r
''')

# Upgrade auto_media planner/ranker/storyboard in-place.
rw('app/services/auto_media.py', lambda s: s.replace('USER_AGENT = "MoneyPrinterTurbo-Ollama-Studio/3.0"','USER_AGENT = "MoneyPrinterTurbo-Ollama-Director/2.0"').replace('candidates.extend(_commons_search(query, 8))','candidates.extend(_commons_search(query, 12))').replace('candidates.extend(_archive_search(query, 5))','candidates.extend(_archive_search(query, 8))'))

# Add a lightweight storyboard generated from existing scene/attribution JSON.
rw('app/services/auto_media.py', lambda s: s if 'def _write_storyboard_html(' in s else s.replace("def download_for_script(task_id: str, script: str, target_minutes: int, clip_seconds: int):", r'''def _write_storyboard_html(output_dir, scenes, records):
    import html as _html
    by={r.get('scene_number'):r for r in records}
    cards=[]
    for sc in scenes:
        r=by.get(sc.get('scene_number'),{})
        cards.append(f"<article><h3>Scene {sc.get('scene_number')}</h3><p><b>Narration:</b> {_html.escape(sc.get('narration',''))}</p><p><b>Search:</b> {_html.escape(sc.get('visual_search_query',''))}</p><p><b>Selected:</b> {_html.escape(r.get('title',''))}</p><p><b>Source:</b> {_html.escape(r.get('provider',''))}</p></article>")
    page="<!doctype html><meta charset='utf-8'><title>Ollama Director Storyboard</title><style>body{font-family:Segoe UI;background:#0d1117;color:#eee;padding:24px}main{display:grid;grid-template-columns:repeat(auto-fit,minmax(320px,1fr));gap:16px}article{background:#161b22;border:1px solid #30363d;border-radius:12px;padding:16px}b{color:#58a6ff}</style><h1>Ollama Director - Living Storyboard</h1><main>"+''.join(cards)+"</main>"
    (output_dir/'storyboard.html').write_text(page,encoding='utf-8')


def download_for_script(task_id: str, script: str, target_minutes: int, clip_seconds: int):'''))

rw('app/services/auto_media.py', lambda s: s if '_write_storyboard_html(output_dir, scenes, records)' in s else s.replace('    if not materials:\n        return [], scenes','    _write_storyboard_html(output_dir, scenes, records)\n    if not materials:\n        return [], scenes'))

# task.py local-first TTS + QC
rw('app/services/task.py', lambda s: s.replace('    auto_media,\n    elevenlabs_music,','    auto_media,\n    local_tts,\n    quality_control,\n    elevenlabs_music,') if '    local_tts,\n' not in s else s)

def patch_task(s):
    old='''        logger.info("no custom audio file provided, using TTS to generate audio.")\n        audio_file = path.join(utils.task_dir(task_id), "audio.mp3")\n        sub_maker = voice.tts(\n            text=video_script,\n            voice_name=voice.parse_voice_name(params.voice_name),\n            voice_rate=params.voice_rate,\n            voice_file=audio_file,\n        )'''
    new='''        logger.info("no custom audio file provided, using local-first Piper TTS.")\n        audio_file = path.join(utils.task_dir(task_id), "audio.mp3")\n        sub_maker = None\n        local_ok = local_tts.synthesize(video_script, audio_file)\n        if not local_ok:\n            logger.warning("Piper unavailable; falling back to Edge TTS")\n            sub_maker = voice.tts(text=video_script, voice_name=voice.parse_voice_name(params.voice_name), voice_rate=params.voice_rate, voice_file=audio_file)'''
    s=s.replace(old,new)
    s=s.replace('''        if sub_maker is None:\n            _mark_task_failed(\n                task_id,\n                "audio",\n                "failed to synthesize audio; verify the selected voice and TTS connectivity",\n            )\n            return None, None, None''','''        if sub_maker is None and not os.path.exists(audio_file):\n            _mark_task_failed(task_id, "audio", "Piper and Edge TTS both failed")\n            return None, None, None''')
    marker='''    if sub_maker is None and subtitle_provider != "whisper":'''
    if marker in s and 'local_tts.create_subtitles' not in s:
        start=s.index(marker); end=s.index('\n\n    is_word_level',start)
        s=s[:start]+'''    if sub_maker is None and subtitle_provider != "whisper":\n        logger.info("creating local narration-timed subtitles")\n        if local_tts.create_subtitles(video_script, audio_file, subtitle_path):\n            return subtitle_path\n        return ""'''+s[end:]
    target='''        final_video_paths.append(final_video_path)\n        combined_video_paths.append(combined_video_path)'''
    if target in s and 'quality_control.save_report' not in s:
        s=s.replace(target,target+'''\n        try:\n            quality_control.save_report(utils.task_dir(task_id), final_video_path, int(getattr(params, "target_duration_minutes", 3) or 3), path.join(utils.task_dir(task_id), "ollama_auto_media", "ATTRIBUTION.md") if params.video_source == "ollama_auto_media" else None)\n        except Exception as exc:\n            logger.warning(f"quality check failed: {exc}")''',1)
    return s
rw('app/services/task.py',patch_task)

# Edge fallback gets 150 sec instead of 30.
rw('app/services/voice.py', lambda s:s.replace('_DEFAULT_EDGE_TTS_TIMEOUT_SECONDS = 30.0','_DEFAULT_EDGE_TTS_TIMEOUT_SECONDS = 150.0'))

# config defaults
rw('config.example.toml', lambda s:s if 'edge_tts_timeout = 150' in s else s+'\nedge_tts_timeout = 150\n')
print('[SUCCESS] Director V2 applied; backups:',BACK)
