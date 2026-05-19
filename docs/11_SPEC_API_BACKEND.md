# Specification API backend

## 1. Objectif

Ce document definit uniquement l'API backend REST du MVP DocTranslate AI.

L'API permet au frontend de :

- verifier que le backend est disponible ;
- uploader un PDF ;
- lancer le traitement ;
- suivre le statut ;
- recuperer les metadonnees du resultat ;
- consulter le rapport ;
- telecharger le DOCX ;
- telecharger le PDF si l'export optionnel est disponible ;
- consulter la representation intermediaire pour debug MVP.

## 2. Principes API

- Utiliser FastAPI.
- Utiliser JSON pour les reponses, sauf pour les telechargements de fichiers.
- Utiliser `{document_id}` dans les routes, avec un nom de parametre explicite.
- Ne jamais exposer les chemins locaux du serveur.
- Ne jamais exposer les cles API IA.
- Valider toutes les entrees avec des schemas Pydantic.
- Retourner des erreurs standardisees.
- Lancer le traitement avec `FastAPI BackgroundTasks` ou un mecanisme simplifie equivalent.
- Ne pas introduire Celery, Redis ou RabbitMQ dans le MVP.
- Le statut peut etre stocke en memoire ou dans `storage/tmp/{document_id}/status.json`.
- Le DOCX est le livrable prioritaire.
- L'export PDF est optionnel et non bloquant pour la validation du MVP.

Limites API du MVP :

- PDF numerique uniquement ;
- texte selectionnable obligatoire ;
- maximum 10 pages ;
- maximum 10 Mo ;
- tableaux simples uniquement ;
- documents a une colonne en priorite ;
- pas de scans complexes ;
- pas de formulaires PDF complexes ;
- pas de remplacement de texte dans les images.

## 3. Endpoints REST

Endpoints obligatoires :

- `GET /api/health`
- `POST /api/documents/upload`
- `POST /api/documents/{document_id}/process`
- `GET /api/documents/{document_id}/status`
- `GET /api/documents/{document_id}/result`
- `GET /api/documents/{document_id}/report`
- `GET /api/documents/{document_id}/download/docx`
- `GET /api/documents/{document_id}/download/pdf`
- `GET /api/documents/{document_id}/intermediate`

`GET /api/documents/{document_id}/intermediate` est reserve au debug MVP. Ce n'est pas une fonctionnalite produit principale.

## 4. Schemas request/response

### GET /api/health

Verifie que l'API est disponible.

Response 200 :

```json
{
  "status": "ok",
  "service": "doctranslate-api"
}
```

### POST /api/documents/upload

Upload d'un PDF.

Request :

- `multipart/form-data`
- champ `file`

Validations :

- extension `.pdf` ;
- MIME `application/pdf` ;
- signature PDF valide ;
- taille maximale 10 Mo ;
- maximum 10 pages ;
- texte selectionnable.

La validation du texte selectionnable peut etre effectuee pendant l'upload avec une extraction texte minimale via PyMuPDF. Si aucun texte exploitable n'est extrait, l'API doit retourner `422 PDF_NO_SELECTABLE_TEXT`.

Response 201 :

```json
{
  "document_id": "doc_123",
  "filename": "contract.pdf",
  "file_size_mb": 2.4,
  "page_count": 4,
  "status": "uploaded"
}
```

### POST /api/documents/{document_id}/process

Lance le traitement en arriere-plan.

Si un traitement est deja en cours pour le meme document, l'API doit retourner `409 PROCESS_ALREADY_RUNNING` au lieu de lancer un second job.

Request :

```json
{
  "target_language": "fr",
  "glossary": [
    {
      "source": "agreement",
      "target": "contrat",
      "required": true
    }
  ]
}
```

Response 202 :

```json
{
  "job_id": "job_001",
  "document_id": "doc_123",
  "status": "queued",
  "translation_provider": "mock"
}
```

### GET /api/documents/{document_id}/status

Retourne l'etat courant du traitement.

Response 200 :

```json
{
  "document_id": "doc_123",
  "job_id": "job_001",
  "status": "processing",
  "current_step": "translation",
  "progress": 65,
  "updated_at": "2026-05-19T10:03:00Z",
  "error": null
}
```

### GET /api/documents/{document_id}/result

Retourne les metadonnees du resultat.

Response 200 :

```json
{
  "document_id": "doc_123",
  "status": "completed",
  "available_files": {
    "docx": true,
    "pdf": false
  },
  "confidence_score": 0.82,
  "message": "Le document DOCX est disponible. L'export PDF n'est pas active pour ce traitement."
}
```

### GET /api/documents/{document_id}/report

Retourne le rapport de validation.

Response 200 :

```json
{
  "document_id": "doc_123",
  "confidence_score": 0.82,
  "issues": [
    {
      "id": "issue_001",
      "severity": "medium",
      "type": "text_overflow_risk",
      "page_number": 2,
      "block_id": "block_010",
      "message": "La traduction est nettement plus longue que le texte source.",
      "suggestion": "Verifier la mise en page dans le DOCX."
    }
  ]
}
```

### GET /api/documents/{document_id}/download/docx

