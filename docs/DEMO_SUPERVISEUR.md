# DEMO SUPERVISEUR - DocTranslate AI

## 1. Presentation du projet

DocTranslate AI est un moteur de traduction et de reconstruction documentaire assiste par IA.

Le projet vise a traiter des PDF numeriques en anglais, a en extraire la structure, a traduire les contenus en francais, puis a reconstruire un PDF final lisible et exploitable.

L'objectif n'est pas de produire un simple traducteur de texte. Le systeme cherche a comprendre la structure documentaire avant traduction :

- detection des pages ;
- extraction des blocs de texte ;
- identification de titres, paragraphes, listes, notes, images et tableaux simples ;
- traduction par blocs logiques ;
- evaluation de la qualite ;
- reconstruction d'un PDF traduit par overlay.

Le projet reste un MVP : il privilegie une architecture claire, demonstrable et testable, sans pretendre atteindre une fidelite parfaite pixel par pixel.

## 2. Etat actuel du MVP

Le MVP fonctionne principalement sur :

- PDF numeriques propres ;
- texte selectionnable ;
- documents simples a moderement structures ;
- documents de 1 a 10 pages pour la demonstration ;
- tableaux simples ;
- tableaux noir et blanc avec bordures et structure reguliere.

Le systeme est actuellement adapte a une demonstration technique superviseur : il montre un pipeline complet, depuis l'import du PDF jusqu'au telechargement d'un PDF traduit.

Les meilleurs resultats sont obtenus avec des documents dont la mise en page reste relativement stable : paragraphes clairs, tableaux reguliers, peu de zones graphiques complexes.

## 3. Pipeline technique actuel

Le pipeline actuellement implemente suit les etapes suivantes :

```text
Upload PDF
-> Extraction structuree
-> Detection des blocs
-> Segmentation logique
-> Traduction IA contextuelle
-> Quality scoring
-> Nettoyage des residus
-> Reconstruction PDF overlay
-> Telechargement du PDF traduit
```

Chaque etape produit ou enrichit une representation intermediaire du document, principalement stockee dans `intermediate.json`.

Ce fichier sert de pivot technique : il contient les pages, les blocs, les coordonnees, les textes sources, les textes traduits, les warnings et les signaux de qualite.

## 4. Architecture backend

Le backend est construit avec :

- Python ;
- FastAPI ;
- PyMuPDF ;
- pytest.

Les responsabilites backend sont separees en services specialises :

- `extraction_service` : extraction PDF, detection des blocs, segmentation logique, tableaux simples, images natives ;
- `translation_service` : orchestration de la traduction, contexte documentaire, nettoyage post-traduction ;
- `quality_service` : scoring qualite, detection de residus anglais, risque d'overlay, confiance semantique ;
- `pdf_overlay_service` : generation du PDF traduit par overlay ;
- `section_service` : structuration logique en sections ;
- `batch_service` : architecture experimentale pour traitement par lots.

Cette separation permet de tester chaque partie du pipeline et de faire evoluer le systeme sans concentrer toute la logique dans une seule fonction.

## 5. Architecture frontend

Le frontend utilise :

- Next.js ;
- React ;
- TypeScript ;
- Tailwind CSS.

L'interface permet actuellement :

- l'import d'un PDF ;
- l'affichage des contraintes MVP ;
- le lancement du traitement ;
- le suivi de l'etat du document ;
- la generation du PDF traduit ;
- le telechargement du resultat.

L'interface reste volontairement simple pour le MVP. L'objectif prioritaire est de rendre le pipeline utilisable et demonstrable avant d'ajouter des fonctions avancees d'edition ou de comparaison visuelle.

## 6. Reconstruction PDF par overlay

La reconstruction PDF repose sur PyMuPDF et utilise le PDF source comme base.

Le moteur conserve les pages, fonds, images natives et elements graphiques du PDF original autant que possible. Il remplace ensuite le texte source par le texte traduit.

Le moteur d'overlay fonctionne maintenant en deux passes :

- PASS 1 : masquage des zones de texte source ;
- PASS 2 : ecriture du texte traduit dans les zones correspondantes.

La logique distingue clairement deux decisions :

- `should_mask_source_block` : determine si un bloc source doit etre masque ;
- `should_write_translation` : determine si une traduction doit etre ecrite.

Cette separation evite qu'un bloc source soit laisse visible uniquement parce que sa traduction est incertaine.

Un fallback existe egalement : si une zone est masquee mais que la traduction est rejetee ou incomplete, le systeme ecrit une sortie visible de revue au lieu de laisser une zone vide.

Limites actuelles :

- le rendu reste approximatif ;
- le positionnement n'est pas pixel-perfect ;
- certains textes longs peuvent etre reduits ou signales comme a risque ;
- les documents tres graphiques restent difficiles.

## 7. Quality scoring

Le systeme calcule des scores de qualite non bloquants sur les blocs traduits.

Ces scores aident a detecter :

- fragments PDF parasites ;
- residus anglais ;
- risque de debordement dans l'overlay ;
- faible coherence semantique ;
- faible confiance sur la structure des tableaux.

Les signaux de qualite ne remplacent pas une validation humaine, mais ils rendent le pipeline plus inspectable. Ils permettent aussi de comprendre pourquoi certaines zones doivent etre relues ou corrigees.

Exemples de warnings :

- `english_residual_detected` ;
- `high_overlay_risk` ;
- `low_semantic_consistency` ;
- `weak_table_grid` ;
- `table_cell_english_residual_cleaned`.

