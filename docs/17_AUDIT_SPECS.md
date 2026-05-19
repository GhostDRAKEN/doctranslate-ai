# Audit global des specifications

## 1. Objectif de l'audit

Ce rapport verifie la coherence globale des fichiers de specification du projet DocTranslate AI.

Perimetre audite :

- contexte projet ;
- regles de codage ;
- architecture technique ;
- UI/UX ;
- modele de donnees ;
- features MVP ;
- API backend ;
- frontend ;
- backend ;
- roadmap ;
- limites et risques ;
- plan d'implementation.

L'objectif est d'identifier les contradictions, les zones trop vagues et les ameliorations a apporter avant de commencer le code applicatif.

## 2. Synthese executive

Les specifications forment une base serieuse et globalement coherente pour un MVP de traduction documentaire haute fidelite limite aux PDF numeriques propres.

Les points les plus solides sont :

- separation claire frontend/backend ;
- choix coherent FastAPI + Next.js + TypeScript ;
- priorite donnee au DOCX ;
- export PDF correctement marque comme optionnel ;
- traitement asynchrone MVP simplifie via `FastAPI BackgroundTasks` ;
- modele de donnees recentre autour de `DocumentIntermediate`, `Page` et `Block` ;
- priorite au `MockTranslationProvider` avant integration LLM reelle ;
- limites MVP explicites dans les documents les plus recents.

Les principales corrections restantes concernent :

- anciennes limites encore presentes dans certaines specs feature ;
- quelques divergences de chemins de stockage ;
- spec traduction encore trop orientee LLM pour le MVP ;
- frontend qui utilise encore `documents/[id]` au lieu d'un nom coherant avec `document_id` ;
- rapport de validation qui emploie parfois `page` au lieu de `page_number` ;
- backend spec encore partiellement alignee sur une structure plus ancienne.

Conclusion : le MVP est realiste, mais plusieurs specs doivent etre harmonisees avant implementation pour eviter des decisions contradictoires cote developpement.

## 3. Contradictions detectees

### 3.1 Limite de taille PDF

Contradiction :

- `02_ARCHITECTURE_TECHNIQUE.md`, `04_MODELE_DONNEES.md`, `11_SPEC_API_BACKEND.md` et `16_PLAN_IMPLEMENTATION.md` fixent la limite a 10 Mo.
- `05_SPEC_FEATURE_UPLOAD_PDF.md` indique encore "Taille maximale recommandee MVP : 20 Mo".

Impact :

- risque d'implementation incoherente entre frontend, API et tests ;
- risque de messages UI contradictoires.

Recommandation :

- remplacer 20 Mo par 10 Mo dans `05_SPEC_FEATURE_UPLOAD_PDF.md`.

### 3.2 Limite de nombre de pages

Contradiction :

- l'architecture, l'API, le modele de donnees et le plan fixent une limite stricte de 10 pages.
- `06_SPEC_FEATURE_ANALYSE_EXTRACTION.md` parle d'un "traitement raisonnable pour un PDF de 20 pages".

Impact :

- le service d'extraction pourrait etre teste ou optimise pour un perimetre qui n'est plus le MVP.

Recommandation :

- aligner `06_SPEC_FEATURE_ANALYSE_EXTRACTION.md` sur 10 pages maximum.

### 3.3 Chemins de stockage des resultats

Contradiction :

- `02_ARCHITECTURE_TECHNIQUE.md`, `04_MODELE_DONNEES.md`, `11_SPEC_API_BACKEND.md` et `16_PLAN_IMPLEMENTATION.md` convergent vers `storage/tmp/{document_id}/` avec `translated.docx` et `report.json`.
- `09_SPEC_FEATURE_RECONSTRUCTION_DOCX.md` sauvegarde le DOCX dans `storage/results/{document_id}/translated.docx`.
- `13_SPEC_BACKEND.md` place aussi le DOCX et le rapport dans `storage/results/{document_id}/`.

Impact :

- confusion sur la responsabilite de `storage/tmp` vs `storage/results` ;
- risque de liens de telechargement ou purge mal implementes.

Recommandation :

- pour le MVP, utiliser un seul dossier : `storage/tmp/{document_id}/`.
- reserver `storage/results` a une evolution future si une retention plus longue est ajoutee.

### 3.4 Traduction IA trop centrale dans certaines specs

Contradiction :

