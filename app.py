#!/usr/bin/env python
# coding: utf-8

import argparse
import concurrent.futures
import asyncio
import json
import logging
import os
import statistics
import urllib.request
from collections import OrderedDict
from pathlib import Path
from typing import Any, Optional, Tuple, Union

import uvicorn
from fastapi import FastAPI, Response, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from ping3 import ping

app = FastAPI()
logger = logging.getLogger('uvicorn')

skip_list = []
if os.getenv('SKIP_LIST'):
    skip_list = os.getenv('SKIP_LIST').split(',')


class _PrettyJSONResponse(Response):
    media_type = 'application/json'

    @staticmethod
    def render(content: Any) -> bytes:  # noqa
        return json.dumps(content,
                          ensure_ascii=False,
                          allow_nan=False,
                          indent=4).encode('utf-8')


class _BackgroundRunner:

    def __init__(self, _best_servers):
        self._best_servers = _best_servers

    async def run_bg_task(self):
        while True:
            if not Path('.cache.json').exists():
                HTMLResponse(
                    'The server is warming up... Try again in a minute...')
            _best_servers()
            with open('.cache.json') as j:
                self._best_servers = json.load(j)
            await asyncio.sleep(60 * 60)


def _iter_ping(server: str, count: int, timeout: int,
               max_retries: int) -> Optional[Tuple[float, str]]:
    if server in skip_list:
        return
    local_results = []
    down = 0
    for _ in range(count):
        ms = ping(server, timeout=timeout)
        if ms:
            local_results.append(ms)
        else:
            down += 1
            if down > max_retries:
                logger.warning(
                    f'"{server}" is taking too long to respond! Skipping...')
                return
    return (statistics.mean(local_results), server)


def _best_servers(count: int = 10,
                  max_retries: int = 1,
                  timeout: Union[float, int] = 0.2,
                  return_markdown: bool = False) -> Union[dict, str]:

    logger.info('Updating...')

    resp = urllib.request.urlopen('https://api.invidious.io/instances.json')
    resp = json.loads(resp.read())
    servers = []
    for server in resp[::-1]:
        if not server[1]['monitor'] or server[1]['type'] != 'https':
            continue
        elif server[1]['monitor']['statusClass'] != 'success':
            continue

        health = statistics.mean(
            [float(x['ratio']) for x in server[1]['monitor']['dailyRatios']])
        if health < 99:
            continue

        uri = server[1]['uri']
        servers.append(uri.replace('https://', ''))

    items = [(server, count, max_retries, timeout) for server in servers]
    with concurrent.futures.ThreadPoolExecutor() as executor:
        results = []

        futures = [executor.submit(_iter_ping, *item) for item in items]
        for future in concurrent.futures.as_completed(futures):
            results.append(future.result())

    sorted_results = [x[::-1] for x in sorted([x for x in results if x])]
    sorted_results = [(f'https://{x[0]}', x[1]) for x in sorted_results]
    results = OrderedDict(sorted_results)

    with open('.cache.json', 'w') as j:
        json.dump(results, j, indent=4)
    logger.info('Saved cache...')

    if not return_markdown:
        return results

    r = '🚀'
    content = ''
    content += '# Best [Invidious.io](invidious.io) Servers\n\n'
    content += '## ⭐ Best servers:\n\n'
    for n, (uri, latency) in enumerate(results.items(), start=1):
        content += f'{n}. {r} [{uri}]({uri}) (`{round(latency, 4)}` ms)\n'
        r = ''
    return content


@app.on_event('startup')
async def _app_startup():
    asyncio.create_task(runner.run_bg_task())


@app.on_event('shutdown')
def _app_shutdown():
    if Path('.cache.json').exists():
        logger.info('Cleaning cache...')
        Path('.cache.json').unlink()


@app.get('/', status_code=307)
@app.get('/watch', status_code=307)
@app.get('/best_server', status_code=307)
def best_server(request: Request, redirect=True):
    _best_servers = runner._best_servers
    _best_server = [
        k for k, v in _best_servers.items() if v == min(_best_servers.values())
    ][0]
    if not redirect:
        return HTMLResponse(_best_server)
    else:
        request_url =  str(request.url)
        if 'watch' in request_url:
            video_id = request_url.split('/watch?v=')[1]
            _best_server = f'{_best_server}/watch?v={video_id}'
        if 'channel' in request_url:
            channel_id = request_url.split('/channel/')[1]
            _best_server = f'{_best_server}/channel/{channel_id}'
        return RedirectResponse(_best_server)


@app.get('/best_servers', status_code=200)
def best_servers(
        count: int = 10,
        max_retries: int = 1,
        timeout: Union[float, int] = 0.2,
        return_markdown: bool = False
) -> Union[_PrettyJSONResponse, HTMLResponse]:
    if return_markdown:
        resp = _best_servers(return_markdown=True)
        return HTMLResponse(resp)
    else:
        with open('.cache.json') as j:
            resp = json.load(j)
        return _PrettyJSONResponse(resp)


def _opts() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument('-H', '--host', default='127.0.0.1', type=str)
    parser.add_argument('-p', '--port', default=5000, type=int)
    return parser.parse_args()


runner = _BackgroundRunner('Warming up... Try again in a minute...')

if __name__ == '__main__':
    args = _opts()
    uvicorn.run('app:app', reload=True, host=args.host, port=args.port)