## 8. Gestion des tableaux

Le projet prend maintenant en charge des tableaux simples.

La logique actuelle couvre :

- detection de regions tabulaires ;
- regroupement des lignes ;
- detection et stabilisation des colonnes ;
- reconstruction d'une grille logique ;
- traduction cellule par cellule ;
- overlay cellule par cellule ;
- nettoyage specifique des residus anglais dans les cellules.

Des ameliorations recentes ont corrige plusieurs problemes observes :

- colonnes 3 et 4 parfois perdues ou mal rendues ;
- cellules courtes ignorees ;
- derniere ligne de tableau absorbee par un paragraphe ;
- residus anglais en fin de cellule, par exemple `Reduced`, `Data`, `Personalized`, `Higher Consumer`.

Le moteur donne ses meilleurs resultats avec des tableaux noir et blanc, simples, reguliers, et avec des bordures visibles ou une structure spatiale claire.

Les tableaux suivants restent experimentaux :

- tableaux colores ou tres stylises ;
- tableaux sans alignement stable ;
- cellules fusionnees ;
- tableaux imbriques ;
- tableaux repartis sur plusieurs pages ;
- tableaux issus d'images ou de scans.

## 9. Skill IA du projet

Le dossier `skills/doctranslate-ai` documente un skill destine a aider un assistant de developpement comme Codex ou Claude Code a travailler sur le projet.

Ce skill permet de :

- comprendre le pipeline technique ;
- inspecter `intermediate.json` ;
- analyser les warnings ;
- diagnostiquer les erreurs d'overlay ;
- verifier si les traductions sont pretes avant generation PDF ;
- identifier les zones non traduites ou suspectes ;
- guider les evolutions techniques.

Il contient aussi des scripts utiles, par exemple pour inspecter un document traite ou lancer les tests backend.

Cette approche rend le projet plus demonstrable : le systeme n'est pas seulement une application, mais aussi un environnement de diagnostic et d'amelioration assiste par IA.

## 10. Tests automatises

Le backend dispose d'une suite pytest couvrant les principales fonctions du MVP :

- upload PDF ;
- validation fichier ;
- extraction PDF ;
- segmentation logique ;
- detection des tableaux ;
- traduction mockee et LLM ;
- generation DOCX ;
- generation PDF overlay ;
- quality scoring ;
- sections ;
- batch service ;
- statuts de traitement ;
- erreurs controlees.

Pendant le developpement, la suite backend a atteint plus de 130 tests automatises valides.

Dernier etat observe pendant les iterations recentes :

```text
157 tests backend valides
```

Ce resultat ne signifie pas que le systeme est parfait, mais il montre que les principaux comportements du MVP sont verifies automatiquement.

## 11. Limites actuelles du MVP

Le MVP ne gere pas encore :

- OCR ;
- PDF scannes ;
- tableaux tres complexes ;
- cellules fusionnees ;
- reconstruction pixel-perfect ;
- tres longs documents en production ;
- documents fortement graphiques ;
- remplacement de texte dans les images ;
- comparaison visuelle automatique entre PDF source et PDF traduit.

Certaines limites sont volontaires. Pour une demonstration superviseur, le perimetre est centre sur les PDF numeriques propres et les cas documentaires realistes mais maitrisables.

## 12. Travaux futurs

Les prochaines evolutions possibles sont :

- architecture batch plus robuste pour documents longs ;
- support plus fiable de documents jusqu'a 100 pages en mode experimental ;
- amelioration des tableaux complexes ;
- gestion des cellules fusionnees ;
- meilleure detection des regions de layout ;
- multi-provider LLM ;
- glossaires metiers plus avances ;
- rapport qualite automatique ;
- OCR dans une version ulterieure ;
- comparaison visuelle source/resultat ;
- interface utilisateur plus professionnelle ;
- historique et gestion de documents ;
- securisation avancee pour documents sensibles.

## 13. Workflow de demonstration

Un workflow de demonstration simple peut etre :

1. Importer un PDF numerique propre.
2. Lancer le traitement.
3. Inspecter le statut du document.
4. Verifier `intermediate.json` si necessaire.
5. Generer le PDF traduit.
6. Telecharger le resultat.
7. Commenter les warnings et les limites observees.

Endpoints principaux :

```text
POST /api/documents/upload
POST /api/documents/{document_id}/process
GET  /api/documents/{document_id}/status
GET  /api/documents/{document_id}/intermediate
POST /api/documents/{document_id}/generate-pdf
GET  /api/documents/{document_id}/download/pdf
```

Commandes utiles :

```powershell
cd backend
python -m pytest
uvicorn app.main:app --reload
```

```powershell
cd frontend
npm run dev
```

## 14. Conclusion

DocTranslate AI est un MVP technique serieux de traduction et reconstruction documentaire.

Le projet montre un pipeline complet combinant extraction PDF, segmentation logique, traduction IA, validation qualite et reconstruction PDF. Il ne pretend pas resoudre tous les problemes complexes du PDF, mais il pose une base extensible, testable et demonstrable.

Les limites sont assumees : pas d'OCR, pas de pixel-perfect, pas de support complet des documents complexes. En revanche, l'architecture actuelle permet d'ameliorer progressivement chaque composant du pipeline.

Pour une presentation superviseur, le projet illustre une comprehension concrete des difficultes liees a la traduction documentaire haute fidelite : structure, contexte, qualite linguistique, contraintes de layout, tests automatises et diagnostic assiste par IA.
