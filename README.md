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

## Etat actuel

Etape 1 terminee : initialisation de l'arborescence du projet.
Etape 2 en cours : backend FastAPI minimal.

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
```

La prochaine etape consiste a creer le frontend minimal.
