"""Start the local terminal; the compiled interface needs no Node runtime."""
import argparse
import json
import os
from pathlib import Path
import sys
import threading
import time
from urllib.request import urlopen
import webbrowser


def is_running(url):
    try:
        with urlopen(url + '/api/health', timeout=1) as response:
            return json.load(response).get('service') == 'portfolio-terminal'
    except Exception:
        return False


def main():
    parser = argparse.ArgumentParser(description='Start Portfolio Tracker terminal')
    parser.add_argument('--port', type=int, default=8502)
    parser.add_argument('--open', action='store_true', help='Open the local dashboard in your browser')
    args = parser.parse_args()
    project = Path(__file__).resolve().parent
    os.chdir(project)
    os.environ.setdefault('MPLBACKEND', 'Agg')
    os.environ.setdefault('MPLCONFIGDIR', str(project / '.runtime' / 'matplotlib'))
    url = f'http://127.0.0.1:{args.port}'
    if is_running(url):
        print(f'Portfolio Tracker is already running: {url}', flush=True)
        if args.open:
            webbrowser.open(url)
        return
    if not (project / 'terminal' / 'dist' / 'index.html').exists():
        sys.exit('The interface needs to be built. See the Terminal interface section in README.md.')
    if args.open:
        def open_when_ready():
            for _ in range(60):
                if is_running(url):
                    webbrowser.open(url)
                    return
                time.sleep(.5)
        threading.Thread(target=open_when_ready, daemon=True).start()
    print(f'Portfolio Tracker: {url}', flush=True)
    import uvicorn
    uvicorn.run('terminal_api:app', host='127.0.0.1', port=args.port, log_level='info')


if __name__ == '__main__':
    main()
