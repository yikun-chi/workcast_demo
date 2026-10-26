"""Download all files of a Dataverse dataset listed in a saved metadata JSON.
Usage: python -I download.py <metadata.json> <outdir>
Downloads originals for tabular (Stata) files, plus the Dataverse .tab derivative; verifies MD5 of the ingested file.
"""
import json, sys, os, hashlib, subprocess, urllib.request, time
meta, outdir = sys.argv[1], sys.argv[2]
d = json.load(open(meta))['data']['latestVersion']
os.makedirs(outdir, exist_ok=True)
manifest = []
def md5(p):
    h = hashlib.md5()
    with open(p, 'rb') as f:
        for ch in iter(lambda: f.read(1 << 20), b''):
            h.update(ch)
    return h.hexdigest()
def fetch(url, dest):
    if os.path.exists(dest) and os.path.getsize(dest) > 0:
        return
    for attempt in range(4):
        r = subprocess.run(['curl', '-sSL', '--fail', '--retry', '2', '-o', dest, url], capture_output=True, text=True)
        if r.returncode == 0 and os.path.getsize(dest) > 0:
            return
        print('retry', url, r.stderr.strip(), file=sys.stderr); time.sleep(3)
    raise SystemExit(f'failed {url}')
for f in d['files']:
    df = f['dataFile']; fid = df['id']; label = f['label']
    sub = (f.get('directoryLabel') or '').replace('Replication_nature_final', '').strip('/')
    tgt_dir = os.path.join(outdir, sub) if sub else outdir
    os.makedirs(tgt_dir, exist_ok=True)
    rec = dict(name=label, directory=f.get('directoryLabel'), file_id=fid, dataverse_bytes=df['filesize'],
               dataverse_md5=df['checksum']['value'], content_type=df['contentType'], restricted=f.get('restricted'),
               original_format=df.get('originalFileFormat'), original_bytes=df.get('originalFileSize'))
    safe = label.replace('~$', 'tilde_dollar_')
    dest = os.path.join(tgt_dir, safe)
    fetch(f'https://dataverse.harvard.edu/api/access/datafile/{fid}', dest)
    rec['local_tab_path'] = dest; rec['local_tab_bytes'] = os.path.getsize(dest); rec['local_tab_md5'] = md5(dest)
    rec['md5_match'] = rec['local_tab_md5'] == rec['dataverse_md5']
    if df.get('originalFileFormat'):
        od = os.path.join(tgt_dir, os.path.splitext(safe)[0] + '.dta')
        fetch(f'https://dataverse.harvard.edu/api/access/datafile/{fid}?format=original', od)
        rec['local_original_path'] = od; rec['local_original_bytes'] = os.path.getsize(od); rec['local_original_md5'] = md5(od)
        rec['original_bytes_match'] = rec['local_original_bytes'] == df.get('originalFileSize')
    manifest.append(rec)
    print(label, fid, rec['md5_match'], rec.get('original_bytes_match'))
json.dump(manifest, open(os.path.join(outdir, '_download_manifest.json'), 'w'), indent=1)