- `16_PLAN_IMPLEMENTATION.md` impose le pipeline complet avec traduction mockee avant integration LLM reelle.
- `07_SPEC_FEATURE_TRADUCTION_CONTEXTE.md` presente encore l'appel LLM, le resume documentaire et les retries IA comme coeur du MVP.
- `08_SPEC_FEATURE_GLOSSAIRE_TERMINOLOGIE.md` mentionne un glossaire genere automatiquement par LLM dans le MVP.

Impact :

- risque de commencer par le LLM au lieu de stabiliser extraction -> mock -> DOCX -> rapport ;
- complexite et cout plus eleves trop tot.

Recommandation :

- clarifier dans `07_SPEC_FEATURE_TRADUCTION_CONTEXTE.md` que le provider mock est prioritaire.
- deplacer le resume documentaire LLM et le glossaire genere automatiquement en "option MVP tardive" ou "version avancee".

### 3.5 Codes d'erreur non harmonises

Contradiction :

- `11_SPEC_API_BACKEND.md` liste les codes principaux actuels.
- `05_SPEC_FEATURE_UPLOAD_PDF.md` contient `EMPTY_FILE` et `UPLOAD_FAILED`, absents de l'API centrale.
- `07_SPEC_FEATURE_TRADUCTION_CONTEXTE.md` contient `AI_QUOTA_EXCEEDED`, absent de l'API centrale.

Impact :

- erreurs frontend difficiles a typer ;
- tests API incomplets ou divergents.

Recommandation :

- soit ajouter ces codes a `11_SPEC_API_BACKEND.md` avec mapping HTTP ;
- soit retirer les codes non MVP des specs feature et les noter comme evolution.

### 3.6 Nommage `page` vs `page_number`

Contradiction :

- `04_MODELE_DONNEES.md` utilise `page_number`.
- `11_SPEC_API_BACKEND.md` utilise `page_number` dans le rapport API.
- `10_SPEC_FEATURE_RAPPORT_VALIDATION.md` montre un exemple avec `page`.

Impact :

- confusion dans les schemas Pydantic et les composants frontend.

Recommandation :

- standardiser partout sur `page_number`.

### 3.7 Routes frontend avec `[id]`

Contradiction :

- `11_SPEC_API_BACKEND.md` impose `{document_id}`.
- `12_SPEC_FRONTEND.md` propose des pages `documents/[id]/progress`, `documents/[id]/result`, `documents/[id]/report`.

Impact :

- ce n'est pas bloquant techniquement, mais le nommage est moins clair.

Recommandation :

- renommer dans la spec frontend en `documents/[documentId]/...` ou documenter que `[id]` correspond au `document_id`.

## 4. Realisme du MVP

Le MVP est realiste si le perimetre le plus recent est respecte :

- PDF numerique uniquement ;
- texte selectionnable ;
- 10 pages maximum ;
- 10 Mo maximum ;
- documents a une colonne en priorite ;
- tableaux simples ;
- traduction mockee en premier ;
- LLM reel optionnel ;
- DOCX prioritaire ;
- PDF optionnel ;
- stockage local temporaire ;
- purge apres 24 heures.

Le risque principal est l'ambition de "traduction avec contexte" si elle est interpretee comme une vraie orchestration LLM complete des le debut. Pour un superviseur de stage, le prototype sera plus convaincant s'il montre un pipeline complet stable, meme avec traduction mockee, plutot qu'une integration IA fragile sans reconstruction fiable.

Recommandation de cadrage :

1. livrer d'abord un pipeline technique complet ;
2. brancher un LLM uniquement apres validation de l'extraction, du JSON intermediaire, du DOCX et du rapport ;
3. presenter clairement les limites du mock et le point d'extension vers le LLM.

## 5. Decoupage des features

Le decoupage est globalement bon :

- upload ;
- analyse/extraction ;
- traduction ;
- glossaire ;
- reconstruction ;
- rapport ;
- API ;
- frontend ;
- backend.

Points forts :

- chaque feature a un objectif clair ;
- les criteres d'acceptation sont presents ;
- les cas limites sont mentionnes ;
- les tests sont listes.

Points a ameliorer :

- `07_SPEC_FEATURE_TRADUCTION_CONTEXTE.md` melange MVP mock, LLM reel, resume documentaire et retry IA.
- `08_SPEC_FEATURE_GLOSSAIRE_TERMINOLOGIE.md` melange glossaire utilisateur simple et glossaire genere automatiquement.
- `06_SPEC_FEATURE_ANALYSE_EXTRACTION.md` devrait expliciter que les tableaux doivent sortir comme blocs `table` conformes au modele de donnees.

