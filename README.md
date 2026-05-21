# DocTranslate AI

DocTranslate AI est un MVP web de traduction documentaire haute fidelite pour PDF numeriques propres en anglais vers francais.

Le projet vise a extraire le contenu structure d'un PDF, traduire les blocs avec un pipeline controlable, reconstruire un document DOCX exploitable et produire un rapport de validation.

## Structure du projet

```text
backend/
  app/        Code applicatif Python/FastAPI
  storage/    Fichiers temporaires generes pendant les traitements
  tests/      Tests backend
frontend/
  src/        Code applicatif frontend Next.js/React
fixtures/
  pdf/        PDF de test et de demonstration
docs/         Specifications fonctionnelles et techniques
```

## Contraintes MVP

- PDF numeriques uniquement.
- Texte selectionnable obligatoire.
- Maximum 10 Mo.
- Maximum 10 pages.
- DOCX prioritaire.
- Export PDF optionnel.
- LLM reel optionnel apres validation du pipeline mocke.
- Reconstruction DOCX approximative : le rendu conserve les titres, paragraphes,
  styles simples, sauts de page et certaines images natives, mais ne vise pas
  une fidelite pixel-perfect.
- Le PDF final reste une evolution future et ne bloque pas le MVP.

## Etat actuel

Le backend couvre l'upload PDF, la validation MVP, l'extraction PyMuPDF, la
traduction mockee et la generation DOCX simple. Le frontend propose un parcours
minimal upload -> traitement -> generation DOCX -> telechargement.

## Lancer le backend

Depuis le dossier `backend/` :

```bash
python -m venv .venv
pip install -r requirements.txt
uvicorn app.main:app --reload
pytest
```

Endpoint disponible :

```text
GET /api/health
POST /api/documents/upload
POST /api/documents/{document_id}/process
GET /api/documents/{document_id}/status
GET /api/documents/{document_id}/intermediate
POST /api/documents/{document_id}/generate-docx
GET /api/documents/{document_id}/download/docx
```
