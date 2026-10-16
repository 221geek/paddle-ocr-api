# Paddle OCR API

> Microservice OCR asynchrone, CPU-first et auto-hébergeable pour images et PDF scannés.

Paddle OCR API extrait le texte de pages de journaux, conserve les blocs et leurs coordonnées,
puis renvoie un JSON stable. Il est prévu pour être appelé par un backend métier — par exemple
NestJS — qui reste responsable des archives, de la recherche et de l'indexation.

Le projet privilégie la maîtrise des ressources : une API FastAPI légère, Redis pour les jobs,
un worker OCR unique et PaddleOCR chargé une seule fois par processus.

## Fonctionnalités

- API REST versionnée sous `/v1` et documentation OpenAPI intégrée.
- Jobs asynchrones : `queued`, `processing`, `completed`, `failed` et `cancelled`.
- PNG, JPEG, WebP et PDF scannés multipages, rendus page par page.
- Texte, blocs OCR, polygones, scores et ordre de lecture estimé.
- PP-OCRv5 Mobile français sur CPU, chargé une fois par worker.
- Idempotence Redis atomique, leases de reprise et résultats avec expiration.
- Limites de taille, pages, pixels, file d'attente et durée de traitement.
- Authentification Bearer, logs JSON corrélés et métriques Prometheus.
- Image Docker non-root ; API, worker et Redis séparés.

### Hors périmètre

Le projet ne fait ni recherche, ni indexation, ni RAG, ni embeddings, ni persistance métier.
Il ne corrige pas le texte avec un LLM. L'ordre de lecture est une heuristique géométrique :
validez-le sur les pages multicolonnes de votre corpus avant tout usage métier critique.

## Architecture

```text
Client / backend métier
        | POST /v1/jobs
        v
FastAPI ── auth, validation, limites, statut
        |
        v
Redis ── jobs, idempotence, leases, résultats TTL
        |
        v
Worker unique ── PaddleOCR chargé une fois
        |
        +─ image : rotation EXIF minimale -> OCR
        +─ PDF   : rendu isolé -> une page -> OCR -> page suivante
        v
Résultat JSON versionné
```

```text
src/ocr_service/
├── api/              # Adaptateur HTTP FastAPI
├── application/      # Cas d'usage et interfaces (ports)
├── domain/           # Modèles et erreurs sans dépendance de framework
├── infrastructure/   # Redis, stockage, PDF, image, PaddleOCR, métriques
├── workers/          # Boucle de travail OCR
└── core/             # Configuration, logs et sécurité
```

## Prérequis et démarrage

