# Plan de developpement MVP

## 1. Objectif

Ce document decrit l'ordre exact de developpement du MVP DocTranslate AI.

Le but est de construire progressivement un prototype stable :

1. structure projet ;
2. backend minimal ;
3. frontend minimal ;
4. upload PDF ;
5. extraction PDF ;
6. traduction mockee ;
7. generation DOCX ;
8. rapport de validation ;
9. parcours complet.

Regle principale : ne pas integrer un vrai LLM avant que le pipeline complet fonctionne avec `MockTranslationProvider`.

## 2. Principes de developpement

- Commencer simple.
- Valider chaque etape avant de passer a la suivante.
- Garder le MVP limite aux PDF numeriques avec texte selectionnable.
- Appliquer les limites : 10 Mo, 10 pages.
- Utiliser `FastAPI BackgroundTasks` ou un traitement simplifie equivalent.
- Stocker les fichiers dans `backend/storage/tmp/{document_id}/`.
- Supprimer les fichiers apres 24 heures ou via purge manuelle.
- Generer le DOCX en priorite.
- Garder l'export PDF optionnel.
- Ne pas utiliser Celery, Redis ou RabbitMQ dans le MVP.

## 3. Etape 1 - Initialiser la structure du projet

### Objectif

Creer une arborescence claire pour separer backend, frontend, documentation, stockage temporaire et fixtures de test.

### Fichiers et dossiers a creer

```text
backend/
  app/
    main.py
    api/
      __init__.py
      documents.py
    core/
      __init__.py
      config.py
      errors.py
      logging.py
    schemas/
      __init__.py
      document.py
      glossary.py
      job.py
      report.py
    services/
      __init__.py
      storage_service.py
    utils/
      __init__.py
      ids.py
  storage/
    tmp/
  tests/
frontend/
  src/
docs/
fixtures/
  pdf/
.gitignore
README.md
```

Fichiers utilitaires explicitement attendus des l'etape 1 :

- `backend/app/utils/__init__.py`
- `backend/app/utils/ids.py`

### Commandes a executer

```bash
mkdir backend frontend fixtures
mkdir backend/app backend/app/api backend/app/core backend/app/schemas backend/app/services backend/app/utils backend/storage backend/storage/tmp backend/tests
mkdir fixtures/pdf
```

`backend/app/` contient uniquement le code applicatif. `backend/storage/` contient les fichiers generes temporairement pendant le traitement et ne doit pas etre confondu avec un module Python.

### Dependances a installer

Aucune dependance applicative obligatoire a cette etape.

### Tests a faire

- Verifier que l'arborescence existe.
- Verifier que `docs/` contient les specifications.
- Verifier que `backend/storage/tmp/` n'est pas destine a etre versionne.

### Critere de fin

L'arborescence projet est prete et separe clairement backend, frontend, docs et fixtures.

## 4. Etape 2 - Backend FastAPI minimal

### Objectif

Mettre en place une API FastAPI minimale avec configuration, healthcheck et format d'erreur standard.

### Fichiers a creer

```text
backend/requirements.txt
backend/.env.example
backend/app/main.py
backend/app/api/documents.py
backend/app/core/config.py
backend/app/core/errors.py
backend/app/core/logging.py
backend/tests/test_health.py
```

### Dependances a installer

```text
fastapi
uvicorn[standard]
pydantic
pydantic-settings
python-dotenv
pytest
httpx
```

### Commandes a executer

```bash
cd backend
python -m venv .venv
pip install -r requirements.txt
uvicorn app.main:app --reload
pytest
```

### Tests a faire

- `GET /api/health` retourne `200`.
- La reponse contient `status: "ok"`.
- Une erreur inconnue ne retourne pas de stack trace publique.

### Critere de fin

Le backend demarre localement et expose un healthcheck fonctionnel.

## 5. Etape 3 - Frontend minimal

### Objectif

Creer une application Next.js minimale avec Tailwind CSS, layout de base et pages principales vides.

### Fichiers a creer

