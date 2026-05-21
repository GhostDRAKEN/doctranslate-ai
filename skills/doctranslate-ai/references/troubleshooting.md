# Troubleshooting DocTranslate AI

## Groq 429

Symptomes :

- job en `failed` ;
- erreur `LLM_RATE_LIMIT_EXCEEDED` ;
- message : `La limite Groq a ete atteinte. Reessayez plus tard.`

Diagnostic :

- verifier `backend/storage/tmp/{document_id}/status.json` ;
- verifier que `LLM_FALLBACK_TO_MOCK=false` si aucun fallback n'est voulu ;
- ne jamais relancer en boucle automatiquement.

Action :

- attendre la reinitialisation du quota ;
- utiliser temporairement `MOCK_TRANSLATION_ENABLED=true` pour tester le pipeline sans LLM reel.

## Backend indisponible

Symptomes :

- frontend affiche backend indisponible ;
- `GET /api/health` echoue.

Diagnostic :

```powershell
cd backend
uvicorn app.main:app --reload
```

Verifier :

- port `8000` disponible ;
- `.env` present si necessaire ;
- CORS autorise le port frontend local.

## RESULT_NOT_READY

Symptomes :

- generation PDF ou DOCX refusee ;
- `intermediate.json` absent.

Diagnostic :

- verifier que `POST /process` a ete lance ;
- verifier `GET /status` ;
- verifier que le job est `completed`.

Action :

- relancer le traitement si le job n'a jamais ete lance ;
- inspecter `status.json` si le job est `failed`.

## PDF sans changement

Causes probables :

- `translated_text` vide ;
- blocs non traduits ;
- blocs marques `needs_review` ;
- overlay refuse mais erreur non affichee cote client ;
- bboxes incorrectes ou texte hors zone.

Diagnostic :

```powershell
python skills/doctranslate-ai/scripts/inspect_intermediate.py <document_id>
```

Verifier :

- nombre de blocs traduits ;
- nombre de `translated_text` vides ;
- warnings `suspicious_translation` ou `overflow_risk`.

## Images masquees

Causes probables :

- bbox texte trop large ;
- rectangle blanc d'overlay chevauche une image ;
- extraction layout approximative.

Action :

- inspecter les bboxes dans `intermediate.json` ;
- reduire la zone de masque ;
- ignorer certains blocs decoratifs ;
- ameliorer la segmentation avant overlay.

## Traduction incomplete

Symptomes :

- `TRANSLATION_INCOMPLETE` ;
- PDF non genere ;
- plusieurs blocs textuels ont `translated_text` vide.

Diagnostic :

- inspecter `intermediate.json` ;
- verifier les blocs `pending`, `failed`, `needs_review` ;
- verifier les logs LLM.

Action :

- corriger segmentation ;
- relancer avec mock pour isoler le pipeline ;
- relancer plus tard si erreur fournisseur LLM.