Recommandation :

- ajouter dans chaque spec feature une ligne "Source de verite associee" :
  - upload -> `11_SPEC_API_BACKEND.md` ;
  - extraction -> `04_MODELE_DONNEES.md` ;
  - reconstruction -> `04_MODELE_DONNEES.md` + `09_SPEC_FEATURE_RECONSTRUCTION_DOCX.md` ;
  - rapport -> `04_MODELE_DONNEES.md` + `10_SPEC_FEATURE_RAPPORT_VALIDATION.md`.

## 6. Coherence architecture frontend/backend

L'architecture est coherente :

- frontend Next.js/TypeScript/Tailwind ;
- backend FastAPI ;
- API REST ;
- polling de statut ;
- traitement asynchrone simplifie ;
- stockage local temporaire ;
- separation services/routes/schemas.

Points a corriger :

- `12_SPEC_FRONTEND.md` ne mentionne pas `GET /api/health`.
- `12_SPEC_FRONTEND.md` ne mentionne pas `getIntermediate(documentId)` pour debug, ce qui est acceptable mais devrait etre note comme outil developpeur optionnel.
- `12_SPEC_FRONTEND.md` n'indique pas explicitement la limite 10 Mo / 10 pages dans l'upload.
- `13_SPEC_BACKEND.md` mentionne encore une evolution Celery/RQ/Redis ; ce n'est pas grave en section evolution, mais il faut eviter que ce soit interprete comme MVP.

Recommandation :

- ajouter une section "Contrats API consommes par le frontend" dans `12_SPEC_FRONTEND.md`.
- aligner les noms de routes dynamiques frontend sur `documentId`.

## 7. Correspondance API avec les besoins frontend

Les endpoints couvrent bien le parcours frontend :

- `GET /api/health` pour verifier l'API ;
- `POST /api/documents/upload` pour l'import ;
- `POST /api/documents/{document_id}/process` pour lancer le traitement ;
- `GET /api/documents/{document_id}/status` pour le polling ;
- `GET /api/documents/{document_id}/result` pour la page resultat ;
- `GET /api/documents/{document_id}/report` pour la page rapport ;
- `GET /api/documents/{document_id}/download/docx` pour le livrable principal ;
- `GET /api/documents/{document_id}/download/pdf` pour l'export optionnel ;
- `GET /api/documents/{document_id}/intermediate` pour debug MVP.

Manques mineurs :

- pas d'endpoint de suppression manuelle d'un document temporaire ;
- pas d'endpoint historique, ce qui est acceptable car l'historique est optionnel ;
- pas de schema detaille pour `PROCESS_ALREADY_RUNNING` et `RESULT_NOT_READY` dans les exemples, meme si les codes sont bien definis.

Recommandation :

- ne pas ajouter d'endpoint historique dans le MVP ;
- envisager plus tard `DELETE /api/documents/{document_id}` pour suppression manuelle, mais le garder hors MVP si le temps est limite.

## 8. Suffisance des modeles de donnees

Le modele de donnees est suffisant pour le MVP.

Points solides :

- `DocumentIntermediate` est simple ;
- `Page` contient directement ses blocs ;
- `Block` couvre titres, paragraphes, tableaux, images ;
- `TableBlock` contient `rows/cells` ;
- `ImageBlock` signale le texte possible dans les images ;
- `TranslationJob` couvre le statut ;
- `ValidationReport` couvre les alertes ;
- les metriques optionnelles preparent une validation visuelle future.

Points a preciser :

- `metrics` est decrit mais absent des exemples de `Block`, ce qui est acceptable car optionnel ; un exemple integre pourrait aider.
- `style.font` et `style.color` valent `null` dans `ImageBlock`, alors que les autres exemples les montrent comme chaines ; le schema Pydantic devra accepter `null` pour les blocs image.
- `TranslationJob.current_step` devrait etre contraint par l'enum incluant `domain_detection`.
- le modele ne definit pas explicitement le format d'une cellule avec `bbox`; ce n'est pas indispensable pour MVP, mais utile pour reconstruction future.

Recommandation :

- garder le modele actuel ;
- ne pas ajouter de collection globale ;
- ajouter seulement des precisions de typage lors de la creation des schemas Pydantic.