```text
frontend/package.json
frontend/next.config.js
frontend/tsconfig.json
frontend/tailwind.config.ts
frontend/src/app/page.tsx
frontend/src/app/upload/page.tsx
frontend/src/app/documents/[documentId]/progress/page.tsx
frontend/src/app/documents/[documentId]/result/page.tsx
frontend/src/app/documents/[documentId]/report/page.tsx
frontend/src/components/AppLayout.tsx
frontend/src/services/apiClient.ts
frontend/src/types/api.ts
```

### Dependances a installer

```text
next
react
react-dom
typescript
tailwindcss
postcss
autoprefixer
```

### Commandes a executer

```bash
cd frontend
npm install
npm run dev
```

### Tests a faire

- La page d'accueil s'affiche.
- La page upload s'affiche.
- Les routes `progress`, `result` et `report` existent.
- Aucun appel API reel n'est encore requis.

### Critere de fin

Le frontend demarre localement et les pages principales sont accessibles.

## 6. Etape 4 - Schemas backend et contrats de base

### Objectif

Creer les schemas Pydantic correspondant aux specs de donnees et d'API.

### Fichiers a creer ou completer

```text
backend/app/schemas/document.py
backend/app/schemas/glossary.py
backend/app/schemas/job.py
backend/app/schemas/report.py
backend/app/core/errors.py
backend/tests/test_schemas.py
```

### Dependances a installer

Dependances deja installees :

```text
pydantic
pytest
```

### Commandes a executer

```bash
cd backend
pytest
```

### Tests a faire

- Valider un `DocumentIntermediate` minimal.
- Valider une `Page` contenant des `Block`.
- Valider un `TableBlock`.
- Valider un `ImageBlock`.
- Valider un `ValidationReport`.
- Verifier que les enums acceptent `domain_detection`.

### Critere de fin

Les schemas representent correctement le modele MVP et tous les tests de validation passent.

## 7. Etape 5 - Upload PDF backend

### Objectif

Permettre l'upload d'un PDF numerique propre et appliquer les validations MVP.

### Fichiers a creer ou completer

```text
backend/app/api/documents.py
backend/app/services/storage_service.py
backend/app/services/pdf_service.py
backend/app/utils/ids.py
backend/tests/test_upload.py
```

### Dependances a installer

```text
python-multipart
pymupdf
```

### Commandes a executer

```bash
cd backend
pip install python-multipart pymupdf
pytest
uvicorn app.main:app --reload
```

### Tests a faire

- Upload PDF valide.
- Refus fichier non PDF avec `INVALID_FILE_TYPE`.
- Refus fichier de plus de 10 Mo avec `FILE_TOO_LARGE`.
- Refus PDF de plus de 10 pages avec `PDF_TOO_MANY_PAGES`.
- Refus PDF sans texte selectionnable avec `PDF_NO_SELECTABLE_TEXT`.
- Creation de `backend/storage/tmp/{document_id}/source.pdf`.
- Creation ou initialisation de `status.json`.

### Critere de fin

`POST /api/documents/upload` retourne un `document_id` pour un PDF valide et refuse les cas hors MVP.

## 8. Etape 6 - Upload PDF frontend

### Objectif

Connecter l'interface upload au backend.

### Fichiers a creer ou completer

```text
frontend/src/app/upload/page.tsx
frontend/src/components/UploadDropzone.tsx
frontend/src/components/FileSummary.tsx
frontend/src/components/ErrorState.tsx
frontend/src/services/apiClient.ts
frontend/src/types/api.ts
```

### Dependances a installer

Aucune dependance obligatoire supplementaire. Une librairie de drag and drop peut etre ajoutee plus tard si necessaire.

### Commandes a executer

```bash
cd frontend
npm run dev
```

### Tests a faire

- Selection d'un fichier PDF.
- Affichage nom et taille.
- Validation frontend simple de l'extension et de la taille.
- Envoi vers `POST /api/documents/upload`.
- Affichage des erreurs backend.
- Conservation du `document_id`.

### Critere de fin

Un utilisateur peut uploader un PDF depuis l'interface et obtenir un `document_id`.

## 9. Etape 7 - Traitement asynchrone simplifie

### Objectif

Lancer un job de traitement en arriere-plan et exposer son statut.

### Fichiers a creer ou completer

