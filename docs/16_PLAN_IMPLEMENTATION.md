# Plan d'implementation

## 1. Objectif

Ce document definit uniquement le plan d'implementation du MVP DocTranslate AI.

Le but est de construire un prototype web demonstrable, realiste et evolutif, sans generer de complexite prematuree.

## 2. Definition du prototype demontrable

Le prototype est considere demonstrable si :

- un utilisateur peut importer un PDF numerique propre ;
- le PDF respecte les limites MVP : 10 pages maximum et 10 Mo maximum ;
- le backend extrait le texte selectionnable avec PyMuPDF ;
- le backend produit une representation intermediaire JSON ;
- la traduction fonctionne d'abord avec un provider mock ;
- un DOCX traduit est genere ;
- un rapport de validation est genere ;
- le frontend permet le parcours complet upload -> progression -> resultat -> rapport.

Le DOCX est le livrable prioritaire. L'export PDF est optionnel et son absence ne bloque pas la validation du MVP.

## 3. Ordre global de developpement

Ordre recommande :

1. Initialisation projet.
2. Backend FastAPI minimal.
3. Frontend minimal.
4. Upload PDF.
5. Stockage temporaire.
6. Extraction PDF avec PyMuPDF.
7. Representation intermediaire JSON.
8. Traduction mockee.
9. Reconstruction DOCX.
10. Rapport de validation.
11. Parcours frontend complet.
12. Integration LLM reelle optionnelle.
13. Polish demo.

Regle importante : le pipeline complet avec traduction mockee doit etre prioritaire avant l'integration d'un vrai LLM.

## 4. Plan semaine par semaine

### Semaine 1 - Initialisation et socle technique

Backend :

- creer le projet FastAPI ;
- ajouter `GET /api/health` ;
- configurer `.env` ;
- ajouter `MOCK_TRANSLATION_ENABLED=true` par defaut ;
- definir les dossiers `storage/tmp` ;
- definir les erreurs API standardisees ;
- definir une regle de logs backend : journaliser les etapes du traitement sans logger le contenu complet des documents.

Frontend :

- creer le projet React ou Next.js en TypeScript ;
- configurer Tailwind CSS ;
- creer un layout minimal ;
- creer les pages vides principales.

Tests :

- tester le healthcheck ;
- tester la lecture de configuration ;
- verifier que le backend demarre ;
- preparer les fixtures PDF de base : PDF avec titres et paragraphes, PDF avec tableau simple, PDF avec image.

### Semaine 2 - Upload PDF et stockage temporaire

Backend :

- implementer `POST /api/documents/upload` ;
- valider extension, MIME et signature PDF ;
- limiter les fichiers a 10 Mo ;
- verifier le nombre de pages, maximum 10 ;
- verifier la presence de texte selectionnable ;
- stocker le fichier dans `storage/tmp/{document_id}/source.pdf` ;
- creer un fichier de statut local.

Frontend :

- creer la zone d'upload ;
- afficher nom, taille et erreurs du fichier ;
- appeler l'endpoint upload ;
- conserver `document_id` apres upload.

Tests :

- upload PDF valide ;
- refus fichier non PDF ;
- refus fichier de plus de 10 Mo ;
- refus PDF de plus de 10 pages ;
- refus ou erreur controlee pour PDF sans texte selectionnable.

### Semaine 3 - Traitement asynchrone simplifie

Backend :

- implementer `POST /api/documents/{document_id}/process` ;
- utiliser `FastAPI BackgroundTasks` ou un traitement simplifie equivalent ;
- ne pas introduire Celery, Redis ou RabbitMQ ;
- stocker le statut en memoire ou dans `storage/tmp/{document_id}/status.json` ;
- implementer `GET /api/documents/{document_id}/status`.

Frontend :

- creer la page de progression ;
- ajouter un polling simple sur le statut ;
- afficher l'etape courante et le pourcentage.

Tests :

- lancement d'un job ;
- statut `queued` puis `processing` ;
- statut `completed` ou `failed` ;
- comportement si le document n'existe pas.