## 9. Specs trop vagues

### 9.1 Detection de tableaux

Probleme :

- les tableaux sont mentionnes comme "simples", mais les criteres exacts restent vagues.

Amelioration concrete :

- definir MVP tableau simple comme : une seule page, lignes/colonnes detectables, pas de cellules fusionnees, pas de tableau imbrique.

### 9.2 Detection de domaine

Probleme :

- le plan mentionne une detection par mots-cles ou mock, mais les mots-cles ne sont pas proposes.

Amelioration concrete :

- definir une table minimale :
  - `legal` : agreement, liability, clause, party, jurisdiction ;
  - `technical` : system, API, configuration, server, protocol ;
  - `academic` : abstract, methodology, results, references ;
  - `business` : revenue, market, customer, strategy, invoice ;
  - fallback `general`.

### 9.3 MockTranslationProvider

Probleme :

- il est prioritaire, mais son comportement attendu n'est pas completement specifie.

Amelioration concrete :

- definir que le mock prefixe ou transforme de maniere deterministe :
  - paragraphes : `[FR MOCK] {source_text}` ;
  - cellules : meme logique cellule par cellule ;
  - images : non traduites, `needs_review` si `has_possible_text`.

### 9.4 Score de confiance

Probleme :

- le score est decrit comme `1.0 - penalites`, mais les penalites ne sont pas quantifiees.

Amelioration concrete :

- definir une formule MVP simple :
  - bloc non traduit : -0.05 ;
  - bloc `failed` : -0.10 ;
  - tableau suspect : -0.05 ;
  - image avec texte possible : -0.03 ;
  - terme obligatoire absent : -0.05 ;
  - borne finale entre 0 et 1.

### 9.5 Nettoyage 24 heures

Probleme :

- la purge apres 24 heures est mentionnee, mais le declenchement n'est pas precise.

Amelioration concrete :

- MVP : purge au demarrage du backend + purge opportuniste avant chaque upload.
- Version future : scheduler dedie.

## 10. Ameliorations concretes recommandees

Priorite haute :

1. Aligner `05_SPEC_FEATURE_UPLOAD_PDF.md` sur 10 Mo.
2. Aligner `06_SPEC_FEATURE_ANALYSE_EXTRACTION.md` sur 10 pages.
3. Aligner les chemins de stockage dans `09_SPEC_FEATURE_RECONSTRUCTION_DOCX.md` et `13_SPEC_BACKEND.md` vers `storage/tmp/{document_id}/`.
4. Clarifier dans `07_SPEC_FEATURE_TRADUCTION_CONTEXTE.md` que le mock est prioritaire et que le LLM reel est optionnel apres pipeline complet.
5. Standardiser `page_number` dans `10_SPEC_FEATURE_RAPPORT_VALIDATION.md`.

Priorite moyenne :

6. Harmoniser les codes d'erreur feature avec `11_SPEC_API_BACKEND.md`.
7. Renommer les routes frontend `documents/[id]` en `documents/[documentId]`.
8. Ajouter les limites 10 Mo / 10 pages dans `03_SPEC_UI_UX.md` et `12_SPEC_FRONTEND.md`.
9. Definir le comportement attendu du `MockTranslationProvider`.
10. Definir une formule MVP du score de confiance.

Priorite basse :

11. Ajouter une table de mots-cles pour la detection de domaine.
12. Preciser la strategie de purge 24 heures.
13. Ajouter un endpoint de suppression manuelle seulement si necessaire pour la demonstration.
14. Ajouter un exemple de bloc avec `metrics`.

## 11. Verdict final

Les specifications sont suffisamment solides pour servir de base a l'implementation, mais elles doivent etre harmonisees avant de coder.

Le MVP reste realiste si les regles suivantes sont conservees :

- pipeline mocke complet avant LLM ;
- PDF limite a 10 Mo et 10 pages ;
- extraction PyMuPDF simple ;
- tableaux simples uniquement ;
- DOCX prioritaire ;
- export PDF optionnel ;
- stockage local temporaire ;
- rapport de validation explicite ;
- pas de Celery, Redis ou RabbitMQ dans le MVP.

Le projet est bien positionne pour une presentation de stage : il montre une comprehension serieuse des problemes PDF, de la reconstruction documentaire, de la traduction assistee par IA et des contraintes produit. La prochaine etape logique est une passe d'harmonisation des specs existantes avant de demarrer le code.
