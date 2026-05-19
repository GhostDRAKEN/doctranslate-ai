# Specification frontend

## Objectif

Construire une interface web claire permettant d'uploader un PDF, suivre le traitement, recuperer le document traduit et consulter le rapport de validation.

## Stack

- Next.js.
- TypeScript.
- Tailwind CSS.
- Fetch ou client HTTP leger.
- Gestion d'etat locale pour le MVP.

## Structure des pages

```text
frontend/
  src/
    pages/ ou app/
      index
      upload
      documents/[documentId]/progress
      documents/[documentId]/result
      documents/[documentId]/report
    components/
    services/
    types/
    styles/
```

## Composants React

- `AppLayout`
- `UploadDropzone`
- `FileSummary`
- `ProgressSteps`
- `StatusBadge`
- `ResultActions`
- `ValidationReportTable`
- `IssueSeverityBadge`
- `ErrorState`
- `LoadingState`

## Gestion d'etat

Etats principaux :

- fichier selectionne ;
- erreur upload ;
- `document_id` ;
- statut de traitement ;
- resultat ;
- rapport.

Pour le MVP, `useState`, `useEffect` et un service API suffisent. Une librairie comme TanStack Query peut etre ajoutee si le projet grandit.

## Appels API

Service `apiClient` :

- `getHealth()`
- `uploadDocument(file)`
- `processDocument(documentId, options)`
- `getDocumentStatus(documentId)`
- `getDocumentResult(documentId)`
- `getValidationReport(documentId)`
- `getDocxDownloadUrl(documentId)`
- `getPdfDownloadUrl(documentId)`
- `getIntermediate(documentId)` pour debug developpeur uniquement

## Contrats API consommes par le frontend

- `GET /api/health` : verifier que le backend est disponible.
- `POST /api/documents/upload` : envoyer le PDF.
- `POST /api/documents/{document_id}/process` : lancer le traitement.
- `GET /api/documents/{document_id}/status` : suivre la progression.
- `GET /api/documents/{document_id}/result` : recuperer les metadonnees du resultat.
- `GET /api/documents/{document_id}/report` : afficher le rapport de validation.
- `GET /api/documents/{document_id}/download/docx` : telecharger le DOCX prioritaire.
- `GET /api/documents/{document_id}/download/pdf` : telecharger le PDF si l'export optionnel est disponible.
- `GET /api/documents/{document_id}/intermediate` : outil debug developpeur uniquement, non expose comme fonctionnalite produit.

## Affichage progression

- Polling toutes les 2 a 3 secondes.
- Arret du polling si `completed`, `failed` ou `expired`.
- Affichage de l'etape courante.
- Message rassurant si la traduction dure longtemps.

## Design system minimal

- `Button` : primary, secondary, danger.
- `Input` : fichier et champs simples.
- `Card` : resume ou item.
- `Badge` : statuts et severites.
- `Alert` : erreurs et warnings.
- `Table` : rapport de validation.

## Gestion upload

- Drag and drop.
- Validation immediate extension/taille.
- Contraintes visibles : PDF uniquement, 10 Mo maximum, 10 pages maximum, texte selectionnable requis.
- Desactivation du bouton pendant upload.
- Affichage des erreurs backend.

## Affichage resultat

- Montrer le statut final.
- Telechargement DOCX prioritaire.
- Afficher PDF seulement si disponible.
- Afficher le score de confiance.
- Lien vers rapport.

## Affichage erreurs

- Erreurs utilisateur : message clair.
- Erreurs techniques : message general + code.
- Ne pas afficher de stack trace.
- Permettre de revenir a l'upload.

## Criteres d'acceptation

- L'interface permet un parcours complet upload -> resultat.
- Le polling s'arrete correctement.
- Les erreurs API sont visibles.
- Le rapport est lisible.
- Les boutons de telechargement fonctionnent quand les fichiers existent.

## Tests a prevoir

- Test composant upload.
- Test affichage erreur fichier invalide.
- Test affichage erreur fichier de plus de 10 Mo.
- Test affichage erreur PDF de plus de 10 pages.
- Test affichage erreur PDF sans texte selectionnable.
- Test progression avec statut mocke.
- Test rapport avec issues.
- Test bouton download.