### Semaine 4 - Extraction PDF et representation intermediaire

Backend :

- integrer PyMuPDF ;
- extraire pages, dimensions et blocs texte ;
- detecter titres et paragraphes simples ;
- detecter images ;
- detecter tableaux simples si possible ;
- representer les tableaux comme blocs `table` ;
- representer les images comme blocs `image` ;
- produire `storage/tmp/{document_id}/intermediate.json` ;
- ajouter `GET /api/documents/{document_id}/intermediate` pour debug MVP.

Tests :

- PDF avec titre et paragraphe ;
- PDF avec image ;
- PDF avec tableau simple ;
- PDF sans texte selectionnable ;
- JSON intermediaire valide.

### Semaine 5 - Traduction mockee et glossaire simple

Backend :

- definir l'interface `TranslationService` ;
- implementer `MockTranslationProvider` ;
- utiliser `MOCK_TRANSLATION_ENABLED=true` par defaut ;
- ajouter une detection de domaine simple avant traduction ;
- limiter les domaines MVP a `general`, `legal`, `technical`, `academic` et `business` ;
- implementer cette detection avec un mock ou quelques mots-cles pour le MVP ;
- traduire les blocs texte de facon deterministe pour tester le pipeline ;
- accepter un glossaire simple ;
- appliquer un controle terminologique basique.

Tests :

- detection de domaine `general` par defaut ;
- detection basique des domaines `legal`, `technical`, `academic` et `business` sur fixtures courtes ;
- traduction mockee d'un paragraphe ;
- traduction mockee de cellules de tableau ;
- glossaire respecte ;
- glossaire non respecte signale dans le rapport.

### Semaine 6 - Reconstruction DOCX

Backend :

- integrer `python-docx` ;
- generer `storage/tmp/{document_id}/translated.docx` ;
- reconstruire titres, paragraphes et tableaux simples ;
- inserer les images extraites ;
- implementer `GET /api/documents/{document_id}/download/docx`.

Tests :

- DOCX ouvrable ;
- titres et paragraphes lisibles ;
- tableau simple present ;
- image inseree si disponible ;
- bloc non traduit signale.

### Semaine 7 - Rapport de validation

Backend :

- generer `storage/tmp/{document_id}/report.json` ;
- implementer `GET /api/documents/{document_id}/report` ;
- calculer un score de confiance indicatif ;
- signaler blocs non traduits ;
- signaler textes potentiellement trop longs ;
- signaler tableaux suspects ;
- signaler images contenant possiblement du texte ;
- signaler incoherences terminologiques.

Frontend :

- creer la page rapport ;
- afficher score, alertes, severite, page et bloc.

Tests :

- rapport sans alerte ;
- rapport avec bloc non traduit ;
- rapport avec image suspecte ;
- rapport avec incoherence de glossaire.

### Semaine 8 - Parcours frontend complet et nettoyage

Frontend :

- connecter upload, progression, resultat et rapport ;
- ajouter les boutons de telechargement ;
- afficher clairement que le PDF est optionnel ;
- afficher les erreurs backend.

Backend :

- implementer `GET /api/documents/{document_id}/result` ;
- implementer `GET /api/documents/{document_id}/download/pdf` avec erreur controlee si non active ;
- ajouter purge automatique ou manuelle apres 24 heures.

Tests :

- parcours complet avec traduction mockee ;
- telechargement DOCX ;
- export PDF non active non bloquant ;
- suppression des fichiers apres 24 heures ou via commande de purge.

### Semaine 9 optionnelle - Integration LLM reelle

Cette etape commence uniquement apres validation du pipeline complet avec traduction mockee.

Backend :

- implementer `LLMTranslationProvider` ;
- ajouter variables `.env` pour le fournisseur ;
- garder `MOCK_TRANSLATION_ENABLED=true` en developpement ;
- construire les prompts ;
- valider les reponses JSON du LLM ;
- ajouter timeouts et retries limites ;
- documenter les couts et limites.

Tests :