- Docker Engine et Docker Compose v2 pour l'exécution recommandée.
- Ou Python 3.11 et [uv](https://docs.astral.sh/uv/) pour contribuer.
- Redis 7+ accessible par l'API et le worker.
- Pour commencer : 4 vCPU et 8 Go de RAM pour un worker OCR CPU isolé sont prudents.

```bash
git clone https://github.com/221geek/paddle-ocr-api.git
cd paddle-ocr-api
cp .env.example .env
```

Définissez un secret aléatoire d'au moins 16 caractères dans `.env` :

```dotenv
API_TOKEN=remplacez-moi-par-un-secret-aleatoire-et-suffisamment-long
```

Construisez et démarrez les trois services :

```bash
docker compose up --build
```

L'image initialise PaddleOCR pendant le build, en root, car PaddleX écrit une police dans
son propre répertoire de paquet. Les poids et le cache sont ensuite rendus accessibles à
`appuser`, l'utilisateur non-root qui exécute l'API et le worker. Le worker ne télécharge
donc pas de modèle au démarrage.

```bash
curl http://localhost:8000/health/live
curl http://localhost:8000/health/ready
```

`/health/ready` répond `503` tant que Redis ou le worker OCR n'est pas prêt.

### Développement sans Docker

```bash
uv sync --all-extras
uv run pytest
uv run ruff check .
uv run mypy src
```

Le backend `memory` est prévu pour les tests et l'exploration locale seulement : il ne fournit
ni durabilité, ni reprise, ni idempotence entre plusieurs processus.

```bash
export API_TOKEN='un-secret-de-developpement-tres-long'
export JOB_BACKEND=memory
uv run uvicorn ocr_service.main:app --reload
```

## Référence API

La documentation interactive est disponible sur [http://localhost:8000/docs](http://localhost:8000/docs)
et le schéma OpenAPI sur [http://localhost:8000/openapi.json](http://localhost:8000/openapi.json).

Tous les endpoints de jobs et de métriques requièrent :

```http
Authorization: Bearer <API_TOKEN>
```

Les erreurs applicatives sont structurées de manière stable :

```json
{
  "code": "payload_too_large",
  "message": "Upload exceeds the configured size limit",
  "request_id": "4c1570a1c6b248cd8f8a6083281f1fc5"
}
```

Le `request_id` est aussi renvoyé via l'en-tête `X-Request-ID`. Vous pouvez fournir votre
propre `X-Request-ID` pour le corréler à votre système appelant.

### Créer un job

```bash
curl --request POST http://localhost:8000/v1/jobs \
  --header "Authorization: Bearer <API_TOKEN>" \
  --header "Idempotency-Key: journal-1978-page-1" \
  --form archive_id=journal_1978 \
  --form document_id=journal_1978_0042 \
  --form page_number=1 \
  --form language=fr \
  --form include_boxes=true \
  --form file=@page-1.jpg
```

Réponse `202 Accepted` :

```json
{
  "job_id": "ocr_7b4e7b9f7ec44d3a8ed08d8e6bb51ef3",
  "status": "queued",
  "created_at": "2026-10-16T15:00:00Z",
  "status_url": "/v1/jobs/ocr_7b4e7b9f7ec44d3a8ed08d8e6bb51ef3"
}
```

| Champ | Requis | Description |
| --- | --- | --- |
| `file` | oui | PNG, JPEG, WebP ou PDF scanné |
| `archive_id` | oui | Identifiant de l'archive appelante |
| `document_id` | oui | Identifiant métier du document |
| `page_number` | image | Numéro de page, à partir de 1 |
| `page_start`, `page_end` | PDF | Bornes inclusives de pages, à partir de 1 |
| `language` | non | Actuellement fixé à `fr` |
| `model_profile` | non | Actuellement fixé à `mobile` |
| `detect_layout` | non | Réservé aux évolutions de segmentation |
| `include_boxes` | non | Retourne ou masque les polygones |

Le fichier est vérifié par signature, pas seulement via son extension ou son `Content-Type`.

### Référence d'objet interne

Pour éviter de faire transiter un grand document par HTTP, vous pouvez transmettre une référence
JSON vers un stockage interne autorisé :

```bash
curl --request POST http://localhost:8000/v1/jobs \
  --header "Authorization: Bearer <API_TOKEN>" \
  --header "Content-Type: application/json" \
  --data '{
    "archive_id": "journal_1978",
    "document_id": "journal_1978_0042",
    "page_number": 1,
    "object_key": "archives/journal_1978/page-1.jpg"
  }'
```

Les URL arbitraires sont volontairement refusées pour prévenir les SSRF. L'adaptateur fourni
résout uniquement des clés sous `OCR_OBJECT_STORE_DIR`, préfixées par
`OCR_ALLOWED_OBJECT_PREFIX`. Pour S3 ou un autre stockage, implémentez le port
`application/ports/blob_store.py`.

### Consulter un job et son résultat

`GET /v1/jobs/{job_id}` retourne l'état et la progression :

```json
{
  "job_id": "ocr_7b4e7b9f7ec44d3a8ed08d8e6bb51ef3",
  "status": "processing",
  "processed_pages": 2,
  "total_pages": 12,
  "created_at": "2026-10-16T15:00:00Z",
  "started_at": "2026-10-16T15:00:03Z",
  "completed_at": null,
  "processing_ms": null,
  "error_code": null
}
```

`GET /v1/jobs/{job_id}/result` répond :

| Réponse | Signification |
| --- | --- |
| `202` | Le travail n'est pas terminé |
| `200` | Résultat disponible |
| `404` | Job inconnu |
| `410` | Job terminé mais résultat expiré |

Extrait de résultat :

```json
{
  "schema_version": "1.0",
  "job_id": "ocr_7b4e7b9f7ec44d3a8ed08d8e6bb51ef3",
  "document_id": "journal_1978_0042",
  "engine": {
    "name": "paddleocr",
    "model": "PP-OCRv5_mobile",
    "version": "pinned-at-build"
  },
  "pages": [{
    "page_number": 1,
    "width": 2480,
    "height": 3508,
    "text": "Texte normalisé de la page…",
    "blocks": [{
      "id": "b1",
      "text": "Titre du journal",
      "confidence": 0.98,
      "polygon": [[120,80],[1100,80],[1100,210],[120,210]],
      "reading_order": 0
    }],
    "processing_ms": 1234,
    "warnings": []
  }]
}
```

Les coordonnées sont exprimées dans le repère de l'image OCR. Pour un PDF, il s'agit de
l'image rendue au DPI configuré. Les scores PaddleOCR sont informatifs, pas des probabilités
calibrées. `DELETE /v1/jobs/{job_id}` annule un job en attente ; une inférence en cours n'est
pas interrompue afin de ne pas laisser PaddleOCR dans un état incohérent.

### Endpoints techniques

| Endpoint | Authentification | Usage |
| --- | --- | --- |
| `GET /health/live` | non | Le processus HTTP répond |
| `GET /health/ready` | non | Redis et le worker OCR sont prêts |
| `GET /metrics` | Bearer | Métriques Prometheus ; réseau privé uniquement |

## Idempotence, retries et reprise

La clé de travail combine SHA-256 du contenu, pages demandées, paramètres OCR et version de
modèle. Si le client envoie `Idempotency-Key`, elle devient la clé de déduplication : utilisez
donc une clé unique pour chaque requête métier.

Redis utilise une opération Lua atomique pour empêcher les soumissions concurrentes de créer
deux jobs. Le worker conserve un lease lorsqu'il prend un job. Après un redémarrage, les leases
expirés sont remis en file jusqu'à deux fois ; le troisième échec produit le code stable
`worker_lease_expired`.

## Configuration

Copiez [`.env.example`](.env.example) vers `.env` en développement. En production, déclarez
ces valeurs comme secrets ou variables Coolify, sans jamais commiter `.env`.

| Variable | Défaut | Rôle |
| --- | --- | --- |
| `APP_ENV` | `development` | Environnement applicatif |
| `LOG_LEVEL` | `INFO` | Niveau des logs JSON |
| `API_TOKEN` | — | Secret Bearer, au moins 16 caractères |
| `REDIS_URL` | `redis://redis:6379/2` | Redis des jobs et résultats |
| `JOB_BACKEND` | `redis` | `redis` en production ; `memory` pour les tests |
| `OCR_MODEL_PROFILE` | `mobile` | Profil CPU public ; moteur volontairement fixe |
| `OCR_MAX_CONCURRENT_JOBS` | `1` | Un worker traite séquentiellement |
| `OCR_MAX_UPLOAD_MB` | `50` | Taille maximale d'un upload |
| `OCR_MAX_PAGES_PER_JOB` | `30` | Pages maximales par PDF/plage |
| `OCR_RENDER_DPI` | `250` | DPI PDF, entre 72 et 400 |
| `OCR_MAX_IMAGE_PIXELS` | `30000000` | Protection contre les images décompressées |
| `OCR_JOB_TIMEOUT_SECONDS` | `600` | Délai maximal d'un job |
| `OCR_RESULT_TTL_HOURS` | `72` | Conservation temporaire des résultats |
| `OCR_TEMP_DIR` | `/tmp/ocr` | Répertoire temporaire partagé |
| `OCR_MAX_QUEUED_JOBS` | `100` | Capacité de file avant un `429` |
| `OCR_ALLOWED_OBJECT_PREFIX` | `archives/` | Préfixe autorisé des références objet |
| `OCR_OBJECT_STORE_DIR` | `/tmp/ocr-objects` | Racine de l'adaptateur objet local |
| `PADDLE_NUM_THREADS` | `2` | Threads OpenMP/MKL de Paddle |

## Déploiement Coolify

[`compose.yaml`](compose.yaml) définit trois services :

1. **api** : FastAPI/Uvicorn ; n'initialise pas PaddleOCR.
2. **worker** : initialise PaddleOCR une fois et traite les jobs un par un.
3. **redis** : file, états, leases et résultats temporaires.

Procédure recommandée :

1. Connectez le dépôt GitHub et déployez la branche `main` avec Docker Compose.
2. Définissez au minimum `API_TOKEN`, `REDIS_URL`, `APP_ENV=production` et `JOB_BACKEND=redis`.
3. Placez Redis, API et worker sur un réseau interne.
4. N'exposez pas Redis ni `/metrics`. Si NestJS est le seul appelant, ne rendez pas l'API publique.
5. Commencez avec un worker et fixez des limites CPU/RAM cohérentes avec votre VPS.
6. Utilisez `/health/live` pour le processus et `/health/ready` pour la disponibilité applicative.

Le premier build nécessite l'accès sortant aux ressources PaddleOCR afin de précharger les
poids. Les démarrages ne les téléchargent pas. Si le serveur de build n'a pas d'accès sortant,
construisez l'image dans une CI autorisée puis poussez-la dans un registre privé.

## Sécurité et exploitation

- Ne stockez jamais `API_TOKEN` dans Git ou les logs.
- Les fichiers sont limités et inspectés par signature, dimensions et nombre de pages.
- Les PDF sont rendus page par page dans un processus isolé avec timeout.
- Les URL clientes sont refusées ; les références objet restent sous une racine contrôlée.
- Les résultats Redis expirent : archivez-les côté système métier si la conservation doit être durable.
- Les conteneurs applicatifs tournent sans root et avec système de fichiers applicatif en lecture seule.
- Les logs ne contiennent ni texte de document ni jeton d'accès.

| HTTP | Code | Situation |
| --- | --- | --- |
| `401` | `unauthorized` | Jeton absent ou incorrect |
| `413` | `payload_too_large` | Upload trop gros |
| `415` | `unsupported_media_type` | Fichier non pris en charge |
| `422` | `validation_error` / `invalid_input` | Paramètres ou document invalides |
| `429` | `queue_saturated` | File OCR pleine |
| `503` | `ocr_not_ready` / `service_unavailable` | Dépendance ou worker indisponible |

## Qualité OCR et benchmarks

Évaluez le service sur vos propres journaux : petits caractères, colonnes, titres, publicités,
pages inclinées, fonds jaunis et photos. Conservez des transcriptions manuelles et mesurez :

- **CER** — Character Error Rate.
- **WER** — Word Error Rate.
- Rappel des noms propres, dates et mots-clés critiques.
- Ordre de lecture multicolonne.
- p50/p95, pages/minute et RSS pour 20, 100 puis 1 000 pages.

Le script suivant charge le moteur une fois et produit un rapport JSON :

```bash
python scripts/benchmark.py /chemin/vers/corpus --output benchmark-report.json
```

Le rapport contient `pages`, `p50_ms`, `p95_ms`, `pages_per_minute` et `max_rss_kb`.
Conservez-le avec les mesures CER/WER ; ne communiquez pas un débit comme une garantie universelle.

## Développement et contribution

### Commandes de qualité

```bash
uv run pytest
uv run ruff format --check .
uv run ruff check .
uv run mypy src
```

Les tests couvrent les contrats HTTP, l'authentification, les limites de fichier, l'idempotence
et le mapping des résultats PaddleOCR. Ajoutez des fixtures représentatives avant une campagne
d'intégration OCR et de charge.

### Dépendances reproductibles

[`uv.lock`](uv.lock) verrouille la résolution. [`requirements.lock`](requirements.lock) est
exporté avec les hashes et utilisé par l'image Docker.

```bash
uv lock
uv export --frozen --no-dev --no-emit-project --format requirements-txt --output-file requirements.lock
```

Les hooks Ruff sont déclarés dans [`.pre-commit-config.yaml`](.pre-commit-config.yaml).

### Contribuer

1. Ouvrez une issue décrivant le besoin ou le bug.
2. Créez une branche ciblée et ajoutez les tests nécessaires.
3. Exécutez les commandes de qualité.
4. Ouvrez une pull request concise et documentez tout impact opérationnel.

Les prochaines améliorations naturelles sont un adaptateur S3 signé, une persistance durable
des résultats, un corpus d'intégration OCR, une campagne de charge et une segmentation de
colonnes validée sur des données réelles.

## Licence

Ce dépôt ne contient pas encore de licence. Avant toute réutilisation, publication de paquet
ou contribution externe, le mainteneur doit ajouter une licence explicite — par exemple MIT,
Apache-2.0 ou GPL-3.0 selon l'intention du projet.