```text
backend/app/api/documents.py
backend/app/services/storage_service.py
backend/app/services/job_service.py
backend/tests/test_process_status.py
```

### Dependances a installer

Aucune dependance supplementaire obligatoire.

### Commandes a executer

```bash
cd backend
pytest
uvicorn app.main:app --reload
```

### Tests a faire

- `POST /api/documents/{document_id}/process` retourne `202`.
- Le job passe en `queued`, puis `processing`.
- `GET /api/documents/{document_id}/status` retourne l'etape courante.
- Un second `POST /process` pendant un traitement retourne `409 PROCESS_ALREADY_RUNNING`.
- Un document inexistant retourne `404 DOCUMENT_NOT_FOUND`.

### Critere de fin

Le frontend peut suivre l'etat d'un traitement via polling, meme si le pipeline ne fait encore qu'une tache minimale.

## 10. Etape 8 - Extraction PDF avec PyMuPDF

### Objectif

Extraire les pages, blocs texte, images et tableaux simples si possible, puis produire `intermediate.json`.

### Fichiers a creer ou completer

```text
backend/app/services/extraction_service.py
backend/app/services/pdf_service.py
backend/app/schemas/document.py
backend/tests/test_extraction.py
fixtures/pdf/titles_paragraphs.pdf
fixtures/pdf/simple_table.pdf
fixtures/pdf/image.pdf
```

### Dependances a installer

Deja installee :

```text
pymupdf
```

Optionnel si necessaire pour tableaux :

```text
pdfplumber
```

### Commandes a executer

```bash
cd backend
pip install pdfplumber
pytest
```

### Tests a faire

- Extraire un PDF avec titres et paragraphes.
- Extraire un PDF avec image.
- Extraire ou signaler un tableau simple.
- Produire un `DocumentIntermediate` valide.
- Sauvegarder `backend/storage/tmp/{document_id}/intermediate.json`.
- Verifier que les blocs contiennent `id`, `page_number`, `type`, `bbox`, `reading_order`, `status`.

### Critere de fin

Le backend produit une representation intermediaire JSON conforme au modele MVP.

## 11. Etape 9 - Endpoint debug intermediate

### Objectif

Permettre la consultation technique de la representation intermediaire pendant le developpement.

### Fichiers a creer ou completer

```text
backend/app/api/documents.py
backend/app/services/storage_service.py
backend/tests/test_intermediate.py
```

### Dependances a installer

Aucune dependance supplementaire.

### Commandes a executer

```bash
cd backend
pytest
```

### Tests a faire

- `GET /api/documents/{document_id}/intermediate` retourne le JSON si disponible.
- Document inexistant retourne `404 DOCUMENT_NOT_FOUND`.
- Representation absente retourne une erreur controlee.

### Critere de fin

L'equipe peut inspecter le JSON intermediaire sans acceder directement au systeme de fichiers.

## 12. Etape 10 - Traduction mockee

### Objectif

Traduire les blocs de maniere deterministe sans utiliser de LLM reel.

### Fichiers a creer ou completer

```text
backend/app/services/translation_service.py
backend/app/services/glossary_service.py
backend/app/core/config.py
backend/tests/test_translation_mock.py
```

### Dependances a installer

Aucune dependance supplementaire pour le mock.

### Commandes a executer

```bash
cd backend
pytest
```

### Tests a faire

- `MOCK_TRANSLATION_ENABLED=true` active le mock.
- Traduction mockee d'un paragraphe.
- Traduction mockee des cellules d'un tableau.
- Images ignorees ou marquees `needs_review`.
- Les `block_id` et `reading_order` sont conserves.
- Le glossaire simple peut etre applique ou controle.

### Critere de fin

Le pipeline peut remplir `translated_text` sans dependance LLM.

## 13. Etape 11 - Detection de domaine simple

### Objectif

Ajouter une detection de domaine legere pour enrichir le contexte de traduction.

### Fichiers a creer ou completer

```text
backend/app/services/domain_service.py
backend/app/services/translation_service.py
backend/tests/test_domain_detection.py
```

### Dependances a installer

Aucune dependance supplementaire.

### Commandes a executer

```bash
cd backend
pytest
```

