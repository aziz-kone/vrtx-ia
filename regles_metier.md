# Règles métier — base des commandes de la marketplace

Ce fichier est lu par l'IA avant chaque question. Écris-le comme pour un nouvel analyste
qui arrive dans l'équipe : ce que signifient les données et les pièges à éviter.
Complète-le chaque fois que l'IA se trompe sur une notion métier.

## Contexte
- Marketplace e-commerce multi-vendeurs en Côte d'Ivoire. Montants en FCFA.
- Une commande peut contenir plusieurs articles, vendus par des vendeurs différents.

## Tables et vues
- `v_ventes` : une ligne par commande VENDUE (statut « Terminée ») et au montant fiable. À utiliser par défaut.
- `v_lignes_ventes` : une ligne par article des commandes vendues, avec la date, la ville et le client de la commande.
- `commandes` et `lignes_commande` : toutes les commandes, tous statuts confondus. À utiliser seulement
  pour une question sur les statuts, les annulations, les commandes en attente ou les montants suspects.

## Définitions
- Chiffre d'affaires (CA) d'une période : `SUM(montant_total)` sur `v_ventes`. Il inclut les frais de livraison.
- CA par produit, catégorie ou vendeur : `SUM(montant_ligne)` sur `v_lignes_ventes` (hors frais de livraison).
  Ne jamais sommer `montant_total` depuis une table de lignes : il serait compté une fois par article.
- Panier moyen : `AVG(montant_total)` sur `v_ventes`.
- Nombre de clients : `COUNT(DISTINCT client_id)`. Un client fidèle a au moins 2 commandes vendues.
- Taux d'annulation : commandes au statut « Annulée » / toutes les commandes, sur la table `commandes`.
- « Abidjan » regroupe les communes (Cocody, Yopougon…). Commune « Non précisée » = adresse à Abidjan sans commune.

## Confidentialité
- `client_id` est un identifiant anonyme. Ne jamais l'afficher seul dans un résultat, seulement le compter.