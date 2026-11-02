#!/usr/bin/env python3
"""
Lecture d'une copie à 4 voix en trois requêtes, comme le fait le téléphone sur un hébergement limité à 5 minutes par
requête (Vercel) : /api/lire (étape 1) → /api/lire/suite (étape 2) → /api/recreer (audio). Vérifie le pack reçu.
Usage : test_etapes.py <adresse> <code d'accès> <fichier.pdf>
"""
import base64, io, json, sys, uuid, zipfile
import urllib.request

base, code, pdf = sys.argv[1:4]


def post(path, fields, files):
    boundary = uuid.uuid4().hex
    body = io.BytesIO()
    for k, v in fields.items():
        body.write(f'--{boundary}\r\nContent-Disposition: form-data; name="{k}"\r\n\r\n{v}\r\n'.encode())
    for k, name, data, ctype in files:
        body.write(f'--{boundary}\r\nContent-Disposition: form-data; name="{k}"; filename="{name}"\r\nContent-Type: {ctype}\r\n\r\n'.encode())
        body.write(data)
        body.write(b'\r\n')
    body.write(f'--{boundary}--\r\n'.encode())
    req = urllib.request.Request(base + path, data=body.getvalue(), headers={
        'Content-Type': f'multipart/form-data; boundary={boundary}', 'Authorization': f'Pupitre {code}'})
    last = None
    with urllib.request.urlopen(req, timeout=900) as r:
        for line in r:
            msg = json.loads(line)
            if msg.get('ping'):
                continue
            if msg.get('error'):
                sys.exit(f'{path} : {msg["error"]}')
            last = msg
    print(path, '→', last.get('status'), flush=True)
    return last


data = open(pdf, 'rb').read()
a = post('/api/lire', {'titre': 'Essai', 'disposition': 'satb'}, [('file', 'essai.pdf', data, 'application/pdf')])
assert a['status'] == 'etape', f"étape 1 attendue, reçu {a['status']}"
b = post('/api/lire/suite', {}, [('etat', 'etat.zip', base64.b64decode(a['etat']), 'application/zip')])
assert b['status'] == 'partition', f"partition attendue, reçu {b['status']}"
pages = [('pages', f'page-{i + 1:02d}.png', base64.b64decode(p), 'image/png') for i, p in enumerate(a['pages'])]
c = post('/api/recreer', {'titre': 'Essai', 'timbre': 'choeur'}, [('file', 'score.musicxml', base64.b64decode(b['partition']), 'application/xml')] + pages)
z = zipfile.ZipFile(io.BytesIO(base64.b64decode(c['pack'])))
pack = json.loads(z.read('pack.json'))
voices = [v['name'] for v in pack['manifest']['voices']]
print('voix :', voices, '· pages :', [n for n in z.namelist() if n.startswith('pages/')])
assert len(voices) == 4, 'quatre voix attendues'
assert any(n.startswith('pages/') for n in z.namelist()), 'pages de la copie absentes du pack'
print('Lecture en trois requêtes réussie')
