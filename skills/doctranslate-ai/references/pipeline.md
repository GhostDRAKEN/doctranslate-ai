# Pipeline technique DocTranslate AI

## Vue generale

DocTranslate AI transforme un PDF numerique anglais en PDF traduit francais via une chaine de traitement backend simple et demonstrable.

```text
PDF source
-> validation upload
-> stockage temporaire
-> extraction PyMuPDF
-> intermediate.json
-> traduction par blocs
-> validation minimale
-> overlay PDF
-> result.pdf
```

## 1. Upload

Endpoint :

```text
POST /api/documents/upload
```

Le backend verifie :

- type MIME PDF ;
- extension `.pdf` ;
- taille maximale 10 Mo ;
- maximum 10 pages ;
- presence de texte selectionnable.

Si le fichier est valide, il est stocke dans :

```text
backend/storage/tmp/{document_id}/source.pdf
```

## 2. Traitement asynchrone simplifie

Endpoint :

```text
POST /api/documents/{document_id}/process
```

Le MVP utilise FastAPI `BackgroundTasks`, sans Celery, Redis ou RabbitMQ.

Le statut est suivi via :

```text
GET /api/documents/{document_id}/status
```

Statuts principaux :

- `uploaded`
- `queued`
- `processing`
- `completed`
- `failed`

## 3. Extraction PDF

PyMuPDF extrait :

- pages ;
- dimensions ;
- lignes et blocs textuels ;
- bbox ;
- styles approximatifs ;
- images natives simples.

Le resultat est sauvegarde dans :

```text
backend/storage/tmp/{document_id}/intermediate.json
```

Les blocs importants sont :

- `title`
- `paragraph`
- `list_item`
- `caption`
- `footnote`
- `image`
- `header`
- `footer`
- `unknown`

## 4. Traduction

Le service de traduction utilise deux modes :

- `MockTranslationProvider` pour tests et developpement ;
- `LLMTranslationProvider` pour traduction reelle via fournisseur externe.

Les blocs traduits doivent etre des blocs logiques complets, pas des fragments isoles.

Blocs traduisibles :

- `title`
- `paragraph`
- `list_item`
- `caption`
- `footnote`

Blocs ignores ou non envoyes au LLM :

- `image`
- `header`
- `footer`
- `unknown`
- `table`

## 5. Validation avant PDF

Avant generation PDF, le backend verifie :

- au moins un bloc traduit ;
- pas trop de blocs textuels avec `translated_text` vide ;
- pas de traduction manifestement incomplete.

Erreurs possibles :

- `TRANSLATION_NOT_READY`
- `TRANSLATION_INCOMPLETE`

## 6. Generation PDF par overlay

Endpoint :

```text
POST /api/documents/{document_id}/generate-pdf
```

Le service ouvre le PDF source, masque les zones de texte anglais avec des rectangles blancs, puis insere le texte traduit aux coordonnees approximatives.

Les images, fonds et formes restent ceux du PDF original.

Sortie :

```text
backend/storage/tmp/{document_id}/result.pdf
```

Telechargement :

```text
GET /api/documents/{document_id}/download/pdf
```

## 7. DOCX

Le DOCX reste disponible comme sortie secondaire :

```text
POST /api/documents/{document_id}/generate-docx
GET  /api/documents/{document_id}/download/docx
```

Le produit met maintenant le PDF traduit en sortie principale.
