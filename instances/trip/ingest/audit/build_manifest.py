"""Build machine-readable manifest. Usage: python -I build_manifest.py <download_manifest.json> <inventory.json> <dataset_meta.json> <pzqob1_meta.json> <out.json>"""
import json, sys
dl, inv, meta, pz, out = sys.argv[1:6]
dl = json.load(open(dl)); inv = json.load(open(inv)); meta = json.load(open(meta))['data']; pz = json.load(open(pz))['data']
v = meta['latestVersion']
def inv_for(name, directory):
    rel = (directory or '').replace('Replication_nature_final', '').strip('/')
    key = f"{rel}/{name}".strip('/').replace('.tab', '.dta')
    return inv.get(key)
files = []
for r in dl:
    i = inv_for(r['name'], r['directory'])
    files.append(dict(name=r['name'], directory=r['directory'], dataverse_file_id=r['file_id'], content_type=r['content_type'],
        restricted=r['restricted'], dataverse_bytes_ingested=r['dataverse_bytes'], dataverse_md5=r['dataverse_md5'],
        original_format=r['original_format'], original_bytes=r['original_bytes'],
        local_tab_md5=r['local_tab_md5'], local_tab_bytes=r['local_tab_bytes'],
        local_original_md5=r.get('local_original_md5'), local_original_bytes=r.get('local_original_bytes'),
        md5_verified=(r.get('local_original_md5') == r['dataverse_md5']) if r.get('local_original_md5') else r['md5_match'],
        md5_note='Dataverse MD5 refers to the original (.dta) upload for ingested tabular files; the .tab derivative has a different MD5' if r.get('local_original_md5') else 'MD5 of the file as served',
        row_count=i['n_rows'] if i else None, columns=[c['name'] for c in i['columns']] if i else None,
        column_labels={c['name']: c.get('label','') for c in i['columns']} if i else None,
        person_id_column=None, license_terms_flags=dict(license='CC BY 4.0', terms_of_use=None, terms_of_access=None, guestbook_required=False, file_access_request_enabled_on_dataset=v.get('fileAccessRequest'))))
man = dict(dataset=dict(doi='doi:10.7910/DVN/6X4ZZL', persistent_url=meta['persistentUrl'], title='Replication Data for: Hybrid working from home improves retention without damaging performance',
        version=f"{v['versionNumber']}.{v['versionMinorNumber']}", version_state=v['versionState'], release_time=v['releaseTime'], publication_date=meta['publicationDate'],
        license=v['license'], terms_of_use=v.get('termsOfUse'), terms_of_access=v.get('termsOfAccess'), file_access_request=v.get('fileAccessRequest'),
        retrieval_date='2026-10-24', retrieval_method='Dataverse native API; curl -L follows the 303 to a pre-signed S3 URL', n_files=len(files),
        total_ingested_bytes=sum(f['dataverse_bytes_ingested'] for f in files), total_original_bytes=sum((f['original_bytes'] or 0) for f in files)),
    files=files,
    stable_person_identifier='NONE in any file (0 of 37 data files have an id-like or unique column)',
    calibration_source_PZQOB1=dict(doi='doi:10.7910/DVN/PZQOB1', title='Replication Data for: Does working from home work? Evidence from a Chinese experiment (QJE 2015)',
        version=f"{pz['latestVersion']['versionNumber']}.{pz['latestVersion']['versionMinorNumber']}", license=pz['latestVersion']['license'], release_time=pz['latestVersion']['releaseTime'],
        files=[dict(name=f['label'], dataverse_file_id=f['dataFile']['id'], bytes=f['dataFile']['filesize'], md5=f['dataFile']['checksum']['value'], restricted=f['restricted'],
                    content_type=f['dataFile']['contentType']) for f in pz['latestVersion']['files']],
        access_note='API download of WFH.zip returned HTTP 400: "You may not download this file without the required Guestbook response for guestbookID 269." Not downloaded; zip contents not listed. restricted=false, fileAccessRequest=false.'))
json.dump(man, open(out, 'w'), indent=1)
print('files', len(files), 'ingested bytes', man['dataset']['total_ingested_bytes'], 'original bytes', man['dataset']['total_original_bytes'])
