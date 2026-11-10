"""
Étape 1 bis — Diagnostic ciblé avant le nettoyage.

Usage :  python diagnostic.py data/mon_fichier.xlsx

Ne modifie rien et n'affiche AUCUNE donnée personnelle (ni nom, ni téléphone, ni adresse).
Les sorties peuvent être partagées telles quelles.
"""
import sys
import pandas as pd

pd.set_option("display.width", 140)
pd.set_option("display.max_colwidth", 60)

df = pd.read_excel(sys.argv[1], sheet_name="Commandes").drop_duplicates()

def titre(t):
    print("\n" + "=" * 70 + f"\n{t}\n" + "=" * 70)

# 1. Période couverte
titre("1. PÉRIODE")
print("Première commande :", df["Date de commande"].min())
print("Dernière commande :", df["Date de commande"].max())

# 2. Statuts : lesquels comptent comme une vente réalisée ?
titre("2. STATUTS (nb de commandes distinctes)")
print(df.groupby("Statut de la commande")["Numéro de commande"].nunique().sort_values(ascending=False).to_string())

# 3. Grain du fichier : une ligne = un article d'une commande ?
titre("3. ARTICLES PAR COMMANDE")
nb = df.groupby("Numéro de commande").size()
print(nb.value_counts().sort_index().head(10).rename("nb de commandes").to_string())

# Le montant total est-il répété à l'identique sur chaque ligne d'une même commande ?
montants = df.groupby("Numéro de commande")["Montant total de la commande"].nunique()
print("\nCommandes avec plusieurs montants totaux différents :", (montants > 1).sum())

# Montant total vs somme des coûts d'articles (frais de livraison ? quantités ?)
cmp = df.groupby("Numéro de commande").agg(
    montant=("Montant total de la commande", "first"),
    somme_articles=("Coût de l'article", "sum"),
)
cmp["ecart"] = cmp["montant"] - cmp["somme_articles"]
print("\nÉcart montant total - somme des articles (en FCFA) :")
print(cmp["ecart"].describe(percentiles=[.1, .5, .9]).round(0).to_string())

# 4. Montants aberrants
titre("4. MONTANTS ABERRANTS")
for seuil in [100, 1_000, 50_000_000, 1_000_000_000]:
    n_bas = (cmp["montant"] < seuil).sum() if seuil <= 1_000 else None
    n_haut = (cmp["montant"] > seuil).sum() if seuil > 1_000 else None
    if n_bas is not None:
        print(f"Commandes < {seuil:>13,} FCFA : {n_bas}")
    else:
        print(f"Commandes > {seuil:>13,} FCFA : {n_haut}")
print("\n10 plus gros montants (n° de commande, montant, somme des articles) :")
print(cmp.sort_values("montant", ascending=False).head(10)[["montant", "somme_articles"]].to_string())

# 5. Villes : ampleur du travail de normalisation
titre("5. VILLES (30 valeurs les plus fréquentes)")
villes = df.drop_duplicates("Numéro de commande")["Ville (facturation)"].astype(str).str.strip()
print(villes.value_counts().head(30).to_string())
print(f"\nLes 30 premières valeurs couvrent {villes.value_counts().head(30).sum() / len(villes):.0%} des commandes.")

# 6. Catégories : la colonne contient une liste séparée par des virgules
titre("6. CATÉGORIES (éléments les plus fréquents)")
cats = df["Catégorie"].dropna().str.split(",").explode().str.strip()
print(cats.value_counts().head(30).to_string())
print("\nNombre de catégories par article :")
print(df["Catégorie"].dropna().str.count(",").add(1).value_counts().sort_index().to_string())

# 7. Lignes sans UGS / catégorie / vendeur : sont-ce les mêmes ?
titre("7. LIGNES INCOMPLÈTES")
manque = df[["UGS", "Catégorie", "Vendeur de produit"]].isna()
print("Lignes sans UGS, catégorie ET vendeur :", manque.all(axis=1).sum())
print("Lignes avec au moins un des trois manquant :", manque.any(axis=1).sum())

# 8. Vendeurs
titre("8. VENDEURS (15 premiers par nombre de lignes)")
print(df["Vendeur de produit"].value_counts().head(15).to_string())