### Tests a faire

- Fallback `general`.
- Detection `legal` par mots-cles.
- Detection `technical` par mots-cles.
- Detection `academic` par mots-cles.
- Detection `business` par mots-cles.
- Le champ `domain` est ecrit dans `DocumentIntermediate`.

### Critere de fin

Chaque document traite a un domaine parmi `general`, `legal`, `technical`, `academic`, `business`.

## 14. Etape 12 - Reconstruction DOCX

### Objectif

Generer un document DOCX editable a partir de la representation intermediaire traduite.

### Fichiers a creer ou completer

```text
backend/app/services/reconstruction_service.py
backend/app/api/documents.py
backend/tests/test_reconstruction_docx.py
```

### Dependances a installer

```text
python-docx
```

### Commandes a executer

```bash
cd backend
pip install python-docx
pytest
```

### Tests a faire

- Generer `backend/storage/tmp/{document_id}/translated.docx`.
- Le DOCX est ouvrable.
- Les titres sont conserves approximativement.
- Les paragraphes sont lisibles.
- Les tableaux simples sont reconstruits.
- Les images sont inserees si disponibles.
- `GET /api/documents/{document_id}/download/docx` retourne le fichier.
- Appel avant fin de traitement retourne `409 RESULT_NOT_READY`.

### Critere de fin

Un DOCX traduit est telechargeable pour un document simple.

## 15. Etape 13 - Rapport de validation

### Objectif

Generer un rapport indiquant les zones a verifier.

### Fichiers a creer ou completer

```text
backend/app/services/validation_service.py
backend/app/schemas/report.py
backend/app/api/documents.py
backend/tests/test_validation_report.py
```

### Dependances a installer

Aucune dependance supplementaire.

### Commandes a executer

```bash
cd backend
pytest
```

### Tests a faire

- Generer `backend/storage/tmp/{document_id}/report.json`.
- Signaler bloc non traduit.
- Signaler image avec texte possible.
- Signaler tableau suspect.
- Signaler risque de debordement avec `overflow_risk`.
- Signaler terme de glossaire absent.
- Calculer un `confidence_score` entre 0 et 1.
- `GET /api/documents/{document_id}/report` retourne le rapport.

### Critere de fin

Chaque traitement produit un rapport de validation consultable par API.

## 16. Etape 14 - Page de progression frontend

### Objectif

Afficher le traitement en cours avec polling backend.

### Fichiers a creer ou completer

```text
frontend/src/app/documents/[documentId]/progress/page.tsx
frontend/src/components/ProgressSteps.tsx
frontend/src/components/StatusBadge.tsx
frontend/src/services/apiClient.ts
```

### Dependances a installer

Aucune dependance supplementaire.

### Commandes a executer

```bash
cd frontend
npm run dev
```

### Tests a faire

- Lancer `POST /process` apres upload.
- Polling `GET /status` toutes les 2 a 3 secondes.
- Arret du polling sur `completed`, `failed` ou `expired`.
- Affichage de `current_step`.
- Redirection ou lien vers la page resultat quand termine.

### Critere de fin

L'utilisateur voit clairement l'avancement du traitement.

## 17. Etape 15 - Page resultat frontend

### Objectif

Afficher les fichiers disponibles et permettre le telechargement DOCX.

### Fichiers a creer ou completer

```text
frontend/src/app/documents/[documentId]/result/page.tsx
frontend/src/components/ResultActions.tsx
frontend/src/services/apiClient.ts
```

### Dependances a installer

Aucune dependance supplementaire.

### Commandes a executer

```bash
cd frontend
npm run dev
```

### Tests a faire

- Appel `GET /result`.
- Affichage du score de confiance.
- Bouton telechargement DOCX.
- PDF affiche seulement si disponible.
- PDF optionnel clairement indique.

### Critere de fin

L'utilisateur peut telecharger le DOCX depuis la page resultat.

## 18. Etape 16 - Page rapport frontend

### Objectif

Afficher les alertes de validation.

### Fichiers a creer ou completer

```text
frontend/src/app/documents/[documentId]/report/page.tsx
frontend/src/components/ValidationReportTable.tsx
frontend/src/components/IssueSeverityBadge.tsx
frontend/src/services/apiClient.ts
```

