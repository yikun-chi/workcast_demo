"""Stream-parse an XES log into Parquet (events partitioned by month) + cases.parquet.
Usage: parse_xes.py <input.xes> <out_dir> [--limit=N]
Also writes <out_dir>/schema.json with trace/event attribute key coverage.
"""
import sys, json, os, gc
from collections import Counter, defaultdict
from lxml import etree
import pyarrow as pa
import pyarrow.parquet as pq
import pandas as pd

inp, out = sys.argv[1], sys.argv[2]
limit = int(sys.argv[3].split('=')[1]) if len(sys.argv) > 3 and sys.argv[3].startswith('--limit=') else None
os.makedirs(out, exist_ok=True)
ev_dir = os.path.join(out, 'events.parquet')
os.makedirs(ev_dir, exist_ok=True)

NS = '{http://www.xes-standard.org/}'
def strip(tag):
    return tag.split('}', 1)[1] if '}' in tag else tag

trace_key_count = Counter(); trace_key_types = defaultdict(Counter)
event_key_count = Counter(); event_key_types = defaultdict(Counter)
log_meta = {'extensions': [], 'classifiers': [], 'globals': {}, 'log_attrs': {}}

cases = []
ev_buf = []          # list of dicts
chunk_id = 0
n_traces = 0; n_events = 0
CHUNK = 200_000

def flush_events():
    global ev_buf, chunk_id
    if not ev_buf:
        return
    df = pd.DataFrame(ev_buf)
    ts = pd.to_datetime(df['time:timestamp'], utc=True, format='ISO8601', errors='coerce')
    df['ts'] = ts
    df['month'] = ts.dt.strftime('%Y-%m').fillna('unknown')
    for m, g in df.groupby('month', sort=False):
        d = os.path.join(ev_dir, f'month={m}')
        os.makedirs(d, exist_ok=True)
        g.drop(columns=['month']).to_parquet(os.path.join(d, f'part-{chunk_id:05d}.parquet'), index=False)
    chunk_id += 1
    ev_buf = []
    gc.collect()

def parse_val(el):
    t = strip(el.tag)
    v = el.get('value')
    return t, v

TAGS = ['trace', 'extension', 'classifier', 'global', 'string', 'date', 'int', 'float', 'boolean']
# the published file has no xmlns on <log>; accept both namespaced and plain tags
context = etree.iterparse(inp, events=('end',), tag=[NS + t for t in TAGS] + TAGS, huge_tree=True)
in_trace_depth_hint = None
for _, el in context:
    tag = strip(el.tag)
    if tag == 'trace':
        n_traces += 1
        case = {}
        case_id = None
        ev_pos = 0
        for child in el:
            ct = strip(child.tag)
            if ct == 'event':
                ev = {}
                for a in child:
                    at = strip(a.tag)
                    k = a.get('key')
                    if k is None:
                        continue
                    event_key_count[k] += 1
                    event_key_types[k][at] += 1
                    ev[k] = a.get('value')
                ev['case_id'] = case_id
                ev['_pos'] = ev_pos
                ev_pos += 1
                ev_buf.append(ev)
                n_events += 1
            else:
                k = child.get('key')
                if k is None:
                    continue
                trace_key_count[k] += 1
                trace_key_types[k][ct] += 1
                case[k] = child.get('value')
                if k == 'concept:name':
                    case_id = child.get('value')
        # events were appended with case_id possibly None if concept:name came after events; fix
        if case_id is not None:
            for e in ev_buf[len(ev_buf) - ev_pos:]:
                e['case_id'] = case_id
        case['n_events'] = ev_pos
        cases.append(case)
        el.clear()
        parent = el.getparent()
        if parent is not None:
            while el.getprevious() is not None:
                del parent[0]
        if len(ev_buf) >= CHUNK:
            flush_events()
        if n_traces % 20000 == 0:
            print(f'traces={n_traces} events={n_events}', file=sys.stderr, flush=True)
        if limit and n_traces >= limit:
            break
    else:
        # log-level elements: only record those whose parent is <log> or <global>
        parent = el.getparent()
        if parent is None:
            continue
        pt = strip(parent.tag)
        if tag == 'extension':
            log_meta['extensions'].append(dict(el.attrib))
        elif tag == 'classifier':
            log_meta['classifiers'].append(dict(el.attrib))
        elif tag == 'global':
            log_meta['globals'][el.get('scope')] = {c.get('key'): {'type': strip(c.tag), 'default': c.get('value')} for c in el}
        elif pt == 'log':
            log_meta['log_attrs'][el.get('key')] = {'type': tag, 'value': el.get('value')}
        # don't clear here; trace clearing handles memory for trace children
flush_events()

cdf = pd.DataFrame(cases)
cdf.to_parquet(os.path.join(out, 'cases.parquet'), index=False)
schema = {
    'n_traces': n_traces, 'n_events': n_events,
    'trace_keys': {k: {'count': c, 'types': dict(trace_key_types[k])} for k, c in trace_key_count.most_common()},
    'event_keys': {k: {'count': c, 'types': dict(event_key_types[k])} for k, c in event_key_count.most_common()},
    'log_meta': log_meta,
}
json.dump(schema, open(os.path.join(out, 'schema.json'), 'w'), indent=2)
print(json.dumps({'n_traces': n_traces, 'n_events': n_events}))
