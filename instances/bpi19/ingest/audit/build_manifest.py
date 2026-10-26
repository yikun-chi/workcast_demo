"""Build machine-readable manifest.
Usage: build_manifest.py <figshare_article.json> <gz_path> <xes_path> <normalized_dir> <analysis.json> <out_manifest.json>
"""
import sys, json, hashlib, os, html, re
import pandas as pd
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]

def repo_path(value):
    return Path(os.path.relpath(value, ROOT)).as_posix()
art_p, gz_p, xes_p, nd, an_p, out_p = sys.argv[1:7]
def sha256(p):
    h = hashlib.sha256()
    with open(p, 'rb') as f:
        for b in iter(lambda: f.read(1 << 24), b''):
            h.update(b)
    return h.hexdigest()
def md5(p):
    h = hashlib.md5()
    with open(p, 'rb') as f:
        for b in iter(lambda: f.read(1 << 24), b''):
            h.update(b)
    return h.hexdigest()
art = json.load(open(art_p)); A = json.load(open(an_p)); S = json.load(open(os.path.join(nd, 'schema.json')))
f0 = art['files'][0]
desc = re.sub('<[^>]+>', '', html.unescape(art['description']))
man = {
    'dataset': 'BPI Challenge 2019', 'retrieval_date': '2026-10-24',
    'figshare_article_id': art['id'], 'figshare_api_url': 'https://api.figshare.com/v2/articles/12715853',
    'doi': art['doi'], 'version': art.get('version'), 'published_date': art.get('published_date'), 'authors': [a['full_name'] for a in art.get('authors', [])],
    'license': art['license'], 'publisher_description': desc,
    'publisher_claims': {'purchase_documents': 76349, 'cases': 251734, 'events': 1595923, 'activities': 42, 'users_total': 627, 'human_users': 607, 'batch_users': 20},
    'canonical_file': {'name': f0['name'], 'size_bytes': f0['size'], 'download_url': f0['download_url'], 'figshare_computed_md5': f0['computed_md5'], 'mimetype': f0['mimetype']},
    'acquisition_note': 'figshare ndownloader returned HTTP 202/504 for >40 min on 2026-10-24 (status page: "Botnet flood" incident same day); data.4tu.nl unreachable from this host. Byte-identical copy obtained from the official ICPM 2019 conference site; md5 matches figshare computed_md5.',
    'retrieved_file': {'url': 'https://icpmconference.org/2019/wp-content/uploads/sites/6/2019/01/log_IEEE.xes_.gz', 'local_path': repo_path(gz_p), 'size_bytes': os.path.getsize(gz_p), 'sha256': sha256(gz_p), 'format': 'gzip-compressed XES 1849.2016 XML'},
    'decompressed_file': {'local_path': repo_path(xes_p), 'size_bytes': os.path.getsize(xes_p), 'sha256': sha256(xes_p), 'md5': md5(xes_p), 'md5_matches_figshare': None},
    'counts': {'traces': S['n_traces'], 'events': S['n_events'], 'activities': A['n_activities'], 'distinct_users_excl_none_missing': A['n_distinct_users_total'], 'batch_users': A['n_batch_users'], 'human_users': A['n_human_users'], 'purchasing_documents': A.get('purchasing_documents', {}).get('n_distinct'), 'variants': A['n_variants']},
    'timestamp_min': A['ts_min'], 'timestamp_max': A['ts_max'],
    'xes_log_meta': S['log_meta'],
    'trace_attributes': {k: {'xes_type': list(v['types'].keys()), 'traces_carrying': v['count'], 'coverage': v['count'] / S['n_traces'], 'null_or_empty_rate': A['case_null_rate'].get(k)} for k, v in S['trace_keys'].items()},
    'event_attributes': {k: {'xes_type': list(v['types'].keys()), 'events_carrying': v['count'], 'coverage': v['count'] / S['n_events'], 'null_or_empty_rate': A['event_null_rate'].get(k)} for k, v in S['event_keys'].items()},
    'normalized_output': {'events_parquet_dir': repo_path(os.path.join(nd, 'events.parquet')), 'partitioning': 'hive month=YYYY-MM on event time:timestamp (UTC)', 'cases_parquet': repo_path(os.path.join(nd, 'cases.parquet')), 'event_columns': list(pd.read_parquet(os.path.join(nd, 'events.parquet', sorted(os.listdir(os.path.join(nd, 'events.parquet')))[0])).columns), 'case_columns': list(pd.read_parquet(os.path.join(nd, 'cases.parquet')).columns)},
}
man['decompressed_file']['md5_matches_figshare'] = man['decompressed_file']['md5'] == f0['computed_md5']
json.dump(man, open(out_p, 'w'), indent=2)
print('manifest written', out_p)
