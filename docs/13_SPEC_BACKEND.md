# Specification backend

## Objectif

Definir la structure backend FastAPI et les services necessaires au pipeline documentaire.

## Structure projet souhaitee

```text
backend/
  app/
    main.py
    api/
      documents.py
    core/
      config.py
      errors.py
      logging.py
    schemas/
      document.py
      glossary.py
      job.py
      report.py
    services/
      pdf_service.py
      extraction_service.py
      translation_service.py
      glossary_service.py
      reconstruction_service.py
      validation_service.py
      storage_service.py
    storage/
      tmp/
    utils/
      ids.py
      text.py
```

## Modules Python

### `main.py`

- Initialisation FastAPI.
- Configuration CORS.
- Inclusion des routes.
- Handlers d'erreur.

### `api/documents.py`

- Routes upload, process, status, result, report, download.
- Validation entree.
- Appel aux services.
- Pas de logique PDF ou IA directe.

### `core/config.py`

- Lecture `.env`.
- Taille max upload.
- Repertoire stockage.
- Configuration fournisseur IA.
- Timeouts.

### `core/errors.py`

- Exceptions metier.
- Mapping exception -> reponse API.

## Schemas Pydantic

- `DocumentUploadResponse`
- `ProcessDocumentRequest`
- `DocumentStatusResponse`
- `DocumentResultResponse`
- `GlossaryTerm`
- `ValidationReport`
- `ValidationIssue`
- `DocumentIntermediate`
- `Page`
- `Block`
- `TableBlock`
- `ImageBlock`

## Services

### `pdf_service.py`

Responsabilites :

- verifier que le PDF est lisible ;
- lire les metadonnees ;
- detecter PDF protege ;
- fournir un handle propre a l'extraction.

### `extraction_service.py`

Responsabilites :

- extraire texte, styles, coordonnees ;
- detecter blocs ;
- extraire images ;
- detecter tableaux simples ;
- produire `DocumentIntermediate`.

### `translation_service.py`

Responsabilites :

- abstraire le fournisseur de traduction ;
- utiliser `MockTranslationProvider` en priorite pour le MVP ;
- permettre `LLMTranslationProvider` uniquement apres validation du pipeline complet ;
- construire les prompts ;
- envoyer les lots ;
- valider les reponses ;
- gerer retries et erreurs.

### `glossary_service.py`

Responsabilites :

- valider le glossaire ;
- filtrer les termes pertinents ;
- controler la terminologie apres traduction ;
- produire des alertes.

### `reconstruction_service.py`

Responsabilites :

- generer le DOCX ;
- inserer titres, paragraphes, tableaux, images ;
- retourner les chemins internes des artefacts.

### `validation_service.py`

Responsabilites :

- agreger les warnings ;
- detecter risques ;
- calculer score de confiance ;
- generer rapport JSON.

### `storage_service.py`

Responsabilites :

- creer dossiers temporaires ;
- sauvegarder fichiers ;
- retrouver artefacts ;
- nettoyer fichiers expires.

## Pipeline de traitement

1. Charger metadonnees document.
2. Analyser le PDF.
3. Extraire representation intermediaire.
4. Detecter domaine simplement.
5. Valider/appliquer glossaire.
6. Traduire les blocs.
7. Controler terminologie.
8. Reconstruire DOCX.
9. Generer rapport.
10. Mettre le statut a `completed`.

## Traitement asynchrone

Pour le MVP :

- traitement en tache de fond FastAPI possible ;
- stockage de statut en memoire ou fichier JSON.
- ne pas utiliser Celery, Redis ou RabbitMQ dans le MVP.

Evolution :

- file de jobs avec Celery/RQ ;
- Redis pour statuts ;
- worker separe.

## Gestion des fichiers

Tous les fichiers du MVP sont regroupes dans :

```text
storage/tmp/{document_id}/
  source.pdf
  intermediate.json
  translated.docx
  report.json
  status.json
  images/
```

Fichiers attendus :

- Source : `storage/tmp/{document_id}/source.pdf`.
- Intermediaire : `storage/tmp/{document_id}/intermediate.json`.
- Resultat DOCX : `storage/tmp/{document_id}/translated.docx`.
- Rapport : `storage/tmp/{document_id}/report.json`.
- Statut : `storage/tmp/{document_id}/status.json`.
- Images extraites : `storage/tmp/{document_id}/images/`.

## Strategie de purge MVP

- Les fichiers temporaires sont supprimes apres 24 heures.
- La purge peut etre lancee au demarrage du backend.
- Une purge opportuniste peut etre lancee avant chaque upload.
- Une version future pourra utiliser un scheduler dedie.

## Criteres d'acceptation

- Les routes principales fonctionnent.
- Les services sont separes.
- Le pipeline peut etre teste avec un `TranslationService` mock.
- Les erreurs sont converties en reponses API propres.
- Les fichiers temporaires sont ranges par document.

## Tests a prevoir

- Tests unitaires services.
- Tests API routes.
- Test pipeline avec PDF fixture.
- Test erreur extraction.
- Test erreur traduction.
- Test generation DOCX.
