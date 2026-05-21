---
name: doctranslate-ai
description: Guide d'utilisation, de diagnostic et d'amelioration du moteur DocTranslate AI pour traduire des PDF numeriques anglais vers francais avec reconstruction PDF par overlay.
---

# DocTranslate AI

## Objectif

Ce skill aide un assistant de developpement comme Codex ou Claude Code a comprendre, tester, diagnostiquer et ameliorer le MVP DocTranslate AI.

DocTranslate AI est une application web qui importe un PDF numerique propre, extrait une representation intermediaire structuree, traduit les blocs textuels en francais, puis genere un PDF traduit par overlay en conservant autant que possible les pages, images, fonds et elements graphiques du document source.

## Quand utiliser ce skill

Utiliser ce skill pour :

- diagnostiquer un probleme de traduction PDF ;
- verifier la qualite de `intermediate.json` avant generation PDF ;
- tester le pipeline backend ;
- analyser un job echoue ;
- comprendre pourquoi un PDF traduit ne change pas visuellement ;
- preparer une demonstration technique du MVP ;
- proposer une amelioration sans casser les contraintes MVP.

## Workflow principal

Le parcours produit attendu est :

```text
upload -> process -> inspect intermediate -> generate-pdf -> download
```

Endpoints associes :

```text
POST /api/documents/upload
POST /api/documents/{document_id}/process
GET  /api/documents/{document_id}/status
GET  /api/documents/{document_id}/intermediate
POST /api/documents/{document_id}/generate-pdf
GET  /api/documents/{document_id}/download/pdf
```

## Regles importantes

- Ne jamais exposer les cles API, notamment `LLM_API_KEY`.
- Ne jamais logger le contenu complet d'un document utilisateur.
- Toujours verifier `backend/storage/tmp/{document_id}/intermediate.json` avant de diagnostiquer le PDF final.
- Ne pas generer de PDF si la traduction est absente ou incomplete.
- En cas de rate limit Groq `429` ou `rate_limit_exceeded`, arreter le job et signaler `LLM_RATE_LIMIT_EXCEEDED`.
- Ne pas fallback vers le mock si `LLM_FALLBACK_TO_MOCK=false`.
- Preserver les images et elements graphiques du PDF source pendant l'overlay.
- Ne pas faire d'OCR dans le MVP.
- Ne pas traiter les PDF scannes complexes.
- Ne pas viser le pixel-perfect : le MVP vise une reconstruction exploitable et demonstrable.

## Commandes utiles

Depuis la racine du projet :

```powershell
cd backend
python -m pytest
uvicorn app.main:app --reload
```

Depuis la racine du frontend :

```powershell
cd frontend
npm run typecheck
npm run build
npm run dev
```

Inspection d'un document :

```powershell
python skills/doctranslate-ai/scripts/inspect_intermediate.py <document_id>
```

Tests backend via script :

```powershell
powershell -ExecutionPolicy Bypass -File skills/doctranslate-ai/scripts/run_backend_tests.ps1
```

## Criteres de reussite

- Le PDF source est accepte uniquement s'il respecte les limites MVP.
- `intermediate.json` contient des pages et des blocs logiques coherents.
- Les blocs textuels principaux ont un `translated_text` francais non vide.
- Les fragments suspects sont marques `needs_review`.
- Le PDF final est genere dans `backend/storage/tmp/{document_id}/result.pdf`.
- Le PDF telechargeable conserve les images et la structure visuelle generale.
- Les tests backend passent.

## Limites actuelles

- PDF numeriques propres uniquement.
- Maximum 10 pages et 10 Mo.
- Pas d'OCR.
- Pas de traduction du texte contenu dans les images.
- Overlay PDF approximatif, sans reflow avance.
- Analyse de layout encore heuristique.
- Tables complexes, colonnes multiples et documents tres graphiques restent hors MVP.

## References

- `references/pipeline.md` : pipeline technique complet.
- `references/troubleshooting.md` : erreurs frequentes et diagnostic.
- `references/quality-checklist.md` : checklist de validation qualite.
