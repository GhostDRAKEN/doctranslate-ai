# Regles de codage

## Objectif

Ce document definit les regles de developpement de DocTranslate AI afin de garder un code lisible, maintenable, testable et securise.

## Regles generales

- Privilegier la simplicite et l'explicite.
- Separer clairement frontend, backend, services metier et stockage.
- Eviter les fonctions longues et les modules fourre-tout.
- Ecrire du code typable, testable et facile a remplacer.
- Ne jamais coder en dur les secrets, cles API ou chemins absolus.
- Documenter les decisions techniques importantes.

## Conventions de nommage

- Python : `snake_case` pour fonctions, variables et fichiers.
- Python : `PascalCase` pour classes et schemas Pydantic.
- TypeScript : `camelCase` pour variables et fonctions.
- React : `PascalCase` pour composants.
- Endpoints API : chemins REST lisibles, au pluriel quand pertinent.
- Identifiants metier : prefixes explicites, par exemple `doc_`, `job_`, `block_`.

## Architecture frontend

- Utiliser React ou Next.js avec TypeScript.
- Organiser le code par domaines fonctionnels : upload, progression, resultats, rapport.
- Isoler les appels API dans un client dedie.
- Garder les composants UI purs quand possible.
- Ne pas exposer de cle API IA cote frontend.
- Gerer explicitement les etats : idle, uploading, processing, completed, failed.

## Architecture backend

- Utiliser FastAPI pour l'API.
- Organiser les routes dans `app/api`.
- Organiser les schemas Pydantic dans `app/schemas`.
- Placer la logique metier dans `app/services`.
- Garder `main.py` minimal.
- Ne pas mettre la logique de traitement PDF dans les routes.

## Regles de securite

- Verifier le type MIME et l'extension du fichier.
- Limiter la taille maximale des uploads.
- Generer des noms de fichiers temporaires non predictibles.
- Stocker les secrets dans `.env`.
- Ne jamais logger le contenu complet de documents sensibles.
- Supprimer les fichiers temporaires apres expiration ou fin de traitement.
- Retourner des erreurs controlees sans stack trace publique.

## Gestion des erreurs

- Utiliser des exceptions metier claires cote backend.
- Transformer les erreurs internes en reponses API standardisees.
- Prevoir des codes d'erreur lisibles : `INVALID_FILE_TYPE`, `PDF_EXTRACTION_FAILED`, `TRANSLATION_FAILED`.
- Afficher cote frontend un message comprehensible et une action possible.
- Ne pas masquer silencieusement les blocs echoues : les marquer dans le rapport.

## Logs

- Logger les evenements techniques : upload recu, extraction terminee, traduction terminee.
- Logger les identifiants de document/job, pas les textes complets.
- Distinguer `info`, `warning`, `error`.
- Ajouter une correlation par `document_id` ou `job_id`.
- Prevoir une retention courte pour le MVP local.

## Commentaires

- Commenter les choix non evidents.
- Eviter les commentaires qui repetent le code.
- Ajouter des docstrings aux services importants.
- Documenter les limites connues des heuristiques de layout.

## Regles Git

- Commits courts et descriptifs.
- Une feature ou correction par commit.
- Ne pas commiter `.env`, documents uploades, fichiers temporaires ou resultats generes.
- Ajouter `.gitignore` pour `storage/tmp`, `storage/results`, `node_modules`, `.venv`.
- Relire les changements avant commit.

## Eviter le code spaghetti

- Une route API orchestre, un service execute.
- Un service ne doit pas connaitre les details UI.
- Les fonctions doivent avoir une responsabilite claire.
- Les transformations de donnees doivent etre explicites.
- La representation intermediaire doit servir de contrat entre extraction, traduction et reconstruction.

## Services IA

- Definir une interface `TranslationService`.
- Ne pas lier le code a un fournisseur unique.
- Centraliser les prompts.
- Versionner les prompts importants.
- Valider le format de reponse IA.
- Prevoir retries, timeouts et limites de cout.
- Garder les textes envoyes a l'IA minimises au besoin utile.

## Fichiers temporaires

- Stocker dans un repertoire local dedie, par exemple `backend/storage/tmp`.
- Associer chaque fichier a un `document_id`.
- Nettoyer les fichiers en cas d'erreur.
- Prevoir une tache de purge des fichiers expires.
- Ne pas conserver les documents sensibles sans raison.