### Dependances a installer

Aucune dependance supplementaire.

### Commandes a executer

```bash
cd frontend
npm run dev
```

### Tests a faire

- Appel `GET /report`.
- Affichage du score.
- Affichage des alertes par severite.
- Affichage `page_number` et `block_id`.
- Message clair si aucune alerte.

### Critere de fin

L'utilisateur peut consulter les zones a verifier apres traitement.

## 19. Etape 17 - Nettoyage temporaire

### Objectif

Eviter de conserver inutilement les documents sensibles.

### Fichiers a creer ou completer

```text
backend/app/services/storage_service.py
backend/tests/test_storage_cleanup.py
```

### Dependances a installer

Aucune dependance supplementaire.

### Commandes a executer

```bash
cd backend
pytest
```

### Tests a faire

- Identifier les dossiers de plus de 24 heures.
- Supprimer un dossier expire.
- Ne pas supprimer un traitement recent.
- Ne pas echouer si un fichier manque deja.

### Critere de fin

Les fichiers temporaires peuvent etre purges apres 24 heures.

## 20. Etape 18 - Integration LLM reelle optionnelle

### Objectif

Brancher un fournisseur LLM sans casser le pipeline mocke.

Cette etape est optionnelle pour le MVP demonstrable.

### Fichiers a creer ou completer

```text
backend/app/services/translation_service.py
backend/app/core/config.py
backend/tests/test_translation_provider_selection.py
```

### Dependances a installer

Selon le fournisseur choisi. Exemple generique :

```text
httpx
```

### Commandes a executer

```bash
cd backend
pytest
```

### Tests a faire

- `MOCK_TRANSLATION_ENABLED=true` utilise le mock.
- `MOCK_TRANSLATION_ENABLED=false` selectionne le provider LLM.
- Timeout gere proprement.
- Reponse non JSON geree proprement.
- Erreur fournisseur convertie en `TRANSLATION_FAILED`.

### Critere de fin

Le LLM peut etre active par configuration, mais le mock reste utilisable pour tests et demonstration.

## 21. Etape 19 - Test complet de demonstration

### Objectif

Verifier le parcours complet avant presentation.

### Fichiers a utiliser

```text
fixtures/pdf/titles_paragraphs.pdf
fixtures/pdf/simple_table.pdf
fixtures/pdf/image.pdf
```

### Commandes a executer

Backend :

```bash
cd backend
uvicorn app.main:app --reload
```

Frontend :

```bash
cd frontend
npm run dev
```

Tests :

```bash
cd backend
pytest
```

### Tests a faire

- Upload PDF titres + paragraphes.
- Upload PDF tableau simple.
- Upload PDF avec image.
- Refus fichier invalide.
- Refus PDF trop grand.
- Refus PDF de plus de 10 pages.
- Suivi de progression.
- Generation DOCX.
- Consultation rapport.
- Telechargement DOCX.
- Verification que PDF optionnel ne bloque pas.
- Verification que les logs ne contiennent pas le texte complet du document.

### Critere de fin

Le parcours upload -> traitement -> DOCX -> rapport fonctionne avec les fixtures et traduction mockee.

## 22. Definition finale du MVP termine

Le MVP est termine lorsque :

- le backend FastAPI demarre ;
- le frontend Next.js demarre ;
- `GET /api/health` fonctionne ;
- un PDF numerique de moins de 10 Mo et 10 pages est accepte ;
- un PDF hors limites est refuse proprement ;
- `source.pdf`, `intermediate.json`, `translated.docx`, `report.json` et `status.json` sont geres dans `backend/storage/tmp/{document_id}/` ;
- le pipeline fonctionne avec `MockTranslationProvider` ;
- la detection de domaine simple fonctionne ;
- le DOCX est telechargeable ;
- le rapport est consultable ;
- le frontend couvre upload, progression, resultat et rapport ;
- les fichiers temporaires peuvent etre supprimes apres 24 heures ;
- aucun vrai LLM n'est requis pour la demonstration de base ;
- l'export PDF est clairement optionnel.