- provider LLM desactive par defaut ;
- simulation timeout ;
- simulation reponse invalide ;
- comparaison comportement mock vs LLM.

### Semaine 10 optionnelle - Polish demo

- ameliorer les textes UI ;
- preparer 2 ou 3 PDF de demonstration ;
- verifier le temps de traitement ;
- verifier l'ouverture du DOCX ;
- relire le rapport de validation ;
- preparer un court scenario de presentation.

## 5. Taches frontend

- Page accueil sobre.
- Page upload.
- Composant drag and drop.
- Page progression avec polling.
- Page resultat.
- Page rapport.
- Gestion des erreurs API.
- Boutons telechargement DOCX et PDF optionnel.
- Affichage clair des limites MVP.

## 6. Taches backend

- API FastAPI minimale.
- Healthcheck.
- Upload PDF.
- Validation 10 Mo et 10 pages.
- Verification texte selectionnable.
- Stockage dans `storage/tmp/{document_id}/`.
- Traitement avec `FastAPI BackgroundTasks` ou equivalent simple.
- Statut en memoire ou fichier JSON.
- Logs des etapes du traitement sans contenu documentaire complet.
- Extraction PyMuPDF.
- Representation intermediaire.
- Detection de domaine simple.
- Traduction mockee.
- Reconstruction DOCX.
- Rapport de validation.
- Suppression automatique ou manuelle apres 24 heures.

## 7. Taches IA

- Ne pas commencer par le LLM reel.
- Definir `TranslationService`.
- Implementer `MockTranslationProvider` en premier.
- Ajouter `MOCK_TRANSLATION_ENABLED=true/false`.
- Valider le pipeline complet avec mock.
- Implementer `LLMTranslationProvider` seulement ensuite.
- Definir un format JSON strict pour les reponses LLM.
- Ajouter timeouts, retries et gestion des couts.

## 8. Taches de test

- Tests API healthcheck.
- Tests upload PDF valide.
- Tests fichier invalide.
- Tests limite 10 Mo.
- Tests limite 10 pages.
- Tests PDF sans texte selectionnable.
- Tests extraction PyMuPDF.
- Tests JSON intermediaire.
- Tests detection de domaine simple.
- Tests traduction mockee.
- Tests reconstruction DOCX.
- Tests rapport de validation.
- Test parcours complet frontend avec mock.
- Test PDF optionnel non bloquant.

## 9. Criteres de validation finale

Le MVP est valide si :

- le pipeline complet fonctionne avec traduction mockee ;
- aucun LLM reel n'est necessaire pour la demonstration technique de base ;
- le backend utilise un traitement asynchrone simplifie ;
- Celery, Redis et RabbitMQ ne sont pas requis ;
- les fichiers sont stockes dans `storage/tmp/{document_id}/` ;
- les fichiers peuvent etre supprimes apres 24 heures ;
- seuls les PDF numeriques avec texte selectionnable sont acceptes ;
- les limites 10 pages et 10 Mo sont appliquees ;
- un DOCX est produit ;
- l'absence de PDF exporte ne bloque pas la validation ;
- le rapport de validation indique les zones a verifier ;
- le frontend permet le parcours complet.

## 10. Checklist finale de demonstration

Avant la presentation, verifier :

- le backend demarre sans erreur ;
- le frontend demarre sans erreur ;
- `GET /api/health` retourne un statut valide ;
- les trois fixtures PDF sont disponibles : titres et paragraphes, tableau simple, image ;
- un PDF valide de moins de 10 Mo et 10 pages est accepte ;
- un fichier invalide est refuse proprement ;
- le statut de traitement progresse dans l'interface ;
- la detection de domaine affiche une valeur parmi `general`, `legal`, `technical`, `academic` ou `business` ;
- la traduction mockee permet de parcourir tout le pipeline sans LLM reel ;
- le DOCX final est genere et ouvrable ;
- le rapport de validation est consultable ;
- les logs backend montrent les etapes du traitement sans contenu complet du document ;
- l'export PDF est presente comme optionnel ;
- le message de limites MVP est clair pendant la demonstration.
