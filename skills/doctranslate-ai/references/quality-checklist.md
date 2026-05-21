# Checklist qualite DocTranslate AI

## Avant generation PDF

- [ ] Le document respecte les limites MVP : PDF numerique, 10 pages max, 10 Mo max.
- [ ] `intermediate.json` existe.
- [ ] Les pages sont presentes.
- [ ] Les blocs principaux sont logiques, pas seulement des lignes isolees.
- [ ] Les titres sont marques `title`.
- [ ] Les paragraphes sont marques `paragraph`.
- [ ] Les listes sont marquees `list_item` si possible.
- [ ] Les footers/headers repetitifs ne polluent pas le corps.
- [ ] Les fragments suspects sont marques `needs_review`.

## Traduction

- [ ] Les blocs principaux ont un `translated_text` non vide.
- [ ] Le texte francais est naturel et comprehensible.
- [ ] Il ne reste pas trop de mots anglais residuels.
- [ ] Les noms propres, URLs, nombres et acronymes sont preserves.
- [ ] Aucun bloc image n'est envoye au LLM.
- [ ] Aucun secret API n'apparait dans les logs.
- [ ] Pas de fallback mock involontaire si `LLM_FALLBACK_TO_MOCK=false`.

## PDF final

- [ ] `result.pdf` existe dans `backend/storage/tmp/{document_id}/`.
- [ ] Le PDF est telechargeable via `/download/pdf`.
- [ ] Les images originales sont conservees.
- [ ] Les fonds et elements graphiques restent visibles.
- [ ] Le texte anglais principal est masque.
- [ ] Le texte francais est visible.
- [ ] Les paragraphes sont coherents.
- [ ] Les footers/headers ne sont pas rendus comme contenu principal.
- [ ] Les warnings `overflow_risk` sont examines.

## Demonstration

- [ ] Upload reussi.
- [ ] Traitement termine avec statut `completed`.
- [ ] PDF genere avec succes.
- [ ] PDF telechargeable.
- [ ] DOCX reste disponible comme option secondaire.
- [ ] Les tests backend passent.
