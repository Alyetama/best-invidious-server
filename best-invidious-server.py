#!/usr/bin/env python
# coding: utf-8

import concurrent.futures
import json
import statistics
import urllib.request
from collections import OrderedDict

from ping3 import ping


def _iter_ping(server):
    local_results = []
    down = 0
    for _ in range(count):
        ms = ping(server, timeout=timeout)
        if ms:
            local_results.append(ms)
        else:
            down += 1
            if down > tolerance:
                print(f'`{server}` is taking too long to respond! Skipping...')
                return
    return (statistics.mean(local_results), server)


def best_servers(servers, count=10, tolerance=4, timeout=1):
    globals().update({
        'count': count,
        'tolerance': tolerance,
        'timeout': timeout
    })
    with concurrent.futures.ThreadPoolExecutor() as executor:
        results = []
        futures = [executor.submit(_iter_ping, server) for server in servers]
        for future in concurrent.futures.as_completed(futures):
            results.append(future.result())

    results = OrderedDict([x[::-1] for x in sorted([x for x in results if x])])

    print('\nResults (from best to worst):')
    print(json.dumps(results, indent=4))
    return results


def main():
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

    return best_servers(servers)


if __name__ == '__main__':
    best_servers = main()
    r = '🚀'
    with open('index.md', 'w') as f:
        f.write('# Best Invidious.io Servers\n\n')
        f.write('## ⭐ Best servers:\n\n')
        for n, (uri, latency) in enumerate(best_servers.items(), start=1):
            f.write(f'{n}. {r} [{uri}]({uri}) (`{round(latency, 4)}` ms)\n')
            r = ''
