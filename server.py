from flask import Flask, jsonify, send_from_directory
from flask_cors import CORS
import json, os, threading, time, subprocess, sys

app = Flask(__name__, static_folder='.')
CORS(app)

LB_CACHE   = 'letterboxd_cache.json'
SZ_CACHE   = 'serializd_cache.json'
DIARY_META = 'diary_meta.json'

_refresh_lock  = threading.Lock()
_is_refreshing = False


def read_json(path):
    if os.path.exists(path):
        try:
            with open(path, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception:
            pass
    return []


def read_meta():
    if os.path.exists(DIARY_META):
        try:
            with open(DIARY_META, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception:
            pass
    return {}


def write_meta(d):
    with open(DIARY_META, 'w', encoding='utf-8') as f:
        json.dump(d, f)


def combined_diary():
    lb    = read_json(LB_CACHE)
    sz    = read_json(SZ_CACHE)
    all_e = lb + sz

    seen, merged = set(), []
    for e in all_e:
        k = (
            f"{(e.get('title') or '').strip().lower()}"
            f"|{e.get('watched_date') or ''}"
            f"|{e.get('source') or ''}"
        )
        if k not in seen:
            seen.add(k)
            merged.append(e)

    merged.sort(
        key=lambda e: e.get('watched_date') or '',
        reverse=True,
    )
    return merged


def run_refresh():
    global _is_refreshing
    with _refresh_lock:
        if _is_refreshing:
            return
        _is_refreshing = True

    try:
        print('\n🔄 Background refresh starting...')
        subprocess.run(
            [sys.executable, 'fetch_letterboxd.py'],
            timeout=60,
            capture_output=False,
        )
        subprocess.run(
            [sys.executable, 'fetch_serializd.py'],
            timeout=360,
            capture_output=False,
        )
        m = read_meta()
        m['last_refresh'] = time.time()
        write_meta(m)
        print('✅ Background refresh complete\n')
    except Exception as e:
        print(f'❌ Refresh error: {e}')
    finally:
        with _refresh_lock:
            _is_refreshing = False


def trigger_bg_refresh():
    t = threading.Thread(target=run_refresh, daemon=True)
    t.start()


@app.route('/')
def index():
    return send_from_directory('.', 'index.html')


@app.route('/api/diary')
def diary():
    entries = combined_diary()
    lb_c    = len(read_json(LB_CACHE))
    sz_c    = len(read_json(SZ_CACHE))
    trigger_bg_refresh()
    return jsonify({
        'entries':    entries,
        'count':      len(entries),
        'refreshing': _is_refreshing,
        'lb_count':   lb_c,
        'sz_count':   sz_c,
    })


@app.route('/api/status')
def status():
    meta = read_meta()
    lb_c = len(read_json(LB_CACHE))
    sz_c = len(read_json(SZ_CACHE))
    return jsonify({
        'refreshing':   _is_refreshing,
        'last_refresh': meta.get('last_refresh', 0),
        'lb_count':     lb_c,
        'sz_count':     sz_c,
        'total':        lb_c + sz_c,
    })


@app.route('/<path:path>')
def static_files(path):
    return send_from_directory('.', path)


if __name__ == '__main__':
    has_cache = os.path.exists(LB_CACHE) or os.path.exists(SZ_CACHE)

    if not has_cache:
        print('📋 First run — building cache...')
        subprocess.run(
            [sys.executable, 'fetch_letterboxd.py'],
            timeout=60,
        )
        subprocess.run(
            [sys.executable, 'fetch_serializd.py'],
            timeout=360,
        )
        m = read_meta()
        m['last_refresh'] = time.time()
        write_meta(m)
    else:
        print('✅ Cache found — starting immediately')
        trigger_bg_refresh()

    port = int(os.environ.get('PORT', 10000))
    print(f'\n🌐  Running on port {port}\n')
    app.run(
        host='0.0.0.0',
        port=port,
        debug=False,
        threaded=True,
    )