Telecharge le fichier DOCX traduit.

Si le traitement n'est pas termine ou si le DOCX n'est pas encore disponible, l'API doit retourner `409 RESULT_NOT_READY`.

Response 200 :

- `Content-Type: application/vnd.openxmlformats-officedocument.wordprocessingml.document`
- fichier binaire `translated.docx`

### GET /api/documents/{document_id}/download/pdf

Telecharge le PDF traduit si l'export PDF est disponible.

Dans le MVP, cet export est optionnel. Si le PDF n'est pas genere, l'API peut retourner une erreur controlee.

Exemple response 501 :

```json
{
  "error": {
    "code": "PDF_EXPORT_NOT_ENABLED",
    "message": "L'export PDF est optionnel et n'est pas active pour ce MVP.",
    "details": null
  }
}
```

### GET /api/documents/{document_id}/intermediate

Retourne la representation intermediaire JSON pour debug MVP.

Cet endpoint aide a verifier l'extraction, l'ordre de lecture et les blocs. Il ne doit pas etre mis en avant comme fonctionnalite produit.

Response 200 :

```json
{
  "document_id": "doc_123",
  "source_language": "en",
  "target_language": "fr",
  "domain": "general",
  "pages": [
    {
      "page_number": 1,
      "width": 595,
      "height": 842,
      "blocks": []
    }
  ],
  "warnings": []
}
```

## 5. Gestion des statuts

Statuts possibles :

- `uploaded`
- `queued`
- `processing`
- `completed`
- `failed`
- `expired`

Etapes possibles :

- `upload`
- `analysis`
- `extraction`
- `domain_detection`
- `translation`
- `terminology_check`
- `reconstruction`
- `validation_report`
- `done`

Strategie MVP :

1. `POST /api/documents/upload` cree `document_id`.
2. `POST /api/documents/{document_id}/process` met le job en `queued`.
3. Le backend lance le pipeline via `FastAPI BackgroundTasks`.
4. Le backend met a jour le statut a chaque etape.
5. Le frontend fait du polling sur `/status`.
6. Le job passe en `completed` ou `failed`.

## 6. Gestion des erreurs

Format standard :

```json
{
  "error": {
    "code": "INVALID_FILE_TYPE",
    "message": "Le fichier doit etre un PDF.",
    "details": null
  }
}
```

Codes principaux :

- `INVALID_FILE_TYPE`
- `FILE_TOO_LARGE`
- `PDF_TOO_MANY_PAGES`
- `PDF_NO_SELECTABLE_TEXT`
- `DOCUMENT_NOT_FOUND`
- `DOCUMENT_EXPIRED`
- `PROCESS_ALREADY_RUNNING`
- `RESULT_NOT_READY`
- `PDF_EXTRACTION_FAILED`
- `TRANSLATION_FAILED`
- `RECONSTRUCTION_FAILED`
- `REPORT_NOT_FOUND`
- `DOCX_NOT_FOUND`
- `PDF_EXPORT_NOT_ENABLED`
- `INTERNAL_ERROR`

Exemple document introuvable :

```json
{
  "error": {
    "code": "DOCUMENT_NOT_FOUND",
    "message": "Le document demande est introuvable.",
    "details": {
      "document_id": "doc_123"
    }
  }
}
```

### Correspondance codes metier / statuts HTTP

| Code metier | Statut HTTP |
| --- | --- |
| `INVALID_FILE_TYPE` | `400` |
| `FILE_TOO_LARGE` | `413` |
| `PDF_TOO_MANY_PAGES` | `400` |
| `PDF_NO_SELECTABLE_TEXT` | `422` |
| `DOCUMENT_NOT_FOUND` | `404` |
| `DOCUMENT_EXPIRED` | `410` |
| `PROCESS_ALREADY_RUNNING` | `409` |
| `RESULT_NOT_READY` | `409` |
| `PDF_EXPORT_NOT_ENABLED` | `501` |
| `INTERNAL_ERROR` | `500` |

## 7. Securite API

- Limiter l'upload a 10 Mo.
- Refuser les fichiers non PDF.
- Verifier que le PDF contient du texte selectionnable.
- Ne pas exposer les chemins `storage/tmp`.
- Ne pas logger le contenu complet des documents.
- Ne pas retourner de stack trace au frontend.
- Stocker les secrets dans `.env`.
- Ne jamais exposer les cles IA cote frontend.
- Configurer CORS uniquement pour le domaine frontend.
- Supprimer automatiquement ou manuellement les fichiers apres 24 heures.

## 8. Tests API a prevoir

- `GET /api/health` retourne `200`.
- Upload PDF valide.
- Refus fichier non PDF.
- Refus fichier de plus de 10 Mo.
- Refus PDF de plus de 10 pages.
- Refus ou erreur controlee pour PDF sans texte selectionnable.
- Lancement traitement sur document existant.
- Erreur sur document inexistant.
- Polling statut pendant traitement.
- Recuperation resultat apres completion.
- Recuperation rapport.
- Telechargement DOCX.
- Export PDF non active retourne une erreur controlee.
- Endpoint `/intermediate` retourne une representation JSON valide pour debug.
