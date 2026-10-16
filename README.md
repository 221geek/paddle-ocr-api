# Paddle OCR API

Service OCR asynchrone CPU-first pour pages de journaux scannées. FastAPI n'initialise
pas PaddleOCR : un unique worker charge le modèle une fois, consomme les jobs Redis et
traite les PDF page par page.

## Démarrage local

```bash
cp .env.example .env
# définir API_TOKEN dans .env
docker compose up --build
```

L'API est disponible sur `http://localhost:8000`; les métriques sont privées et exigent
le même jeton que l'API (ou `PROMETHEUS_METRICS_TOKEN`). Le premier démarrage du worker
doit utiliser des poids PaddleOCR déjà inclus dans l'image ou montés dans le cache :
aucun téléchargement de modèle ne doit être autorisé en production.

L'image charge donc PaddleOCR **pendant le build, en root**, car PaddleX écrit aussi une
police dans son propre répertoire de paquet. Le cache de modèles est ensuite copié vers
l'utilisateur non-root qui exécute l'API et le worker.

```bash
curl -X POST http://localhost:8000/v1/jobs \
  -H "Authorization: Bearer $API_TOKEN" \
  -H "Idempotency-Key: journal-1978-page-1" \
  -F archive_id=journal_1978 -F document_id=journal_1978_0042 \
  -F page_number=1 -F file=@page-1.jpg
```

Le résultat se lit via `GET /v1/jobs/{job_id}/result`. Une même clé d'idempotence et des
paramètres équivalents renvoient le même job, sans retraitement. Le mode `JOB_BACKEND=memory`
est réservé au développement et aux tests ; Coolify doit utiliser Redis et des services
`api` / `worker` séparés.

## Contrat et exploitation

- `POST /v1/jobs` accepte une image ou un PDF multipart, ou une référence `object_key`
  JSON sous le préfixe autorisé. Les URL sont volontairement interdites.
- `GET /v1/jobs/{id}`, `GET /v1/jobs/{id}/result`, `DELETE /v1/jobs/{id}`.
- `GET /health/live`, `GET /health/ready`, `GET /metrics`.
- Les erreurs ont toujours la forme `{ "code", "message", "request_id" }`.

Fixez les limites mémoire/CPU dans Coolify en fonction du VPS. Commencez avec un seul
worker et une seule inférence. Les coordonnées sont celles de l'image OCR rendue : pour
un PDF, cela correspond au rendu au DPI configuré. `reading_order` reste une estimation
géométrique à valider sur le corpus de journaux.

## Qualité

```bash
pip install -e '.[dev]'
pytest
ruff check .
```

`uv.lock` et `requirements.lock` verrouillent respectivement la résolution et les artefacts
utilisés par l'image Docker. Après un changement de dépendances, exécutez `uv lock` puis
`uv export --frozen --no-dev --no-emit-project --format requirements-txt --output-file requirements.lock`.

Avant production, validez la paire de versions Paddle dans votre image, mesurez CER/WER,
l'ordre de lecture et RSS/p95 sur 20, 100 puis 1 000 pages représentatives.

Le script `scripts/benchmark.py` produit p50, p95, pages/minute et RSS maximal pour un
corpus d'images. Conservez ce rapport avec les mesures CER/WER manuelles : le débit n'est
pas annoncé comme une garantie, car il dépend des scans et du CPU.

